"""bearkit: the fundamentals for interacting with the Bear notes app.

- `Bear`: the facade and recommended entry point - read notes, write them
  through the Bear app (verified), all from one object.
- `db` / `BearDB`: the raw read-only database layer (strictly read-only).
- `actions`: Bear's x-callback-url write API (fire-and-forget URLs).
- `ops`: verified write operations - fire an action, confirm it via the
  database, return the fresh note, or raise `BearWriteError`.
- `search`: naive and fuzzy search over notes.
- `secrets`: offline secret detection and redaction for note text.
- `markdown`: Bear markdown conventions (attachment links, tag markers).

Nothing in this package depends on a UI; bearcli's CLI and TUI are built
on top of it. macOS only (Bear is a macOS/iOS app).
"""

from bearkit import actions, db, markdown, ops, search, secrets
from bearkit.bear import Bear
from bearkit.db import (
    DEFAULT_DB_PATH,
    AmbiguousNoteId,
    Attachment,
    BearDB,
    Note,
    NoteFilter,
)
from bearkit.ops import BearWriteError, TagMarkerNotFound, TextMode
from bearkit.search import SearchResult, naive_search, search_notes
from bearkit.secrets import ScanReport, SecretFinding, scan_notes

__all__ = [
    "DEFAULT_DB_PATH",
    "AmbiguousNoteId",
    "Attachment",
    "Bear",
    "BearDB",
    "BearWriteError",
    "Note",
    "NoteFilter",
    "ScanReport",
    "SearchResult",
    "SecretFinding",
    "TagMarkerNotFound",
    "TextMode",
    "actions",
    "db",
    "markdown",
    "naive_search",
    "ops",
    "scan_notes",
    "search",
    "search_notes",
    "secrets",
]
