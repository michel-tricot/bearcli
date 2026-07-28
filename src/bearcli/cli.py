"""Typer CLI for reading notes from the Bear note app."""

from __future__ import annotations

import base64
import json
import re
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from rich import box
from rich.console import Console
from rich.markup import escape as rich_escape
from rich.table import Table

from bearcli import actions
from bearcli.db import DEFAULT_DB_PATH, AmbiguousNoteId, BearDB, Note, note_metadata
from bearcli.export import export_notes
from bearcli.gitsync import GitError, export_and_push
from bearcli.markdown import rewrite_attachment_refs
from bearcli.search import naive_search, search_notes
from bearcli.secrets import SecretFinding, redact_text, redaction_map, scan_notes

app = typer.Typer(help="Read notes from the Bear note app.", no_args_is_help=True, add_completion=False)
note_app = typer.Typer(help="Create, read, and modify notes.", no_args_is_help=True)
tag_app = typer.Typer(help="List and manage tags.", no_args_is_help=True)
app.add_typer(note_app, name="note")
app.add_typer(tag_app, name="tag")
console = Console()


class OutputFormat(StrEnum):
    table = "table"
    json = "json"
    text = "text"


class OnlyFilter(StrEnum):
    pinned = "pinned"
    encrypted = "encrypted"
    trashed = "trashed"
    archived = "archived"


def _note_to_dict(note: Note, with_text: bool = False) -> dict:
    data = note_metadata(note)
    if with_text:
        data["text"] = note.text
        data["attachments"] = [
            {
                "filename": a.filename,
                "path": str(a.path),
                "size": a.size,
                "exists": a.exists,
            }
            for a in note.attachments
        ]
    return data


def _note_status(note: Note) -> str:
    flags = (
        ("pinned", note.pinned),
        ("encrypted", note.encrypted),
        ("trashed", note.trashed),
        ("archived", note.archived),
    )
    return ",".join(s for s, on in flags if on)


def _resolve_attachments(note: Note) -> str:
    """Rewrite attachment links to the files' absolute paths on disk."""
    return rewrite_attachment_refs(note, lambda att: str(att.path))


DbPathOption = Annotated[
    Path,
    typer.Option("--db", envvar="BEAR_DB_PATH", help="Path to the Bear SQLite database."),
]


def _open_db(path: Path) -> BearDB:
    try:
        return BearDB(path)
    except FileNotFoundError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from None


def _parse_date(value: str | None, option: str) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        console.print(
            f"[red]Error:[/red] invalid date for {option}: {value!r} "
            "(expected ISO format, e.g. 2026-07-01 or 2026-07-01T14:30)"
        )
        raise typer.Exit(2) from None


