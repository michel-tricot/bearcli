"""Write flows shared by the CLI and TUI: fire a Bear action, verify via the database."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from bearcli import actions
from bearcli.db import BearDB, Note


def create_and_find(db: BearDB, title: str, text: str | None, tags: list[str] | None = None) -> Note | None:
    """Create a note through Bear and return it once it appears in the database."""
    started = datetime.now(UTC)
    actions.create_note(title, text=text, tags=tags)

    def find() -> Note | None:
        return next(
            (
                n
                for n in db.list_notes(limit=10)
                if n.title == title and n.created and n.created >= started - timedelta(seconds=5)
            ),
            None,
        )

    if actions.wait_for(lambda: find() is not None):
        return find()
    return None
