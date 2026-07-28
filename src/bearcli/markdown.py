"""Helpers for Bear's markdown conventions, shared by get and export."""

from __future__ import annotations

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
