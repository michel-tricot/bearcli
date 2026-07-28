"""Shared Typer apps, output types, and helpers for the CLI commands."""

from __future__ import annotations

import sys
from collections.abc import Callable
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from bearcli import actions
from bearcli.db import AmbiguousNoteId, BearDB, Note, note_metadata

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
