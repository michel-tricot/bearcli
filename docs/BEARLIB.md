# `bearlib` API reference

The fundamentals for interacting with the Bear notes app from Python. macOS
only; everything runs offline. Install: `pip install bearcli` (both packages
ship together).

```python
from bearlib import BearDB, NoteFilter, ops

with BearDB() as db:                       # read-only
    for note in db.list_notes(tag="work"):
        print(note.title, note.tags)
```

## Reading - `bearlib.db`

- `BearDB(path=DEFAULT_DB_PATH)` - opens Bear's SQLite database read-only.
  Context manager; `close()` when done otherwise.
- `db.list_notes(limit=None, tag=None, created_after/before=None,
  modified_after/before=None, only=None, include_trashed=False,
  include_archived=False) -> list[Note]` - newest first. `only` takes a
  `NoteFilter` (`PINNED`, `ENCRYPTED`, `TRASHED`, `ARCHIVED`) or its string
  value. Text is always loaded.
- `db.get_note(id) -> Note | None` - accepts a unique id prefix (4+ chars);
  raises `AmbiguousNoteId` (with `.matches`) if the prefix is ambiguous.
  Loads attachments.
- `db.list_tags(include_empty=False) -> list[(name, note_count)]`
- `db.attachment_stats() -> (count, total_bytes)`
- `Note` - id, title, text (None **iff encrypted**), created/modified
  (tz-aware), pinned/encrypted/archived/trashed, tags, attachments.
- `note_metadata(note) -> dict`, `note_status(note) -> str` - canonical
  serializations.

## Writing - `bearlib.ops` (recommended) and `bearlib.actions`

`ops` functions fire a Bear x-callback action, verify the outcome by
re-reading the database, and return the fresh `Note`. If Bear doesn't
observably apply the change within `ops.VERIFY_TIMEOUT` seconds they raise
`BearWriteError`. The Bear app is launched if needed; the database itself is
never written.

- `ops.create_note(db, title, text, tags=None) -> Note`
- `ops.add_text(db, note, text, mode=TextMode.APPEND) -> Note` - `TextMode`:
  `APPEND`, `PREPEND`, `REPLACE` (body only), `REPLACE_ALL`.
- `ops.rename(db, note, new_title) -> Note`
- `ops.add_tag(db, note, name)` / `ops.remove_tag(db, note, name)` - remove
  raises `TagMarkerNotFound` when the text has no marker for the tag.
- `ops.attach_file(db, note, filename, file_b64) -> Note`
- `ops.trash(db, note)` / `ops.archive(db, note)` - one-way; Bear has no
  untrash/unarchive API.

`actions` is the raw fire-and-forget layer (`open_note`, `create`,
`add_text`, `add_file`, `trash_note`, `archive_note`, `rename_tag`,
`delete_tag`) - use it when you don't need verification.

## Search - `bearlib.search`

- `naive_search(notes, query) -> list[SearchResult]` - case-insensitive
  substring over titles, tags, and text; input order preserved; `score` is
  None.
- `search_notes(notes, query, min_score=60.0)` - typo-tolerant, ranked
  (rapidfuzz); results carry `score` and a `snippet`.

## Secrets - `bearlib.secrets`

- `scan_notes(notes) -> list[SecretFinding]` - offline detection (formats +
  entropy + labeled credentials). `SecretFinding.secret` holds the raw value
  for redaction purposes - never print it; `excerpt` is the safe display
  form.
- `redaction_map(findings) -> {note_id: {secret: rule}}`
- `redact_text(text, secrets) -> str` - replaces each value with
  `[redacted: <rule>]`.

## Markdown - `bearlib.markdown`

- `rewrite_attachment_refs(note, target_for)` - rewrite bare attachment
  links (handles Bear's percent-encoding).
- `tag_marker(name)` / `remove_tag_marker(text, name)`.