@note_app.command("list")
def list_notes(
    limit: Annotated[int, typer.Option("--limit", "-n", help="Maximum number of notes.")] = 20,
    tag: Annotated[
        str | None,
        typer.Option("--tag", "-t", help="Only notes with this tag (includes nested sub-tags)."),
    ] = None,
    modified_after: Annotated[
        str | None, typer.Option("--modified-after", help="Modified on or after this date.")
    ] = None,
    modified_before: Annotated[str | None, typer.Option("--modified-before", help="Modified before this date.")] = None,
    created_after: Annotated[str | None, typer.Option("--created-after", help="Created on or after this date.")] = None,
    created_before: Annotated[str | None, typer.Option("--created-before", help="Created before this date.")] = None,
    only: Annotated[
        OnlyFilter | None,
        typer.Option(
            "--only",
            help="Only notes with this status: pinned, encrypted, trashed, or archived.",
        ),
    ] = None,
    all_notes: Annotated[bool, typer.Option("--all", "-a", help="No limit (overrides --limit).")] = False,
    trashed: Annotated[bool, typer.Option("--trashed", help="Include trashed notes.")] = False,
    archived: Annotated[bool, typer.Option("--archived", help="Include archived notes.")] = False,
    ids_only: Annotated[bool, typer.Option("--ids", help="Print only note identifiers, one per line.")] = False,
    fmt: Annotated[
        OutputFormat,
        typer.Option(
            "--format",
            "-f",
            help="Output format: table, json, or text (tab-separated: id, modified, tags, title).",
        ),
    ] = OutputFormat.table,
    db_path: DbPathOption = DEFAULT_DB_PATH,
) -> None:
    """List notes, most recently modified first."""
    db = _open_db(db_path)
    try:
        notes = db.list_notes(
            limit=None if all_notes else limit,
            tag=tag,
            created_after=_parse_date(created_after, "--created-after"),
            created_before=_parse_date(created_before, "--created-before"),
            modified_after=_parse_date(modified_after, "--modified-after"),
            modified_before=_parse_date(modified_before, "--modified-before"),
            only=only.value if only else None,
            include_trashed=trashed,
            include_archived=archived,
        )
    finally:
        db.close()

    if ids_only:
        for note in notes:
            print(note.id)
        return

    if fmt is OutputFormat.json:
        print(json.dumps([_note_to_dict(n) for n in notes], indent=2, ensure_ascii=False))
        return

    if fmt is OutputFormat.text:
        for note in notes:
            modified = note.modified.isoformat() if note.modified else ""
            print(f"{note.id}\t{modified}\t{','.join(note.tags)}\t{_note_status(note)}\t{note.title}")
        return

    if not notes:
        console.print("No notes found.")
        return

    table = Table(box=box.ROUNDED, header_style="bold")
    table.add_column("ID", style="dim", no_wrap=True)
    table.add_column("Title", overflow="ellipsis", max_width=50)
    table.add_column("Tags", style="cyan", overflow="ellipsis", max_width=30)
    table.add_column("Status", style="yellow", no_wrap=True)
    table.add_column("Modified", no_wrap=True)
    for note in notes:
        table.add_row(
            note.id,
            note.title,
            ", ".join(note.tags),
            _note_status(note),
            note.modified.strftime("%Y-%m-%d %H:%M") if note.modified else "",
        )
    console.print(table)


@note_app.command()
def get(
    note_id: Annotated[str, typer.Argument(help="Note identifier (UUID from `bearcli list`).")],
    meta: Annotated[bool, typer.Option("--meta", help="Print metadata frontmatter before the content.")] = False,
    resolve_attachments: Annotated[
        bool,
        typer.Option(
            "--resolve-attachments",
            "-r",
            help="Rewrite attachment references in the content to absolute file paths.",
        ),
    ] = False,
    redact_secrets: Annotated[
        bool,
        typer.Option("--redact-secrets", help="Replace detected secrets with a [redacted: <rule>] placeholder."),
    ] = False,
    fmt: Annotated[
        OutputFormat,
        typer.Option(
            "--format",
            "-f",
            help="Output format: text (raw content), json (metadata + content), or table.",
        ),
    ] = OutputFormat.text,
    db_path: DbPathOption = DEFAULT_DB_PATH,
) -> None:
    """Print the content of a note."""
    db = _open_db(db_path)
    try:
        note = _require_note(db, note_id)
    finally:
        db.close()

    if note.encrypted or note.text is None:
        console.print(f"[red]Error:[/red] note {note.id} is encrypted; its content is unavailable")
        raise typer.Exit(1)

    text = _resolve_attachments(note) if resolve_attachments else note.text
    if redact_secrets and text is not None:
        note_secrets = redaction_map(scan_notes([note])).get(note.id, {})
        text = redact_text(text, note_secrets)

    if fmt is OutputFormat.json:
        data = _note_to_dict(note, with_text=True)
        data["text"] = text
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return

    if fmt is OutputFormat.table:
        table = Table(box=box.ROUNDED, show_header=False)
        table.add_column(style="bold")
        table.add_column()
        table.add_row("ID", note.id)
        table.add_row("Title", note.title)
        table.add_row("Tags", ", ".join(note.tags))
        if note.created:
            table.add_row("Created", note.created.strftime("%Y-%m-%d %H:%M"))
        if note.modified:
            table.add_row("Modified", note.modified.strftime("%Y-%m-%d %H:%M"))
        for i, att in enumerate(note.attachments):
            label = "Attachments" if i == 0 else ""
            missing = "" if att.exists else " (missing)"
            table.add_row(label, f"{att.path}{missing}")
        console.print(table)
        console.print()
        print(text)
        return

    if meta:
        print("---")
        print(f"id: {note.id}")
        print(f"title: {note.title}")
        print(f"tags: [{', '.join(note.tags)}]")
        if note.created:
            print(f"created: {note.created.isoformat()}")
        if note.modified:
            print(f"modified: {note.modified.isoformat()}")
        if note.attachments:
            print(f"attachments: [{', '.join(str(a.path) for a in note.attachments)}]")
        print("---")
    print(text)


