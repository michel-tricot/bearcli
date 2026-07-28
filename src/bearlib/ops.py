"""Verified write operations.

Each function fires a Bear x-callback action, confirms the outcome by
re-reading the database, and returns the fresh note. If Bear never
observably applies the change within `VERIFY_TIMEOUT` seconds (typically:
Bear cannot run), `BearWriteError` is raised.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from bearlib import actions
from bearlib.db import BearDB, Note
from bearlib.markdown import remove_tag_marker, tag_marker

VERIFY_TIMEOUT = 6.0
"""Seconds to wait for Bear to apply a write before raising BearWriteError."""


class TextMode(StrEnum):
    """Where `add_text` puts the text (mirrors Bear's add-text modes)."""

    APPEND = "append"
    PREPEND = "prepend"
    REPLACE = "replace"  # replaces the body, keeps the title
    REPLACE_ALL = "replace_all"  # replaces everything including the title


class BearWriteError(RuntimeError):
    """Bear did not observably apply the write (is Bear able to run?)."""


class TagMarkerNotFound(LookupError):
    """The note text contains no inline marker for the tag being removed."""


def has_tag(note: Note, name: str) -> bool:
    return name.lower() in (t.lower() for t in note.tags)


def _confirmed(db: BearDB, note_id: str, operation: str, changed: Callable[[Note], bool]) -> Note:
    def check() -> bool:
        fresh = db.get_note(note_id)
        return fresh is not None and changed(fresh)

    if actions.wait_for(check, timeout=VERIFY_TIMEOUT):
        fresh = db.get_note(note_id)
        if fresh is not None:
            return fresh
    raise BearWriteError(f"{operation} was not applied to note {note_id}")


def _modified_after(before: Note) -> Callable[[Note], bool]:
    return lambda n: n.modified is not None and (before.modified is None or n.modified > before.modified)


def create_note(db: BearDB, title: str, text: str | None, tags: list[str] | None = None) -> Note:
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

    if actions.wait_for(lambda: find() is not None, timeout=VERIFY_TIMEOUT):
        created = find()
        if created is not None:
            return created
    raise BearWriteError(f"created note {title!r} did not appear in the database")


def add_text(db: BearDB, note: Note, text: str, mode: TextMode | str = TextMode.APPEND) -> Note:
    """Append/prepend/replace note text; verified by the modification date bump."""
    actions.add_text(note.id, text, mode=TextMode(mode).value)
    return _confirmed(db, note.id, "text change", _modified_after(note))


def rename(db: BearDB, note: Note, new_title: str) -> Note:
    """Replace the heading line, keeping the body."""
    head, sep, body = (note.text or "").partition("\n")
    if head.startswith("# "):
        new_text = f"# {new_title}{sep}{body}"
    else:
        new_text = f"# {new_title}\n{note.text or ''}"
    actions.add_text(note.id, new_text, mode=TextMode.REPLACE_ALL.value)
    return _confirmed(db, note.id, "rename", lambda n: n.title == new_title)


def add_tag(db: BearDB, note: Note, name: str) -> Note:
    actions.add_text(note.id, tag_marker(name), mode=TextMode.APPEND.value)
    return _confirmed(db, note.id, "tag", lambda n: has_tag(n, name))


def remove_tag(db: BearDB, note: Note, name: str) -> Note:
    """Rewrite the note without the tag marker.

    Raises TagMarkerNotFound when the text has no marker for the tag.
    """
    new_text = remove_tag_marker(note.text or "", name)
    if new_text is None:
        raise TagMarkerNotFound(f"no #{name} marker in the note text")
    actions.add_text(note.id, new_text, mode=TextMode.REPLACE_ALL.value)
    return _confirmed(db, note.id, "untag", lambda n: not has_tag(n, name))


def attach_file(db: BearDB, note: Note, filename: str, file_b64: str) -> Note:
    before = len(note.attachments)
    actions.add_file(note.id, filename, file_b64)
    return _confirmed(db, note.id, "attach", lambda n: len(n.attachments) > before)


def trash(db: BearDB, note: Note) -> Note:
    actions.trash_note(note.id)
    return _confirmed(db, note.id, "trash", lambda n: n.trashed)


def archive(db: BearDB, note: Note) -> Note:
    actions.archive_note(note.id)
    return _confirmed(db, note.id, "archive", lambda n: n.archived)
