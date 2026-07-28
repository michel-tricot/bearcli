"""FastMCP server exposing Bear notes to AI apps (the `mcp` command). Stdio only.

Every tool opens a fresh connection so long-running sessions always see
current data. Note text returned to the model is secret-redacted by default:
MCP clients ship tool results to their model provider, so raw credentials
must not travel unless the user explicitly turns redaction off.
"""

from __future__ import annotations

from pathlib import Path

from fastmcp import FastMCP

from bearkit import Bear, TextMode, scan_notes
from bearkit.db import DEFAULT_DB_PATH, Note


def _summary(note: Note) -> dict:
    return note.to_dict()


def _redacted_text(note: Note, redact: bool) -> str | None:
    if note.text is None:
        return None
    return scan_notes([note]).redact_text(note.text) if redact else note.text


def _require(bear: Bear, note_id: str) -> Note:
    note = bear.get_note(note_id)
    if note is None:
        raise ValueError(f"no note with id {note_id!r}")
    return note


def build_server(db_path: Path = DEFAULT_DB_PATH) -> FastMCP:
    server = FastMCP(
        name="bearcli",
        instructions=(
            "Read, search, and manage the user's Bear notes. Note ids accept unique "
            "prefixes of 4+ characters. Writes go through the Bear app and are "
            "verified; they fail if Bear cannot run. Encrypted notes have no "
            "readable text."
        ),
    )

    @server.tool
    def list_notes(
        limit: int = 20,
        tag: str | None = None,
        only: str | None = None,
        include_trashed: bool = False,
        include_archived: bool = False,
    ) -> list[dict]:
        """List notes (metadata only), most recently modified first.

        `tag` includes nested sub-tags; `only` filters to one status:
        pinned, encrypted, trashed, or archived.
        """
        with Bear(db_path) as bear:
            return [
                _summary(n)
                for n in bear.list_notes(
                    limit=limit,
                    tag=tag,
                    only=only,
                    include_trashed=include_trashed,
                    include_archived=include_archived,
                )
            ]

    @server.tool
    def get_note(note_id: str, redact_secrets: bool = True) -> dict:
        """Fetch one note: metadata plus its markdown text.

        Detected secrets are replaced with [redacted: <rule>] placeholders
        unless redact_secrets is false (only disable when the user explicitly
        wants raw credential values).
        """
        with Bear(db_path) as bear:
            note = _require(bear, note_id)
            return {**_summary(note), "text": _redacted_text(note, redact_secrets)}

    @server.tool
    def search_notes(query: str, fuzzy: bool = False, tag: str | None = None, limit: int = 10) -> list[dict]:
        """Search titles, tags, and content; fuzzy is typo-tolerant and adds a score."""
        with Bear(db_path) as bear:
            results = bear.search(query, fuzzy=fuzzy, tag=tag)[:limit]
            return [
                {**_summary(r.note), "snippet": r.snippet} | ({"score": r.score} if r.score is not None else {})
                for r in results
            ]

    @server.tool
    def list_tags() -> list[dict]:
        """All tags with their note counts."""
        with Bear(db_path) as bear:
            return [{"tag": t, "notes": c} for t, c in bear.list_tags()]

    @server.tool
    def create_note(title: str, text: str | None = None, tags: list[str] | None = None) -> dict:
        """Create a note; returns it (with its new id) once Bear confirms."""
        with Bear(db_path) as bear:
            return _summary(bear.create_note(title, text, tags))

    @server.tool
    def append_to_note(note_id: str, text: str, prepend: bool = False) -> dict:
        """Append (or prepend) text to a note; returns the updated note."""
        with Bear(db_path) as bear:
            note = _require(bear, note_id)
            mode = TextMode.PREPEND if prepend else TextMode.APPEND
            return _summary(bear.add_text(note, text, mode=mode))

    @server.tool
    def rename_note(note_id: str, new_title: str) -> dict:
        """Change a note's title, keeping the body."""
        with Bear(db_path) as bear:
            return _summary(bear.rename(_require(bear, note_id), new_title))

    @server.tool
    def add_tag(note_id: str, tag: str) -> dict:
        """Add a tag to a note (no leading #)."""
        with Bear(db_path) as bear:
            return _summary(bear.add_tag(_require(bear, note_id), tag))

    @server.tool
    def remove_tag(note_id: str, tag: str) -> dict:
        """Remove a tag from a note."""
        with Bear(db_path) as bear:
            return _summary(bear.remove_tag(_require(bear, note_id), tag))

    @server.tool
    def trash_note(note_id: str) -> dict:
        """Move a note to Bear's trash. One-way: restoring requires Bear's UI."""
        with Bear(db_path) as bear:
            return _summary(bear.trash(_require(bear, note_id)))

    @server.tool
    def archive_note(note_id: str) -> dict:
        """Archive a note. One-way: unarchiving requires Bear's UI."""
        with Bear(db_path) as bear:
            return _summary(bear.archive(_require(bear, note_id)))

    @server.tool
    def open_note_in_bear(note_id: str) -> str:
        """Bring a note up in the Bear app on the user's screen."""
        with Bear(db_path) as bear:
            note = _require(bear, note_id)
            bear.open(note)
            return f"Opened {note.title!r} in Bear"

    return server


def run(db_path: Path = DEFAULT_DB_PATH) -> None:
    """Serve over stdio (the only supported transport)."""
    build_server(db_path).run(transport="stdio", show_banner=False)


__all__ = ["build_server", "run"]