def _report_secrets(findings: list[SecretFinding]) -> None:
    table = Table(box=box.ROUNDED, header_style="bold")
    table.add_column("Note", overflow="ellipsis", max_width=30)
    table.add_column("ID", style="dim", no_wrap=True)
    table.add_column("Rule", style="yellow")
    table.add_column("Line", justify="right")
    table.add_column("Match", style="red")
    for f in findings:
        table.add_row(f.note_title, f.note_id, f.rule, str(f.line), f.excerpt)
    console.print(table)
    notes = len({f.note_id for f in findings})
    console.print(
        f"[red]Export blocked:[/red] {len(findings)} potential secret(s) in {notes} note(s). "
        "Move them somewhere safe (or into an encrypted note), re-run with --redact-secrets "
        "to export with placeholders, or with --allow-secrets to export as-is."
    )


@app.command()
def export(
    dest: Annotated[Path, typer.Argument(help="Destination directory for the markdown files.")],
    sync: Annotated[
        bool,
        typer.Option(
            "--sync",
            help="Only rewrite notes that changed since the last export instead of everything.",
        ),
    ] = False,
    push: Annotated[
        bool,
        typer.Option(
            "--push",
            help="Treat DEST as a git clone: commit the export and push. Bear is the source of "
            "truth — remote or manual edits are kept in history but overwritten in HEAD.",
        ),
    ] = False,
    allow_secrets: Annotated[
        bool,
        typer.Option("--allow-secrets", help="Export even if the secret scan finds potential credentials."),
    ] = False,
    redact_secrets: Annotated[
        bool,
        typer.Option(
            "--redact-secrets",
            help="Export with detected secrets replaced by a [redacted: <rule>] placeholder "
            "(notes in Bear are untouched).",
        ),
    ] = False,
    db_path: DbPathOption = DEFAULT_DB_PATH,
) -> None:
    """Export all notes as markdown files with frontmatter and attachments."""
    if allow_secrets and redact_secrets:
        console.print("[red]Error:[/red] --allow-secrets and --redact-secrets are mutually exclusive")
        raise typer.Exit(2)
    db = _open_db(db_path)
    try:
        redactions: dict[str, dict[str, str]] | None = None
        if not allow_secrets:
            with console.status("Scanning notes for secrets…", spinner="dots"):
                candidates = db.list_notes(limit=None, include_archived=True, with_text=True)
                findings = scan_notes(candidates)
            if findings and not redact_secrets:
                _report_secrets(findings)
                raise typer.Exit(1)
            if findings:
                redactions = redaction_map(findings)
        with console.status("Exporting…", spinner="dots") as status:
            update = lambda msg: status.update(rich_escape(msg))  # noqa: E731
            if push:
                try:
                    result, outcome = export_and_push(db, dest, sync=sync, progress=update, redactions=redactions)
                except GitError as exc:
                    console.print(f"[red]Error:[/red] {exc}")
                    raise typer.Exit(1) from None
            else:
                result = export_notes(db, dest, sync=sync, progress=update, redactions=redactions)
    finally:
        db.close()

    parts = [f"{result.written} written"]
    if push:
        parts.append(outcome)
    if sync:
        parts.append(f"{result.unchanged} unchanged")
    if result.removed:
        parts.append(f"{result.removed} removed")
    if result.skipped_encrypted:
        parts.append(f"{result.skipped_encrypted} encrypted skipped")
    if result.index_updated:
        parts.append("index updated")
    if redactions:
        secrets_count = sum(len(v) for v in redactions.values())
        parts.append(f"{secrets_count} secret(s) redacted in {len(redactions)} note(s)")
    console.print(f"Exported to {dest}: " + ", ".join(parts))


def _text_or_stdin(text: str | None) -> str | None:
    if text is None and not sys.stdin.isatty():
        return sys.stdin.read()
    return text


