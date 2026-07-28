"""Typer CLI for reading notes from the Bear note app."""

from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Annotated, Optional
from urllib.parse import quote

import typer
from rich import box
from rich.console import Console
from rich.markup import escape as rich_escape
from rich.table import Table

from bearcli.db import DEFAULT_DB_PATH, BearDB, Note
from bearcli.export import export_notes

app = typer.Typer(help="Read notes from the Bear note app.", no_args_is_help=True)
console = Console()


class OutputFormat(str, Enum):
    table = "table"
    json = "json"
    text = "text"


class OnlyFilter(str, Enum):
    pinned = "pinned"
    encrypted = "encrypted"
    trashed = "trashed"
    archived = "archived"


def _note_to_dict(note: Note, with_text: bool = False) -> dict:
    data = {
        "id": note.id,
        "title": note.title,
        "tags": note.tags,
        "created": note.created.isoformat() if note.created else None,
        "modified": note.modified.isoformat() if note.modified else None,
        "pinned": note.pinned,
        "encrypted": note.encrypted,
        "archived": note.archived,
        "trashed": note.trashed,
    }
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
    """Rewrite bare attachment filenames in markdown links to absolute paths.

    Bear percent-encodes filenames in the note text (e.g. spaces as %20), so match
    both the raw and encoded forms; emit encoded paths to keep the links valid.
    """
    text = note.text or ""
    for att in note.attachments:
        target = quote(str(att.path))
        for ref in {att.filename, quote(att.filename)}:
            text = text.replace(f"]({ref})", f"]({target})")
    return text

DbPathOption = Annotated[
    Path,
    typer.Option("--db", envvar="BEAR_DB_PATH", help="Path to the Bear SQLite database."),
]


def _open_db(path: Path) -> BearDB:
    try:
        return BearDB(path)
    except FileNotFoundError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)


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
        raise typer.Exit(2)


@app.command("list")
def list_notes(
    limit: Annotated[int, typer.Option("--limit", "-n", help="Maximum number of notes.")] = 20,
    tag: Annotated[
        Optional[str],
        typer.Option("--tag", "-t", help="Only notes with this tag (includes nested sub-tags)."),
    ] = None,
    modified_after: Annotated[
        Optional[str], typer.Option("--modified-after", help="Modified on or after this date.")
    ] = None,
    modified_before: Annotated[
        Optional[str], typer.Option("--modified-before", help="Modified before this date.")
    ] = None,
    created_after: Annotated[
        Optional[str], typer.Option("--created-after", help="Created on or after this date.")
    ] = None,
    created_before: Annotated[
        Optional[str], typer.Option("--created-before", help="Created before this date.")
    ] = None,
    search: Annotated[
        Optional[str], typer.Option("--search", "-s", help="Filter by text in title or body.")
    ] = None,
    only: Annotated[
        Optional[OnlyFilter],
        typer.Option(
            "--only",
            help="Only notes with this status: pinned, encrypted, trashed, or archived.",
        ),
    ] = None,
    all_notes: Annotated[
        bool, typer.Option("--all", "-a", help="No limit (overrides --limit).")
    ] = False,
    trashed: Annotated[bool, typer.Option("--trashed", help="Include trashed notes.")] = False,
    archived: Annotated[bool, typer.Option("--archived", help="Include archived notes.")] = False,
    ids_only: Annotated[
        bool, typer.Option("--ids", help="Print only note identifiers, one per line.")
    ] = False,
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
            search=search,
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
            print(
                f"{note.id}\t{modified}\t{','.join(note.tags)}\t{_note_status(note)}\t{note.title}"
            )
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


@app.command()
def get(
    note_id: Annotated[str, typer.Argument(help="Note identifier (UUID from `bearcli list`).")],
    meta: Annotated[
        bool, typer.Option("--meta", help="Print metadata frontmatter before the content.")
    ] = False,
    resolve_attachments: Annotated[
        bool,
        typer.Option(
            "--resolve-attachments",
            "-r",
            help="Rewrite attachment references in the content to absolute file paths.",
        ),
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
        note = db.get_note(note_id)
    finally:
        db.close()

    if note is None:
        console.print(f"[red]Error:[/red] no note with id {note_id!r}")
        raise typer.Exit(1)
    if note.encrypted or note.text is None:
        console.print(f"[red]Error:[/red] note {note.id} is encrypted; its content is unavailable")
        raise typer.Exit(1)

    text = _resolve_attachments(note) if resolve_attachments else note.text

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
    db_path: DbPathOption = DEFAULT_DB_PATH,
) -> None:
    """Export all notes as markdown files with frontmatter and attachments."""
    db = _open_db(db_path)
    try:
        with console.status("Exporting…", spinner="dots") as status:
            result = export_notes(
                db, dest, sync=sync, progress=lambda msg: status.update(rich_escape(msg))
            )
    finally:
        db.close()

    parts = [f"{result.written} written"]
    if sync:
        parts.append(f"{result.unchanged} unchanged")
    if result.removed:
        parts.append(f"{result.removed} removed")
    if result.skipped_encrypted:
        parts.append(f"{result.skipped_encrypted} encrypted skipped")
    if result.index_updated:
        parts.append("index updated")
    console.print(f"Exported to {dest}: " + ", ".join(parts))
    if result.index_skipped:
        console.print(
            "[yellow]Warning:[/yellow] README.md exists but was not generated by bearcli; "
            "left untouched"
        )
