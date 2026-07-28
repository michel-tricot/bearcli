"""Export Bear notes to self-contained per-note directories."""

from __future__ import annotations

import json
import re
import shutil
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from bearkit.db import BearDB, Note
from bearkit.markdown import rewrite_attachment_refs
from bearkit.secrets import ScanReport

NOTE_FILENAME = "README.md"
ATTACHMENTS_DIRNAME = "attachments"


@dataclass
class ExportResult:
    written: int = 0
    unchanged: int = 0
    removed: int = 0
    skipped_encrypted: int = 0
    index_updated: bool = False


def slugify(title: str, max_length: int = 60) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:max_length].rstrip("-") or "untitled"


def _dirnames(notes: list[Note]) -> dict[str, str]:
    """Map note id -> directory name: <slug>-<first 8 id chars>.

    The id fragment makes names unique without title-dedup suffixes. In the
    astronomically rare case two notes share both slug and id prefix, those
    notes use their full id so the outcome never depends on iteration order.
    """
    short = {n.id: f"{slugify(n.title)}-{n.id[:8].lower()}" for n in notes}
    counts = Counter(short.values())
    return {n.id: short[n.id] if counts[short[n.id]] == 1 else f"{slugify(n.title)}-{n.id.lower()}" for n in notes}


def _frontmatter(note: Note, redacted: bool = False) -> str:
    lines = [
        "---",
        f"id: {note.id}",
        f"title: {json.dumps(note.title, ensure_ascii=False)}",
        f"tags: [{', '.join(note.tags)}]",
    ]
    if note.created:
        lines.append(f"created: {note.created.isoformat()}")
    if note.modified:
        lines.append(f"modified: {note.modified.isoformat()}")
    if redacted:
        lines.append("redacted: true")
    lines.append("---")
    return "\n".join(lines)


def _parse_frontmatter(path: Path) -> dict[str, str]:
    fields: dict[str, str] = {}
    try:
        with path.open() as fh:
            if fh.readline().rstrip("\n") != "---":
                return fields
            for line in fh:
                line = line.rstrip("\n")
                if line == "---":
                    break
                key, _, value = line.partition(": ")
                fields[key] = value
    except OSError:
        pass
    return fields


INDEX_MARKER = "generated-by: bearcli"


def _entry_flags(entry: dict) -> str:
    flags = ""
    if entry["attachments"]:
        flags += "📎"
    if entry["encrypted"]:
        flags += "🔒"
    if entry["archived"]:
        flags += "🗄"
    return flags


_INDEX_TITLE_LENGTH = 48


def _ellipsize(value: str, length: int) -> str:
    return value if len(value) <= length else value[: length - 1].rstrip() + "…"


def _index_rows(entries: list[dict]) -> list[str]:
    rows = ["| ID | Modified | | Note |", "|---|---|---|---|"]
    for e in entries:
        title = _ellipsize(e["title"].replace("|", "\\|"), _INDEX_TITLE_LENGTH)
        link = f"[{title}]({e['path']})" if e["path"] else title
        # The short id resolves anywhere a note id is accepted (git-style prefix).
        rows.append(f"| `{e['id'][:8].lower()}` | {(e['modified'] or '')[:10]} | {_entry_flags(e)} | {link} |")
    return rows


def _index_markdown(entries: list[dict]) -> str:
    entries = sorted(entries, key=lambda e: e["modified"] or "", reverse=True)
    lines = [
        "---",
        INDEX_MARKER,
        "---",
        "",
        "# Bear notes",
        "",
        f"{len(entries)} notes · 📎 attachments · 🔒 encrypted · 🗄 archived",
        "",
    ]
    archived = [e for e in entries if e["archived"]]
    active = [e for e in entries if not e["archived"]]
    pinned = [e for e in active if e["pinned"]]
    if pinned:
        lines += ["## 📌 Pinned", ""] + _index_rows(pinned) + [""]
    rest = [e for e in active if not e["pinned"]]
    by_year: dict[str, list[dict]] = {}
    for e in rest:
        year = e["modified"][:4] if e["modified"] else "Undated"
        by_year.setdefault(year, []).append(e)
    for year in sorted(by_year, reverse=True):
        lines += [f"## {year}", ""] + _index_rows(by_year[year]) + [""]
    if archived:
        lines += ["## 🗄 Archived", ""] + _index_rows(archived) + [""]
    return "\n".join(lines)