def _require_note(db: BearDB, note_id: str) -> Note:
    try:
        note = db.get_note(note_id)
    except AmbiguousNoteId as exc:
        console.print(f"[red]Error:[/red] note id prefix {exc.prefix!r} matches several notes:")
        for full_id, title in exc.matches:
            console.print(f"  {full_id}  {title}")
        raise typer.Exit(1) from None
    if note is None:
        console.print(f"[red]Error:[/red] no note with id {note_id!r}")
        raise typer.Exit(1)
    return note


def _verify(ok: Callable[[], bool], success: str, failure: str) -> None:
    if actions.wait_for(ok):
        console.print(success)
    else:
        console.print(f"[red]Error:[/red] {failure}")
        raise typer.Exit(1)


def _create_and_report(db: BearDB, title: str, text: str | None, tags: list[str] | None) -> None:
    started = datetime.now(UTC)
    actions.create_note(title, text=text, tags=tags)

    def find_created() -> Note | None:
        candidates = db.list_notes(limit=10)
        return next(
            (n for n in candidates if n.title == title and n.created and n.created >= started - timedelta(seconds=5)),
            None,
        )

    if actions.wait_for(lambda: find_created() is not None):
        created = find_created()
        console.print(f"Created note {created.id}" if created else "Created note")
    else:
        console.print("[red]Error:[/red] note did not appear in the Bear database; is Bear able to run?")
        raise typer.Exit(1)


@note_app.command()
def create(
    title: Annotated[str, typer.Argument(help="Title of the new note.")],
    text: Annotated[str | None, typer.Option("--text", help="Note body (reads stdin if piped).")] = None,
    tags: Annotated[list[str] | None, typer.Option("--tag", "-t", help="Tag to add (repeatable).")] = None,
    db_path: DbPathOption = DEFAULT_DB_PATH,
) -> None:
    """Create a new note in Bear."""
    db = _open_db(db_path)
    try:
        _create_and_report(db, title, _text_or_stdin(text), tags)
    finally:
        db.close()


@note_app.command()
def append(
    note_id: Annotated[str, typer.Argument(help="Note identifier.")],
    text: Annotated[str | None, typer.Option("--text", help="Text to add (reads stdin if piped).")] = None,
    prepend: Annotated[bool, typer.Option("--prepend", help="Add at the top instead of the bottom.")] = False,
    db_path: DbPathOption = DEFAULT_DB_PATH,
) -> None:
    """Append (or prepend) text to an existing note."""
    body = _text_or_stdin(text)
    if body is None:
        console.print("[red]Error:[/red] provide --text or pipe content on stdin")
        raise typer.Exit(2)
    db = _open_db(db_path)
    try:
        before = _require_note(db, note_id)
        actions.add_text(before.id, body, mode="prepend" if prepend else "append")
        _verify(
            lambda: (
                (n := db.get_note(before.id)) is not None
                and n.modified is not None
                and (before.modified is None or n.modified > before.modified)
            ),
            f"Updated note {before.id}",
            "note was not modified; is Bear able to run?",
        )
    finally:
        db.close()


@note_app.command()
def trash(
    note_id: Annotated[str, typer.Argument(help="Note identifier.")],
    db_path: DbPathOption = DEFAULT_DB_PATH,
) -> None:
    """Move a note to Bear's trash."""
    db = _open_db(db_path)
    try:
        note = _require_note(db, note_id)
        if note.trashed:
            console.print(f"Note {note.id} is already in the trash")
            return
        actions.trash_note(note.id)
        _verify(
            lambda: (n := db.get_note(note.id)) is not None and n.trashed,
            f"Trashed note {note.id}",
            "note was not trashed; is Bear able to run?",
        )
    finally:
        db.close()


@note_app.command()
def archive(
    note_id: Annotated[str, typer.Argument(help="Note identifier.")],
    db_path: DbPathOption = DEFAULT_DB_PATH,
) -> None:
    """Archive a note."""
    db = _open_db(db_path)
    try:
        note = _require_note(db, note_id)
        if note.archived:
            console.print(f"Note {note.id} is already archived")
            return
        actions.archive_note(note.id)
        _verify(
            lambda: (n := db.get_note(note.id)) is not None and n.archived,
            f"Archived note {note.id}",
            "note was not archived; is Bear able to run?",
        )
    finally:
        db.close()


