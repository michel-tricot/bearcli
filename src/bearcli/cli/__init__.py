"""Typer CLI for reading notes from the Bear note app."""

from collections.abc import Callable

from bearcli.cli.common import app
from bearcli.cli.notes import create, get, list_notes, open_note, search


def _alias(name: str, target: str, func: Callable) -> None:
    summary = (func.__doc__ or "").strip().splitlines()[0]
    app.command(name, help=f"{summary} (alias for `bearcli {target}`)", rich_help_panel="Shortcuts")(func)


_alias("list", "note list", list_notes)

_alias("search", "note search", search)

_alias("get", "note get", get)

_alias("open", "note open", open_note)

_alias("create", "note create", create)

# Imported after the aliases: help panels render in registration order, and
# Shortcuts should lead the top-level help.
from bearcli.cli import export, misc, skills, tags  # noqa: E402, F401  # command registration

__all__ = ["app"]