def _write_if_changed(path: Path, content: str) -> bool:
    try:
        if path.read_text() == content:
            return False
    except OSError:
        pass
    path.write_text(content)
    return True


def _rewrite_refs(note: Note) -> str:
    return rewrite_attachment_refs(note, lambda att: f"{ATTACHMENTS_DIRNAME}/{att.filename}")


def export_notes(
    db: BearDB,
    dest: Path,
    sync: bool = False,
    progress: Callable[[str], None] | None = None,
    redactions: ScanReport | None = None,
) -> ExportResult:
    """Write every non-trashed note as dest/<slug>/README.md plus attachments/.

    With sync=True, notes whose id and modified timestamp match the existing
    README's frontmatter are left untouched. In both modes, directories for
    notes that no longer exist (or whose title changed slug) are removed; only
    directories whose README carries an `id:` frontmatter field are ever touched.
    """
    dest.mkdir(parents=True, exist_ok=True)
    result = ExportResult()

    def report(message: str) -> None:
        if progress is not None:
            progress(message)

    report("Reading notes from Bear…")
    summaries = db.list_notes(limit=None, include_archived=True)
    dirnames = _dirnames(summaries)

    entries: list[dict] = []

    def add_entry(note: Note, path: str | None, attachments: bool) -> None:
        entries.append({**note.to_dict(), "path": path, "attachments": attachments})

    for position, summary in enumerate(summaries, start=1):
        report(f"[{position}/{len(summaries)}] {summary.title}")
        if summary.encrypted:
            result.skipped_encrypted += 1
            add_entry(summary, None, False)
            continue

        slug = dirnames[summary.id]
        note_dir = dest / slug
        note_path = note_dir / NOTE_FILENAME

        note_secrets = redactions.for_note(summary.id) if redactions else {}
        modified_iso = summary.modified.isoformat() if summary.modified else ""
        if sync and note_path.exists():
            existing = _parse_frontmatter(note_path)
            # A change in redaction state must rewrite the file even though the
            # note itself is unchanged — otherwise a previously exported secret
            # would survive a later --redact-secrets run (and vice versa).
            same_redaction = (existing.get("redacted") == "true") == bool(note_secrets)
            if existing.get("id") == summary.id and existing.get("modified") == modified_iso and same_redaction:
                result.unchanged += 1
                add_entry(summary, f"{slug}/", (note_dir / ATTACHMENTS_DIRNAME).exists())
                continue

        note = db.get_note(summary.id)
        if note is None or note.text is None:
            result.skipped_encrypted += 1
            add_entry(summary, None, False)
            continue

        text = _rewrite_refs(note)
        if note_secrets and redactions is not None:
            text = redactions.redact_text(text)
        note_dir.mkdir(exist_ok=True)
        note_path.write_text(f"{_frontmatter(note, redacted=bool(note_secrets))}\n{text}\n")

        attach_dir = note_dir / ATTACHMENTS_DIRNAME
        if attach_dir.exists():
            shutil.rmtree(attach_dir)
        for att in note.attachments:
            if not att.exists:
                continue
            attach_dir.mkdir(exist_ok=True)
            shutil.copy2(att.path, attach_dir / att.filename)
        result.written += 1
        add_entry(note, f"{slug}/", attach_dir.exists())

    # Remove directories for notes that were deleted in Bear or whose slug changed.
    report("Cleaning up removed notes…")
    current_dirs = set(dirnames.values())
    for stale in dest.iterdir():
        if not stale.is_dir() or stale.name in current_dirs:
            continue
        if not _parse_frontmatter(stale / NOTE_FILENAME).get("id"):
            continue
        shutil.rmtree(stale)
        result.removed += 1

    report("Writing index…")
    index_path = dest / "README.md"
    result.index_updated = _write_if_changed(index_path, _index_markdown(entries))
    result.index_updated |= _write_if_changed(
        dest / "index.json",
        json.dumps(sorted(entries, key=lambda e: e["title"].lower()), indent=2, ensure_ascii=False) + "\n",
    )

    return result