@tag_app.command("list")
def tags(
    fmt: Annotated[
        OutputFormat,
        typer.Option("--format", "-f", help="Output format: table, json, or text (tab-separated: count, tag)."),
    ] = OutputFormat.table,
    include_empty: Annotated[
        bool, typer.Option("--all", "-a", help="Include empty tags (Bear keeps them hidden after their last note).")
    ] = False,
    db_path: DbPathOption = DEFAULT_DB_PATH,
) -> None:
    """List all tags with their note counts."""
    db = _open_db(db_path)
    try:
        all_tags = db.list_tags(include_empty=include_empty)
    finally:
        db.close()

    if fmt is OutputFormat.json:
        print(json.dumps([{"tag": t, "notes": c} for t, c in all_tags], indent=2, ensure_ascii=False))
        return
    if fmt is OutputFormat.text:
        for t, c in all_tags:
            print(f"{c}\t{t}")
        return

    table = Table(box=box.ROUNDED, header_style="bold")
    table.add_column("Tag", style="cyan")
    table.add_column("Notes", justify="right")
    for t, c in all_tags:
        table.add_row(t, str(c))
    console.print(table)


def _tag_marker(name: str) -> str:
    # Tags containing anything beyond word chars, '/', or '-' need the #...# form.
    return f"#{name}#" if re.search(r"[^\w/-]", name) else f"#{name}"


def _has_tag(note: Note, name: str) -> bool:
    return name.lower() in (t.lower() for t in note.tags)


@note_app.command()
def tag(
    note_id: Annotated[str, typer.Argument(help="Note identifier.")],
    name: Annotated[str, typer.Argument(help="Tag to add (without the leading #).")],
    db_path: DbPathOption = DEFAULT_DB_PATH,
) -> None:
    """Add a tag to a note."""
    db = _open_db(db_path)
    try:
        note = _require_note(db, note_id)
        if _has_tag(note, name):
            console.print(f"Note {note.id} already has tag {name!r}")
            return
        actions.add_text(note.id, _tag_marker(name), mode="append")
        _verify(
            lambda: (n := db.get_note(note.id)) is not None and _has_tag(n, name),
            f"Tagged note {note.id} with {name!r}",
            "tag did not appear; is Bear able to run?",
        )
    finally:
        db.close()


@note_app.command()
def untag(
    note_id: Annotated[str, typer.Argument(help="Note identifier.")],
    name: Annotated[str, typer.Argument(help="Tag to remove (without the leading #).")],
    db_path: DbPathOption = DEFAULT_DB_PATH,
) -> None:
    """Remove a tag from a note (rewrites the note text without the tag marker)."""
    db = _open_db(db_path)
    try:
        note = _require_note(db, note_id)
        if not _has_tag(note, name) or note.text is None:
            console.print(
                f"[red]Error:[/red] note {note.id} has no tag {name!r} (tags: {', '.join(note.tags) or 'none'})"
            )
            raise typer.Exit(1)
        # Strip both marker forms; don't touch longer tags sharing the prefix
        # (removing "work" must leave "#work/ideas" and "#workout" alone).
        escaped = re.escape(name)
        new_text = re.sub(rf"[ \t]?#{escaped}#", "", note.text, flags=re.IGNORECASE)
        new_text = re.sub(rf"[ \t]?#{escaped}(?![\w/-])", "", new_text, flags=re.IGNORECASE)
        if new_text == note.text:
            console.print(f"[red]Error:[/red] could not locate the #{name} marker in the note text")
            raise typer.Exit(1)
        new_text = new_text.rstrip("\n") + "\n"
        actions.add_text(note.id, new_text, mode="replace_all")
        _verify(
            lambda: (n := db.get_note(note.id)) is not None and not _has_tag(n, name),
            f"Removed tag {name!r} from note {note.id}",
            "tag was not removed; is Bear able to run?",
        )
    finally:
        db.close()


@note_app.command("open")
def open_note(
    note_id: Annotated[str, typer.Argument(help="Note identifier.")],
    new_window: Annotated[bool, typer.Option("--new-window", "-w", help="Open in a separate window.")] = False,
    db_path: DbPathOption = DEFAULT_DB_PATH,
) -> None:
    """Open a note in the Bear app."""
    db = _open_db(db_path)
    try:
        note = _require_note(db, note_id)
    finally:
        db.close()
    actions.open_note(note.id, new_window=new_window)
    console.print(f"Opened note {note.id} in Bear")


