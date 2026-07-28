"""The Bear facade: one object for reading and (verified) writing.

The recommended entry point for library users. Reads go straight to the
read-only database; writes go through Bear's x-callback API and are
verified against the database before returning (raising `BearWriteError`
if Bear never applies the change). The raw layers remain available as
`bear.db`, `bearkit.ops`, and `bearkit.actions`.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import TracebackType

from bearkit import actions, ops
from bearkit.db import DEFAULT_DB_PATH, BearDB, Note, NoteFilter
from bearkit.ops import TextMode
from bearkit.search import SearchResult, naive_search, search_notes
from bearkit.secrets import ScanReport, scan_notes


class Bear:
    """A Bear library: read notes, and write them through the Bear app."""

    def __init__(self, path: Path = DEFAULT_DB_PATH):
        self.db = BearDB(path)

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> Bear:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.close()

    # ── reading ──────────────────────────────────────────────────────────

    def list_notes(
        self,
        limit: int | None = None,
        tag: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        modified_after: datetime | None = None,
        modified_before: datetime | None = None,
        only: NoteFilter | str | None = None,
        include_trashed: bool = False,
        include_archived: bool = False,
    ) -> list[Note]:
        """Notes, most recently modified first (see BearDB.list_notes)."""
        return self.db.list_notes(
            limit=limit,
            tag=tag,
            created_after=created_after,
            created_before=created_before,
            modified_after=modified_after,
            modified_before=modified_before,
            only=only,
            include_trashed=include_trashed,
            include_archived=include_archived,
        )

    def get_note(self, note_id: str) -> Note | None:
        """Fetch a note by id or unique 4+ char prefix; None when absent."""
        return self.db.get_note(note_id)

    def list_tags(self, include_empty: bool = False) -> list[tuple[str, int]]:
        """All tags with their note counts."""
        return self.db.list_tags(include_empty=include_empty)

    def attachment_stats(self) -> tuple[int, int]:
        """(count, total bytes) of attachments on non-trashed notes."""
        return self.db.attachment_stats()

    def search(
        self, query: str, fuzzy: bool = False, min_score: float = 60.0, tag: str | None = None
    ) -> list[SearchResult]:
        """Search titles, tags, and content; fuzzy is typo-tolerant and ranked."""
        notes = self.list_notes(limit=None, tag=tag)
        if fuzzy:
            return search_notes(notes, query, min_score=min_score)
        return naive_search(notes, query)

    def scan_secrets(self, notes: list[Note] | None = None) -> ScanReport:
        """Scan for secrets; defaults to every note, archived included."""
        return scan_notes(notes if notes is not None else self.list_notes(limit=None, include_archived=True))

    # ── verified writing ─────────────────────────────────────────────────

    def create_note(self, title: str, text: str | None = None, tags: list[str] | None = None) -> Note:
        """Create a note and return it once it appears in the database."""
        return ops.create_note(self.db, title, text, tags)

    def add_text(self, note: Note, text: str, mode: TextMode | str = TextMode.APPEND) -> Note:
        """Append/prepend/replace note text."""
        return ops.add_text(self.db, note, text, mode)

    def rename(self, note: Note, new_title: str) -> Note:
        """Replace the heading line, keeping the body."""
        return ops.rename(self.db, note, new_title)

    def add_tag(self, note: Note, name: str) -> Note:
        """Add an inline tag marker to the note."""
        return ops.add_tag(self.db, note, name)

    def remove_tag(self, note: Note, name: str) -> Note:
        """Remove the tag's inline marker; raises TagMarkerNotFound if absent."""
        return ops.remove_tag(self.db, note, name)

    def attach_file(self, note: Note, filename: str, file_b64: str) -> Note:
        """Attach a base64-encoded file (keep it under ~500 KB)."""
        return ops.attach_file(self.db, note, filename, file_b64)

    def trash(self, note: Note) -> Note:
        """Move the note to Bear's trash (one-way: no untrash API)."""
        return ops.trash(self.db, note)

    def archive(self, note: Note) -> Note:
        """Archive the note (one-way: no unarchive API)."""
        return ops.archive(self.db, note)

    def rename_tag(self, name: str, new_name: str) -> None:
        """Rename a tag across all notes."""
        ops.rename_tag(self.db, name, new_name)

    def delete_tag(self, name: str) -> None:
        """Delete a tag from every note that has it."""
        ops.delete_tag(self.db, name)

    # ── the Bear app ─────────────────────────────────────────────────────

    def open(self, note: Note, new_window: bool = False) -> None:
        """Bring the note up in the Bear app."""
        actions.open_note(note.id, new_window=new_window)
