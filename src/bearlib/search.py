"""Fuzzy search over notes using rapidfuzz."""

from __future__ import annotations

import re
from dataclasses import dataclass

from rapidfuzz import fuzz, utils

from bearlib.db import Note

# Where the match landed determines its weight: a title hit beats an equally
# good tag hit, which beats a body hit.
TITLE_WEIGHT = 1.0
TAG_WEIGHT = 0.95
BODY_WEIGHT = 0.9

SNIPPET_LENGTH = 70


@dataclass
class SearchResult:
    note: Note
    snippet: str
    score: float | None = None  # None for naive (substring) matches


def naive_search(notes: list[Note], query: str) -> list[SearchResult]:
    """Case-insensitive substring search over titles, tags, and text.

    Input order (most recently modified first) is preserved.
    """
    needle = query.lower()
    results = []
    for note in notes:
        title_hit = needle in note.title.lower()
        tag_hit = any(needle in tag.lower() for tag in note.tags)
        body_line = next(
            (line.strip() for line in (note.text or "").splitlines() if needle in line.lower()),
            "",
        )
        if not (title_hit or tag_hit or body_line):
            continue
        snippet = _trim_snippet(body_line, query) if body_line and not (title_hit or tag_hit) else ""
        results.append(SearchResult(note=note, snippet=snippet))
    return results


def _fuzzy_score(processed_query: str, target: str) -> float:
    """Direction-aware scoring: the query must always be the needle.

    partial_ratio slides the shorter string over the longer one, so a trivially
    short target ("Bindi") would score ~80 against a long query. Only allow the
    sliding when the target is at least query-sized; otherwise use plain ratio,
    which penalizes the missing content.
    """
    processed_target = utils.default_process(target)
    if not processed_query or not processed_target:
        return 0.0
    if len(processed_target) >= len(processed_query):
        return fuzz.partial_ratio(processed_query, processed_target)
    return fuzz.ratio(processed_query, processed_target)


def _body_match(query: str, text: str | None) -> tuple[float, str]:
    """Score the query against the full note text; return (score, matching line).

    partial_ratio must slide the query over the text, never the reverse: with a
    short haystack the needle/haystack roles flip and trivial strings score ~90.
    """
    processed_query = utils.default_process(query)
    processed_text = utils.default_process(text or "")
    if not processed_query or not processed_text:
        return 0.0, ""
    if len(processed_text) < len(processed_query):
        return fuzz.ratio(processed_query, processed_text), (text or "").strip().splitlines()[0]

    alignment = fuzz.partial_ratio_alignment(processed_query, processed_text)
    if alignment is None:
        return 0.0, ""
    # default_process keeps positions 1:1 (non-alnum become spaces) except for
    # the leading strip, so shift by where the first alphanumeric char was.
    first_alnum = re.search(r"[^\W_]", text or "")
    pos = alignment.dest_start + (first_alnum.start() if first_alnum else 0)
    line_start = (text or "").rfind("\n", 0, pos) + 1
    line_end = (text or "").find("\n", pos)
    line = (text or "")[line_start : line_end if line_end >= 0 else None].strip()
    return alignment.score, line


def _trim_snippet(line: str, query: str) -> str:
    if len(line) <= SNIPPET_LENGTH:
        return line
    # Center the snippet on the first query word that occurs literally, if any.
    lowered = line.lower()
    pos = next((p for w in query.lower().split() if (p := lowered.find(w)) >= 0), 0)
    start = max(0, min(pos - SNIPPET_LENGTH // 3, len(line) - SNIPPET_LENGTH))
    end = start + SNIPPET_LENGTH
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(line) else ""
    return f"{prefix}{line[start:end].strip()}{suffix}"


def search_notes(notes: list[Note], query: str, min_score: float = 60.0) -> list[SearchResult]:
    """Score every note against the query; return matches sorted best-first."""
    processed_query = utils.default_process(query)
    results = []
    for note in notes:
        title_score = _fuzzy_score(processed_query, note.title) * TITLE_WEIGHT
        tag_score = max(_fuzzy_score(processed_query, tag) for tag in note.tags) * TAG_WEIGHT if note.tags else 0.0
        body_raw, body_line = _body_match(query, note.text)
        body_score = body_raw * BODY_WEIGHT

        score = max(title_score, tag_score, body_score)
        if score < min_score:
            continue
        snippet = _trim_snippet(body_line, query) if body_score >= max(title_score, tag_score) else ""
        results.append(SearchResult(note=note, score=score, snippet=snippet))

    results.sort(key=lambda r: r.score or 0.0, reverse=True)
    return results