MAX_ATTACH_BYTES = 500_000  # the file travels base64-encoded inside a URL; macOS caps arg size at ~1 MB


@note_app.command()
def attach(
    note_id: Annotated[str, typer.Argument(help="Note identifier.")],
    file: Annotated[Path, typer.Argument(help="File to attach (appended at the end of the note).")],
    db_path: DbPathOption = DEFAULT_DB_PATH,
) -> None:
    """Attach a file to a note."""
    if not file.is_file():
        console.print(f"[red]Error:[/red] {file} is not a file")
        raise typer.Exit(1)
    data = file.read_bytes()
    if len(data) > MAX_ATTACH_BYTES:
        console.print(
            f"[red]Error:[/red] {file.name} is {len(data)} bytes; attachments are limited to "
            f"{MAX_ATTACH_BYTES} bytes (the file is passed base64-encoded through a URL)"
        )
        raise typer.Exit(1)
    db = _open_db(db_path)
    try:
        note = _require_note(db, note_id)
        before = len(note.attachments)
        actions.add_file(note.id, file.name, base64.b64encode(data).decode())
        _verify(
            lambda: (n := db.get_note(note.id)) is not None and len(n.attachments) > before,
            f"Attached {file.name} to note {note.id}",
            "attachment did not appear; is Bear able to run?",
        )
    finally:
        db.close()


@note_app.command()
def rename(
    note_id: Annotated[str, typer.Argument(help="Note identifier.")],
    new_title: Annotated[str, typer.Argument(help="New title for the note.")],
    db_path: DbPathOption = DEFAULT_DB_PATH,
) -> None:
    """Change a note's title (first line), keeping the body."""
    db = _open_db(db_path)
    try:
        note = _require_note(db, note_id)
        if note.text is None:
            console.print(f"[red]Error:[/red] note {note.id} is encrypted; cannot rename")
            raise typer.Exit(1)
        head, sep, body = note.text.partition("\n")
        if head.startswith("# "):
            new_text = f"# {new_title}{sep}{body}"
        else:
            new_text = f"# {new_title}\n{note.text}"
        actions.add_text(note.id, new_text, mode="replace_all")
        _verify(
            lambda: (n := db.get_note(note.id)) is not None and n.title == new_title,
            f"Renamed note {note.id} to {new_title!r}",
            "title did not change; is Bear able to run?",
        )
    finally:
        db.close()


@note_app.command()
def replace(
    note_id: Annotated[str, typer.Argument(help="Note identifier.")],
    text: Annotated[str | None, typer.Option("--text", help="New body (reads stdin if piped).")] = None,
    db_path: DbPathOption = DEFAULT_DB_PATH,
) -> None:
    """Replace a note's body with new text, keeping the title. Destructive."""
    body = _text_or_stdin(text)
    if body is None:
        console.print("[red]Error:[/red] provide --text or pipe content on stdin")
        raise typer.Exit(2)
    db = _open_db(db_path)
    try:
        before = _require_note(db, note_id)
        actions.add_text(before.id, body, mode="replace")
        _verify(
            lambda: (
                (n := db.get_note(before.id)) is not None
                and n.modified is not None
                and (before.modified is None or n.modified > before.modified)
            ),
            f"Replaced body of note {before.id}",
            "note was not modified; is Bear able to run?",
        )
    finally:
        db.close()


@tag_app.command("rename")
def rename_tag(
    name: Annotated[str, typer.Argument(help="Existing tag name.")],
    new_name: Annotated[str, typer.Argument(help="New tag name.")],
    db_path: DbPathOption = DEFAULT_DB_PATH,
) -> None:
    """Rename a tag across all notes."""
    db = _open_db(db_path)
    try:
        existing = {t.lower() for t, _ in db.list_tags()}
        if name.lower() not in existing:
            console.print(f"[red]Error:[/red] no tag named {name!r}")
            raise typer.Exit(1)
        actions.rename_tag(name, new_name)
        _verify(
            lambda: new_name.lower() in {t.lower() for t, _ in db.list_tags()},
            f"Renamed tag {name!r} to {new_name!r}",
            "tag was not renamed; is Bear able to run?",
        )
    finally:
        db.close()


