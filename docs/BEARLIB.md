# `bearlib` API reference

The fundamentals for interacting with the Bear notes app from Python. macOS
only; everything runs offline. Install: `pip install bearcli` (both packages
ship together). The package is typed (`py.typed`).

Samples below assume:

```python
from bearlib import BearDB, NoteFilter, ops

db = BearDB()  # read-only
note = db.get_note("C44D09DC")
```

## Reading - `bearlib.db`

### `BearDB(path=DEFAULT_DB_PATH)`

Opens Bear's SQLite database read-only. Context manager, or call `close()`.

```python
from bearlib import BearDB

with BearDB() as db:
    print(len(db.list_notes()))
```

### `db.list_notes(...) -> list[Note]`

Notes, most recently modified first. Trashed/archived are excluded unless
included explicitly or selected via `only` (a `NoteFilter` or its string
value). Text is always loaded.

```python
recent = db.list_notes(limit=10)
work = db.list_notes(tag="work")  # includes nested tags like work/ideas
pinned = db.list_notes(only=NoteFilter.PINNED)
everything = db.list_notes(include_trashed=True, include_archived=True)

from datetime import datetime
this_month = db.list_notes(modified_after=datetime(2026, 7, 1))
```

### `db.get_note(note_id) -> Note | None`

Fetch by id; a unique prefix of 4+ characters works like a full id. Loads
attachments. Raises `AmbiguousNoteId` when the prefix matches several notes.

```python
from bearlib import AmbiguousNoteId

try:
    note = db.get_note("c44d09dc")  # case-insensitive prefix
except AmbiguousNoteId as exc:
    for full_id, title in exc.matches:
        print(full_id, title)
```

### `db.list_tags(include_empty=False) -> list[tuple[str, int]]`

All tags with their note counts. Bear keeps empty tag rows around; they are
hidden unless `include_empty=True`.

```python
for name, count in db.list_tags():
    print(f"{count:4}  {name}")
```

### `db.attachment_stats() -> tuple[int, int]`

Count and total bytes of attachments on non-trashed notes.

```python
count, total_bytes = db.attachment_stats()
print(f"{count} attachments, {total_bytes / 1e6:.1f} MB")
```

### `Note`, `note_metadata(note)`, `note_status(note)`

`Note` fields: `id`, `title`, `text` (None **iff encrypted**), `created` /
`modified` (timezone-aware), `pinned` / `encrypted` / `archived` / `trashed`,
`tags`, `attachments` (each with `filename`, `path`, `size`, `exists`).

```python
from bearlib import note_metadata, note_status

print(note_metadata(note))  # serializable dict: id, title, tags, ISO dates, flags
print(note_status(note))    # e.g. "pinned,archived" ("" when none)
```

## Writing - `bearlib.ops`

Each function fires a Bear x-callback action (launching the Bear app if
needed - the database itself is never written), verifies the outcome by
re-reading the database, and returns the fresh `Note`. If Bear doesn't
observably apply the change within `ops.VERIFY_TIMEOUT` seconds, it raises
`BearWriteError`.

### `ops.create_note(db, title, text, tags=None) -> Note`

```python
from bearlib import BearWriteError

try:
    created = ops.create_note(db, "Meeting notes", "agenda item one", tags=["work"])
    print(created.id)
except BearWriteError:
    print("Bear did not apply the change")
```

### `ops.add_text(db, note, text, mode=TextMode.APPEND) -> Note`

`TextMode`: `APPEND`, `PREPEND`, `REPLACE` (body only, keeps the title),
`REPLACE_ALL` (including the title). Strings are accepted and validated.

```python
from bearlib import TextMode

ops.add_text(db, note, "follow-up item")
ops.add_text(db, note, "new body", mode=TextMode.REPLACE)
```

### `ops.rename(db, note, new_title) -> Note`

Replaces the heading line, keeping the body.

```python
renamed = ops.rename(db, note, "Better title")
assert renamed.title == "Better title"
```

### `ops.add_tag(db, note, name)` / `ops.remove_tag(db, note, name)`

Tags are inline markers in the note text; `remove_tag` rewrites the text
without the marker and raises `TagMarkerNotFound` when none is present.

