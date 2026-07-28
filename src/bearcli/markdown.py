"""Helpers for Bear's markdown conventions, shared by the CLI, TUI, and export."""

from __future__ import annotations

import re
from collections.abc import Callable
from urllib.parse import quote

from bearcli.db import Attachment, Note


def rewrite_attachment_refs(note: Note, target_for: Callable[[Attachment], str]) -> str:
    """Rewrite bare attachment filename links to per-attachment targets.

    Bear references attachments by bare filename and percent-encodes it in the
    note text (spaces as %20), so both the raw and encoded forms must be
    matched; targets are emitted percent-encoded to keep the links valid.
    Only filenames known from the attachment records are rewritten — regular
    URLs in the text are never touched.
    """
    text = note.text or ""
    for att in note.attachments:
        target = quote(target_for(att))
        for ref in {att.filename, quote(att.filename)}:
            text = text.replace(f"]({ref})", f"]({target})")
    return text


def tag_marker(name: str) -> str:
    """The inline marker Bear uses for a tag: #name, or #name# when it needs delimiting."""
    return f"#{name}#" if re.search(r"[^\w/-]", name) else f"#{name}"


def remove_tag_marker(text: str, name: str) -> str | None:
    """The text with the tag's inline markers stripped, or None if none matched.

    Longer tags sharing the prefix are left alone: removing "work" must not
    touch "#work/ideas" or "#workout".
    """
    escaped = re.escape(name)
    stripped = re.sub(rf"[ \t]?#{escaped}#", "", text, flags=re.IGNORECASE)
    stripped = re.sub(rf"[ \t]?#{escaped}(?![\w/-])", "", stripped, flags=re.IGNORECASE)
    if stripped == text:
        return None
    return stripped.rstrip("\n") + "\n"
