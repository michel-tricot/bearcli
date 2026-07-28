"""Library-wide commands: stats and the terminal UI."""

from __future__ import annotations

import json
from typing import Annotated

import typer
from rich import box
from rich.table import Table

from bearcli.cli.common import (
    DbPathOption,
    OutputFormat,
    _open_bear,
    app,
    console,
)
from bearkit.db import DEFAULT_DB_PATH


@app.command(rich_help_panel="Library")
def stats(
    fmt: Annotated[
        OutputFormat,
        typer.Option("--format", "-f", help="Output format: table or json."),
    ] = OutputFormat.table,
    db_path: DbPathOption = DEFAULT_DB_PATH,
) -> None:
    """Show statistics about the note library."""
    bear = _open_bear(db_path)
    try:
        notes = bear.list_notes(limit=None, include_trashed=True, include_archived=True)
        tag_counts = bear.list_tags()
        attachment_count, attachment_bytes = bear.attachment_stats()
    finally:
        bear.close()

    active = [n for n in notes if not n.trashed and not n.archived]
    by_year: dict[str, int] = {}
    for n in notes:
        if not n.trashed and n.created:
            year = str(n.created.year)
            by_year[year] = by_year.get(year, 0) + 1

    data = {
        "notes": len(notes),
        "active": len(active),
        "archived": sum(1 for n in notes if n.archived and not n.trashed),
        "trashed": sum(1 for n in notes if n.trashed),
        "pinned": sum(1 for n in notes if n.pinned and not n.trashed),
        "encrypted": sum(1 for n in notes if n.encrypted and not n.trashed),
        "words": sum(len((n.text or "").split()) for n in notes if not n.trashed),
        "tags": len(tag_counts),
        "attachments": attachment_count,
        "attachment_bytes": attachment_bytes,
        "notes_by_year": dict(sorted(by_year.items())),
        "top_tags": [{"tag": t, "notes": c} for t, c in sorted(tag_counts, key=lambda tc: -tc[1])[:10]],
    }

    if fmt is OutputFormat.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return

    table = Table(box=box.ROUNDED, show_header=False, width=44)
    table.add_column(style="bold")
    table.add_column(justify="right")
    table.add_row("Notes", str(data["notes"]))
    table.add_row("  active", str(data["active"]))
    table.add_row("  archived", str(data["archived"]))
    table.add_row("  trashed", str(data["trashed"]))
    table.add_row("  pinned", str(data["pinned"]))
    table.add_row("  encrypted", str(data["encrypted"]))
    table.add_row("Words", f"{data['words']:,}")
    table.add_row("Tags", str(data["tags"]))
    table.add_row("Attachments", f"{attachment_count} ({attachment_bytes / 1_000_000:.1f} MB)")
    console.print(table)

    if data["top_tags"]:
        tag_table = Table(box=box.ROUNDED, header_style="bold", width=44)
        tag_table.add_column("Top tags", style="cyan")
        tag_table.add_column("Notes", justify="right")
        for entry in data["top_tags"]:
            tag_table.add_row(str(entry["tag"]), str(entry["notes"]))
        console.print(tag_table)

    year_table = Table(box=box.ROUNDED, header_style="bold", width=44)
    year_table.add_column("Created", style="cyan")
    year_table.add_column("Notes", justify="right")
    for year, count in data["notes_by_year"].items():
        year_table.add_row(year, str(count))
    console.print(year_table)


@app.command(rich_help_panel="Library")
def ui(
    fuzzy: Annotated[bool, typer.Option("--fuzzy", help="Typo-tolerant ranked filtering.")] = False,
    tag_filter: Annotated[str | None, typer.Option("--tag", "-t", help="Restrict to notes with this tag.")] = None,
    db_path: DbPathOption = DEFAULT_DB_PATH,
) -> None:
    """Bear in the terminal: search, edit, create, tag, and organize notes."""
    from bearcli.tui import run_ui

    _open_bear(db_path).close()  # fail fast with a clear message if the db is missing
    run_ui(fuzzy=fuzzy, db_path=db_path, tag_filter=tag_filter)