@tag_app.command("delete")
def delete_tag(
    name: Annotated[str, typer.Argument(help="Tag to delete from all notes.")],
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip the confirmation prompt.")] = False,
    db_path: DbPathOption = DEFAULT_DB_PATH,
) -> None:
    """Delete a tag from every note that has it."""
    db = _open_db(db_path)
    try:
        counts = {t.lower(): c for t, c in db.list_tags(include_empty=True)}
        if name.lower() not in counts:
            console.print(f"[red]Error:[/red] no tag named {name!r}")
            raise typer.Exit(1)
        if not yes:
            typer.confirm(f"Remove tag '{name}' from {counts[name.lower()]} note(s)?", abort=True)
        actions.delete_tag(name)
        # Bear keeps an empty tag row behind, so verify the count reaches zero.
        _verify(
            lambda: dict((t.lower(), c) for t, c in db.list_tags(include_empty=True)).get(name.lower(), 0) == 0,
            f"Deleted tag {name!r}",
            "tag was not deleted; is Bear able to run?",
        )
    finally:
        db.close()


@note_app.command()
def search(
    query: Annotated[str, typer.Argument(help="Search terms, matched against titles, tags, and text.")],
    fuzzy: Annotated[bool, typer.Option("--fuzzy", help="Typo-tolerant matching, ranked by score.")] = False,
    limit: Annotated[int, typer.Option("--limit", "-n", help="Maximum number of results.")] = 10,
    min_score: Annotated[float, typer.Option("--min-score", help="Minimum match score, 0-100 (fuzzy only).")] = 60.0,
    tag_filter: Annotated[str | None, typer.Option("--tag", "-t", help="Restrict to notes with this tag.")] = None,
    trashed: Annotated[bool, typer.Option("--trashed", help="Include trashed notes.")] = False,
    archived: Annotated[bool, typer.Option("--archived", help="Include archived notes.")] = False,
    fmt: Annotated[
        OutputFormat,
        typer.Option("--format", "-f", help="Output format: table, json, or text."),
    ] = OutputFormat.table,
    db_path: DbPathOption = DEFAULT_DB_PATH,
) -> None:
    """Search notes by title, tags, and content."""
    db = _open_db(db_path)
    try:
        notes = db.list_notes(
            limit=None,
            tag=tag_filter,
            include_trashed=trashed,
            include_archived=archived,
            with_text=True,
        )
    finally:
        db.close()

    if fuzzy:
        results = search_notes(notes, query, min_score=min_score)[:limit]
    else:
        results = naive_search(notes, query)[:limit]

    if fmt is OutputFormat.json:
        payload = [
            {**_note_to_dict(r.note), "snippet": r.snippet}
            | ({"score": round(r.score, 1)} if r.score is not None else {})
            for r in results
        ]
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return
    if fmt is OutputFormat.text:
        for r in results:
            score = f"\t{r.score:.0f}" if r.score is not None else ""
            print(f"{r.note.id}{score}\t{r.note.title}")
        return

    if not results:
        console.print("No matches.")
        return

    table = Table(box=box.ROUNDED, header_style="bold")
    if fuzzy:
        table.add_column("Score", justify="right")
    table.add_column("ID", style="dim", no_wrap=True)
    table.add_column("Title", overflow="ellipsis", max_width=40)
    table.add_column("Match", style="green", overflow="ellipsis", max_width=50)
    if not fuzzy:
        table.add_column("Modified", no_wrap=True)
    for r in results:
        row = [r.note.id, r.note.title, r.snippet]
        if fuzzy:
            row.insert(0, f"{r.score:.0f}" if r.score is not None else "")
        else:
            row.append(r.note.modified.strftime("%Y-%m-%d %H:%M") if r.note.modified else "")
        table.add_row(*row)
    console.print(table)


# Top-level aliases for the most-used commands, shown in their own help panel.
def _alias(name: str, target: str, func: Callable) -> None:
    summary = (func.__doc__ or "").strip().splitlines()[0]
    app.command(name, help=f"{summary} (alias for `bearcli {target}`)", rich_help_panel="Shortcuts")(func)


_alias("list", "note list", list_notes)
_alias("search", "note search", search)
_alias("get", "note get", get)
_alias("open", "note open", open_note)
_alias("create", "note create", create)
