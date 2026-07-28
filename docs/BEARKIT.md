# `bearkit` API reference

The fundamentals for interacting with the Bear notes app from Python. macOS
only; everything runs offline. Install: `pip install bearkit` (just the
library - two dependencies, no CLI or TUI). The package is typed
(`py.typed`). Every sample below is self-contained.

`Bear` is the interface: one object for reading and verified writing. The
raw layers stay available underneath (`bear.db`, `bearkit.ops`,
`bearkit.actions`) but most code should never need them.

## `Bear`

Reads your notes directly; writes go through the Bear app (launching it if
needed) and are verified before returning. Context manager, or call
`close()`.

```python
from bearkit import Bear

with Bear() as bear:
    for note in bear.list_notes(tag="work", limit=10):
        print(note.title)
```

### Reading

#### `bear.list_notes(...) -> list[Note]`

Notes, most recently modified first. Trashed/archived are excluded unless
included explicitly or selected via `only` (a `NoteFilter` or its string
value). Text is always loaded.

```python
from datetime import datetime

from bearkit import Bear, NoteFilter

bear = Bear()
recent = bear.list_notes(limit=10)
work = bear.list_notes(tag="work")  # includes nested tags like work/ideas
pinned = bear.list_notes(only=NoteFilter.PINNED)
everything = bear.list_notes(include_trashed=True, include_archived=True)
this_month = bear.list_notes(modified_after=datetime(2026, 7, 1))
```

#### `bear.get_note(note_id) -> Note | None`

Fetch by id; a unique prefix of 4+ characters works like a full id. Loads
attachments. Raises `AmbiguousNoteId` when the prefix matches several notes.

```python
from bearkit import AmbiguousNoteId, Bear

bear = Bear()
try:
    note = bear.get_note("c44d09dc")  # case-insensitive prefix
    print(note.title if note else "no such note")
except AmbiguousNoteId as exc:
    for full_id, title in exc.matches:
        print(full_id, title)
```

#### `bear.list_tags(include_empty=False) -> list[tuple[str, int]]`

All tags with their note counts. Bear keeps empty tag rows around; they are
hidden unless `include_empty=True`.

```python
from bearkit import Bear

bear = Bear()
for name, count in bear.list_tags():
    print(f"{count:4}  {name}")
```

#### `bear.attachment_stats() -> tuple[int, int]`

Count and total bytes of attachments on non-trashed notes.

```python
from bearkit import Bear

bear = Bear()
count, total_bytes = bear.attachment_stats()
print(f"{count} attachments, {total_bytes / 1e6:.1f} MB")
```

#### `bear.search(query, fuzzy=False, min_score=60.0, tag=None) -> list[SearchResult]`

Case-insensitive substring by default; `fuzzy=True` is typo-tolerant and
ranked (results then carry a `score`).

```python
from bearkit import Bear

bear = Bear()
for result in bear.search("invoice", tag="work"):
    print(result.note.title, result.snippet)
for result in bear.search("quarterly planing", fuzzy=True)[:5]:
    print(f"{result.score:5.1f}  {result.note.title}")
```

### Writing

Verified writes raise `BearWriteError` if Bear doesn't observably apply the
change within `bearkit.ops.VERIFY_TIMEOUT` seconds.

#### `bear.create_note(title, text=None, tags=None) -> Note`

```python
from bearkit import Bear, BearWriteError

bear = Bear()
try:
    created = bear.create_note("Meeting notes", "agenda item one", tags=["work"])
    print(created.id)
except BearWriteError:
    print("Bear did not apply the change")
```

#### `bear.add_text(note, text, mode=TextMode.APPEND) -> Note`

`TextMode`: `APPEND`, `PREPEND`, `REPLACE` (body only, keeps the title),
`REPLACE_ALL` (including the title). Strings are accepted and validated.

```python
from bearkit import Bear, TextMode

bear = Bear()
note = bear.get_note("C44D09DC")
assert note is not None
bear.add_text(note, "follow-up item")
bear.add_text(note, "new body", mode=TextMode.REPLACE)
```

#### `bear.rename(note, new_title) -> Note`

Replaces the heading line, keeping the body.

```python
from bearkit import Bear

bear = Bear()
note = bear.get_note("C44D09DC")
assert note is not None
renamed = bear.rename(note, "Better title")
assert renamed.title == "Better title"
```

#### `bear.add_tag(note, name)` / `bear.remove_tag(note, name)`

Tags are inline markers in the note text; `remove_tag` rewrites the text
without the marker and raises `TagMarkerNotFound` when none is present.

```python
from bearkit import Bear, TagMarkerNotFound

bear = Bear()
note = bear.get_note("C44D09DC")
assert note is not None
tagged = bear.add_tag(note, "work/ideas")
try:
    bear.remove_tag(tagged, "work/ideas")
except TagMarkerNotFound:
    print("note has no such tag")
```

#### `bear.attach_file(note, filename, file_b64) -> Note`

The file travels base64-encoded inside a URL; keep it under ~500 KB.

