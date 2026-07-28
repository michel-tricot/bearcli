"""Verified write operations shared by the CLI and TUI.

Each function fires a Bear x-callback action, confirms the outcome by
re-reading the database, and returns the fresh note - or None when Bear
never applied the change (typically: Bear cannot run).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from bearlib import actions
from bearlib.db import BearDB, Note
from bearlib.markdown import remove_tag_marker, tag_marker


def has_tag(note: Note, name: str) -> bool:
    return name.lower() in (t.lower() for t in note.tags)


def _confirmed(db: BearDB, note_id: str, changed: Callable[[Note], bool]) -> Note | None:
    def check() -> bool:
        fresh = db.get_note(note_id)
        return fresh is not None and changed(fresh)

    return db.get_note(note_id) if actions.wait_for(check) else None


def _modified_after(before: Note) -> Callable[[Note], bool]:
    return lambda n: n.modified is not None and (before.modified is None or n.modified > before.modified)


def create_note(db: BearDB, title: str, text: str | None, tags: list[str] | None = None) -> Note | None:
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


def add_text(db: BearDB, note: Note, text: str, mode: str = "append") -> Note | None:
    """Append/prepend/replace note text; verified by the modification date bump."""
    actions.add_text(note.id, text, mode=mode)
    return _confirmed(db, note.id, _modified_after(note))


def rename(db: BearDB, note: Note, new_title: str) -> Note | None:
    """Replace the heading line, keeping the body."""
    head, sep, body = (note.text or "").partition("\n")
    if head.startswith("# "):
        new_text = f"# {new_title}{sep}{body}"
    else:
        new_text = f"# {new_title}\n{note.text or ''}"
    actions.add_text(note.id, new_text, mode="replace_all")
    return _confirmed(db, note.id, lambda n: n.title == new_title)


def add_tag(db: BearDB, note: Note, name: str) -> Note | None:
    actions.add_text(note.id, tag_marker(name), mode="append")
    return _confirmed(db, note.id, lambda n: has_tag(n, name))


def remove_tag(db: BearDB, note: Note, name: str) -> Note | None:
    """Rewrite the note without the tag marker; raises LookupError if none is present."""
    new_text = remove_tag_marker(note.text or "", name)
    if new_text is None:
        raise LookupError(f"no #{name} marker in the note text")
    actions.add_text(note.id, new_text, mode="replace_all")
    return _confirmed(db, note.id, lambda n: not has_tag(n, name))


def attach_file(db: BearDB, note: Note, filename: str, file_b64: str) -> Note | None:
    before = len(note.attachments)
    actions.add_file(note.id, filename, file_b64)
    return _confirmed(db, note.id, lambda n: len(n.attachments) > before)


def trash(db: BearDB, note: Note) -> Note | None:
    actions.trash_note(note.id)
    return _confirmed(db, note.id, lambda n: n.trashed)


def archive(db: BearDB, note: Note) -> Note | None:
    actions.archive_note(note.id)
    return _confirmed(db, note.id, lambda n: n.archived)
