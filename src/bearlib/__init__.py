"""bearlib: the fundamentals for interacting with the Bear notes app.

- `db` / `BearDB`: read Bear's SQLite database (strictly read-only; Bear
  does not need to be running).
- `actions`: Bear's x-callback-url write API (fire-and-forget URLs).
- `ops`: verified write operations - fire an action, confirm it via the
  database, return the fresh note.
- `search`: naive and fuzzy search over notes.
- `secrets`: offline secret detection and redaction for note text.
- `markdown`: Bear markdown conventions (attachment links, tag markers).

Nothing in this package depends on a UI; bearcli's CLI and TUI are built
on top of it.
"""

from bearlib.db import (
    DEFAULT_DB_PATH,
    AmbiguousNoteId,
    Attachment,
    BearDB,
    Note,
    note_metadata,
    note_status,
)

__all__ = [
    "DEFAULT_DB_PATH",
    "AmbiguousNoteId",
    "Attachment",
    "BearDB",
    "Note",
    "note_metadata",
    "note_status",
]