```python
import base64
from pathlib import Path

from bearkit import Bear

bear = Bear()
note = bear.get_note("C44D09DC")
assert note is not None
payload = base64.b64encode(Path("chart.png").read_bytes()).decode()
bear.attach_file(note, "chart.png", payload)
```

#### `bear.trash(note)` / `bear.archive(note)`

One-way: Bear has no untrash/unarchive API (restore is UI-only).

```python
from bearkit import Bear

bear = Bear()
note = bear.get_note("C44D09DC")
assert note is not None
bear.archive(note)
```

#### `bear.rename_tag(name, new_name)` / `bear.delete_tag(name)`

Across all notes; verified via the tag list.

```python
from bearkit import Bear

bear = Bear()
bear.rename_tag("old-name", "new-name")
bear.delete_tag("obsolete")
```

### The Bear app

#### `bear.open(note, new_window=False)`

```python
from bearkit import Bear

bear = Bear()
note = bear.list_notes(limit=1)[0]
bear.open(note)
```

## `Note`

Fields: `id`, `title`, `text` (None **iff encrypted**), `created` /
`modified` (timezone-aware), `pinned` / `encrypted` / `archived` / `trashed`,
`tags`, `attachments` (each with `filename`, `path`, `size`, `exists`).

### `note.has_tag(name)`, `note.to_dict()`, `note.status_line`

```python
from bearkit import Bear

bear = Bear()
note = bear.list_notes(limit=1)[0]
print(note.has_tag("work"))  # case-insensitive, exact tag name
print(note.to_dict())  # serializable: id, title, tags, ISO dates, flags
print(note.status_line)  # e.g. "pinned,archived" ("" when none)
```

## Search - `bearkit.search`

### `naive_search(notes, query) -> list[SearchResult]`

Case-insensitive substring over titles, tags, and text; preserves input
order; `score` is None.

```python
from bearkit import Bear, naive_search

bear = Bear()
notes = bear.list_notes(limit=None)
for result in naive_search(notes, "invoice"):
    print(result.note.title, result.snippet)
```

### `search_notes(notes, query, min_score=60.0) -> list[SearchResult]`

Typo-tolerant and ranked (rapidfuzz); results carry a `score` and a
`snippet` locating the match.

```python
from bearkit import Bear, search_notes

bear = Bear()
notes = bear.list_notes(limit=None)
for result in search_notes(notes, "quarterly planing")[:5]:
    print(f"{result.score:5.1f}  {result.note.title}  {result.snippet}")
```

## Secrets - `bearkit.secrets`

### `scan_notes(notes) -> ScanReport`

Offline detection: known token formats, entropy analysis, and labeled
credentials. The report iterates as `SecretFinding`s and is truthy when
anything was found. `SecretFinding.excerpt` is safe to display;
`SecretFinding.secret` holds the raw value for redaction - never print it.

```python
from bearkit import Bear, scan_notes

bear = Bear()
report = scan_notes(bear.list_notes(limit=None))
print(f"{len(report)} finding(s) in {report.notes_affected()} note(s)")
for f in report:
    print(f.note_title, f.rule, f.line, f.excerpt)
```

### `ScanReport.redact(note)` and friends

`redact(note)` returns the note's text with every detected value replaced by
`[redacted: <rule>]`. `has(note_id)` and `for_note(note_id)` answer per-note
questions without touching raw values; `redact_text(text)` redacts arbitrary
text (e.g. after rewriting links) using every finding in the report.

```python
from bearkit import Bear, scan_notes

bear = Bear()
notes = bear.list_notes(limit=None)
report = scan_notes(notes)
for n in notes:
    if report.has(n.id):
        print(report.redact(n))
```

## Markdown - `bearkit.markdown`

### `rewrite_attachment_refs(note, target_for) -> str`

Rewrites bare attachment links to per-attachment targets, handling Bear's
percent-encoding. Regular URLs are never touched.

```python
from bearkit import Bear
from bearkit.markdown import rewrite_attachment_refs

bear = Bear()
note = bear.list_notes(limit=1)[0]
absolute = rewrite_attachment_refs(note, lambda att: str(att.path))
relative = rewrite_attachment_refs(note, lambda att: f"files/{att.filename}")
```

### `tag_marker(name)` / `remove_tag_marker(text, name)`

The inline marker Bear uses for a tag, and text with that marker stripped
(None when no marker matched; longer tags sharing the prefix are untouched).

```python
from bearkit.markdown import remove_tag_marker, tag_marker

assert tag_marker("work") == "#work"
assert tag_marker("two words") == "#two words#"
stripped = remove_tag_marker("body #work\n", "work")  # "body\n"
assert remove_tag_marker("plain text", "work") is None
```

## Advanced: the raw layers

- `BearDB` - the read-only database handle behind `bear.db`; same reading
  methods as the facade.
- `bearkit.ops` - the verified-write engine; functions take `(db, note, ...)`.
- `bearkit.actions` - fire-and-forget x-callback calls, no verification;
  `actions.wait_for(predicate)` helps hand-roll your own.
