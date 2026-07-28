"""Tag management commands (the `tag` group)."""

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
    console,
    tag_app,
)
from bearkit import BearWriteError
from bearkit.db import DEFAULT_DB_PATH


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
    bear = _open_bear(db_path)
    try:
        all_tags = bear.list_tags(include_empty=include_empty)
    finally:
        bear.close()

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


@tag_app.command("rename")
def rename_tag(
    name: Annotated[str, typer.Argument(help="Existing tag name.")],
    new_name: Annotated[str, typer.Argument(help="New tag name.")],
    db_path: DbPathOption = DEFAULT_DB_PATH,
) -> None:
    """Rename a tag across all notes."""
    bear = _open_bear(db_path)
    try:
        existing = {t.lower() for t, _ in bear.list_tags()}
        if name.lower() not in existing:
            console.print(f"[red]Error:[/red] no tag named {name!r}")
            raise typer.Exit(1)
        try:
            bear.rename_tag(name, new_name)
        except BearWriteError:
            console.print("[red]Error:[/red] tag was not renamed; is Bear able to run?")
            raise typer.Exit(1) from None
        console.print(f"Renamed tag {name!r} to {new_name!r}")
    finally:
        bear.close()


@tag_app.command("delete")
def delete_tag(
    name: Annotated[str, typer.Argument(help="Tag to delete from all notes.")],
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip the confirmation prompt.")] = False,
    db_path: DbPathOption = DEFAULT_DB_PATH,
) -> None:
    """Delete a tag from every note that has it."""
    bear = _open_bear(db_path)
    try:
        counts = {t.lower(): c for t, c in bear.list_tags(include_empty=True)}
        if name.lower() not in counts:
            console.print(f"[red]Error:[/red] no tag named {name!r}")
            raise typer.Exit(1)
        if not yes:
            typer.confirm(f"Remove tag '{name}' from {counts[name.lower()]} note(s)?", abort=True)
        try:
            bear.delete_tag(name)
        except BearWriteError:
            console.print("[red]Error:[/red] tag was not deleted; is Bear able to run?")
            raise typer.Exit(1) from None
        console.print(f"Deleted tag {name!r}")
    finally:
        bear.close()