```python
from bearlib import TagMarkerNotFound

tagged = ops.add_tag(db, note, "work/ideas")
try:
    ops.remove_tag(db, tagged, "work/ideas")
except TagMarkerNotFound:
    print("note has no such tag")
```

### `ops.attach_file(db, note, filename, file_b64) -> Note`

The file travels base64-encoded inside a URL; keep it under ~500 KB.

```python
import base64
from pathlib import Path

payload = base64.b64encode(Path("chart.png").read_bytes()).decode()
ops.attach_file(db, note, "chart.png", payload)
```

### `ops.trash(db, note)` / `ops.archive(db, note)`

One-way: Bear has no untrash/unarchive API (restore is UI-only).

```python
ops.archive(db, note)
```

### `ops.has_tag(note, name) -> bool`

```python
if not ops.has_tag(note, "inbox"):
    ops.add_tag(db, note, "inbox")
```

## Raw actions - `bearlib.actions`

The fire-and-forget x-callback layer: no database, no verification. Prefer
`ops` unless you explicitly don't want to wait.

```python
from bearlib import actions

actions.open_note(note.id)                    # bring the note up in Bear
actions.create_note("Quick capture", text="from a script")
actions.add_text(note.id, "appended", mode="append")
actions.trash_note(note.id)
actions.archive_note(note.id)
actions.rename_tag("old-name", "new-name")    # across all notes
actions.delete_tag("obsolete")                # across all notes
```

`actions.wait_for(predicate, timeout=6.0, interval=0.3) -> bool` polls until
the predicate is true - useful for hand-rolled verification:

```python
actions.trash_note(note.id)
applied = actions.wait_for(lambda: (n := db.get_note(note.id)) is not None and n.trashed)
```

## Search - `bearlib.search`

### `naive_search(notes, query) -> list[SearchResult]`

Case-insensitive substring over titles, tags, and text; preserves input
order; `score` is None.

```python
from bearlib import naive_search

notes = db.list_notes(limit=None)
for result in naive_search(notes, "invoice"):
    print(result.note.title, result.snippet)
```

### `search_notes(notes, query, min_score=60.0) -> list[SearchResult]`

Typo-tolerant and ranked (rapidfuzz); results carry a `score` and a
`snippet` locating the match.

```python
from bearlib import search_notes

for result in search_notes(notes, "quarterly planing")[:5]:
    print(f"{result.score:5.1f}  {result.note.title}  {result.snippet}")
```

## Secrets - `bearlib.secrets`

### `scan_notes(notes) -> list[SecretFinding]`

Offline detection: known token formats, entropy analysis, and labeled
credentials. `SecretFinding.excerpt` is safe to display;
`SecretFinding.secret` holds the raw value for redaction - never print it.

```python
from bearlib import scan_notes

findings = scan_notes(notes)
for f in findings:
    print(f.note_title, f.rule, f.line, f.excerpt)
```

### `redaction_map(findings)` and `redact_text(text, secrets)`

```python
from bearlib import redact_text, redaction_map

by_note = redaction_map(findings)  # {note_id: {secret_value: rule}}
for n in notes:
    if n.id in by_note and n.text is not None:
        safe = redact_text(n.text, by_note[n.id])  # values become [redacted: <rule>]
        print(safe)
```

## Markdown - `bearlib.markdown`

### `rewrite_attachment_refs(note, target_for) -> str`

Rewrites bare attachment links to per-attachment targets, handling Bear's
percent-encoding. Regular URLs are never touched.

```python
from bearlib.markdown import rewrite_attachment_refs

absolute = rewrite_attachment_refs(note, lambda att: str(att.path))
relative = rewrite_attachment_refs(note, lambda att: f"files/{att.filename}")
```

### `tag_marker(name)` / `remove_tag_marker(text, name)`

The inline marker Bear uses for a tag, and text with that marker stripped
(None when no marker matched; longer tags sharing the prefix are untouched).

```python
from bearlib.markdown import remove_tag_marker, tag_marker

assert tag_marker("work") == "#work"
assert tag_marker("two words") == "#two words#"
stripped = remove_tag_marker("body #work\n", "work")   # "body\n"
assert remove_tag_marker("plain text", "work") is None
```
