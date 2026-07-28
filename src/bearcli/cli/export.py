"""The export command."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich import box
from rich.markup import escape as rich_escape
from rich.table import Table

from bearcli.cli.common import (
    DbPathOption,
    _open_db,
    app,
    console,
)
from bearcli.export import export_notes
from bearcli.gitsync import GitError, export_and_push
from bearlib.db import DEFAULT_DB_PATH
from bearlib.secrets import SecretFinding, redaction_map, scan_notes


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
                candidates = db.list_notes(limit=None, include_archived=True)
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
