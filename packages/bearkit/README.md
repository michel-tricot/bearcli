<div align="center">

# 🐻 `bearkit`

**The Python toolkit for [Bear](https://bear.app) notes** - read, search, and
write your notes from Python, with secret detection built in.

[![PyPI](https://img.shields.io/pypi/v/bearkit.svg)](https://pypi.org/project/bearkit/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/michel-tricot/bearcli/blob/main/LICENSE)
[![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue.svg)](https://pypi.org/project/bearkit/)
[![macOS](https://img.shields.io/badge/platform-macOS-lightgrey.svg)](#)

[**API reference**](https://github.com/michel-tricot/bearcli/blob/main/docs/BEARKIT.md) ·
[Website](https://michel-tricot.github.io/bearcli/) ·
[`bearcli`](https://pypi.org/project/bearcli/) (the CLI & terminal UI built on it)

</div>

---

## Install

```sh
pip install bearkit            # or: uv add bearkit
```

Lightweight by design: no CLI or UI dependencies, just the fundamentals.

## Quick start

One object, `Bear`, for everything:

```python
from bearkit import Bear

with Bear() as bear:
    for note in bear.list_notes(tag="work", limit=10):
        print(note.title, note.tags)
```

## Read and search

Filter by tag (nested sub-tags included), dates, or status; search naively or
fuzzily, scoped to tags and widened to archived or trashed notes:

```python
from bearkit import Bear

with Bear() as bear:
    pinned = bear.list_notes(only="pinned")
    note = bear.get_note("C44D09DC")  # a unique 4+ char id prefix works

    for result in bear.search("quarterly planing", fuzzy=True)[:5]:
        print(f"{result.score:5.1f}  {result.note.title}")
    for result in bear.search("invoice", tag=["work", "clients"], include_archived=True):
        print(result.note.title, result.snippet)
```

## Verified writes

Writes go through the Bear app itself and are verified before returning - you
get the fresh note back, or `BearWriteError` if Bear didn't apply the change:

```python
from bearkit import Bear, BearWriteError

with Bear() as bear:
    try:
        note = bear.create_note("Meeting notes", text="agenda...", tags=["work"])
        bear.add_tag(note, "from-python")
    except BearWriteError:
        print("Bear did not apply the change")
```

Also: `add_text` (append/prepend/replace), `rename`, `attach_file`, `trash`,
`archive`, `rename_tag`, `delete_tag`, and `open` to bring a note up in Bear.

## Secret detection

Scan notes for leaked credentials (token formats, key blocks, credential
assignments, high-entropy strings) - fully offline - and redact before
sharing:

```python
from bearkit import Bear

with Bear() as bear:
    notes = bear.list_notes(limit=None, include_archived=True)
    report = bear.scan_secrets(notes)
    for finding in report:
        print(finding.note_title, finding.rule, finding.excerpt)  # excerpt is safe to print
    for note in notes:
        if report.has(note.id):
            safe = report.redact(note)  # text with [redacted: <rule>] placeholders
```

> **⚠️ Warning** - detection is best-effort: a secret that reads like ordinary
> prose will not be caught. Ideally, don't keep secrets in notes at all.

## Good to know

- **Typed** - ships `py.typed`; the full API is annotated.
- **Encrypted notes** are listed with their metadata, but their content stays
  in Bear (`note.text` is `None`).
- **Every public function has a runnable sample** in the
  [API reference](https://github.com/michel-tricot/bearcli/blob/main/docs/BEARKIT.md).
- Want a ready-made tool instead of a library? `bearkit` powers
  [`bearcli`](https://pypi.org/project/bearcli/) - the CLI and full terminal
  UI, including markdown export and git mirroring.

## License

[MIT](https://github.com/michel-tricot/bearcli/blob/main/LICENSE) · not
affiliated with [Shiny Frog](https://shinyfrog.app)
