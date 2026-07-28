"""Read-only access to Bear's SQLite database."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

DEFAULT_DB_PATH = (
    Path.home() / "Library/Group Containers/9K33E3U3T4.net.shinyfrog.bear" / "Application Data/database.sqlite"
)

# Core Data stores timestamps as seconds since 2001-01-01 UTC.
CORE_DATA_EPOCH = datetime(2001, 1, 1, tzinfo=UTC)


def core_data_to_datetime(value: float | None) -> datetime | None:
    if value is None:
        return None
    return (CORE_DATA_EPOCH + timedelta(seconds=value)).astimezone()


def datetime_to_core_data(value: datetime) -> float:
    if value.tzinfo is None:
        value = value.astimezone()
    return (value - CORE_DATA_EPOCH).total_seconds()


@dataclass
class Attachment:
    id: str
    filename: str
    path: Path
    size: int | None
    exists: bool


@dataclass
class Note:
    id: str
    title: str
    created: datetime | None
    modified: datetime | None
    pinned: bool
    encrypted: bool
    archived: bool
    trashed: bool
    tags: list[str] = field(default_factory=list)
    text: str | None = None
    attachments: list[Attachment] = field(default_factory=list)


class BearDB:
    def __init__(self, path: Path = DEFAULT_DB_PATH):
        if not path.exists():
            raise FileNotFoundError(f"Bear database not found at {path}")
        self.conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        self.conn.row_factory = sqlite3.Row
        self.files_dir = path.parent / "Local Files"
        self._tags_join = self._detect_tags_join()

    def close(self) -> None:
        self.conn.close()

    def _detect_tags_join(self) -> tuple[str, str, str]:
        """Find the note<->tag join table; its numeric prefixes vary by Bear version.

        Returns (table, note_column, tag_column).
        """
        rows = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'Z\\_%TAGS' ESCAPE '\\'"
        ).fetchall()
        for (table,) in rows:
            if not re.fullmatch(r"Z_\d+TAGS", table):
                continue
            columns = [r["name"] for r in self.conn.execute(f"PRAGMA table_info({table})")]
            note_col = next((c for c in columns if re.fullmatch(r"Z_\d+NOTES", c)), None)
            tag_col = next((c for c in columns if re.fullmatch(r"Z_\d+TAGS", c)), None)
            if note_col and tag_col:
                return table, note_col, tag_col
        raise RuntimeError("Could not locate the note/tag join table in the Bear database")

    def _tags_for_note(self, note_pk: int) -> list[str]:
        table, note_col, tag_col = self._tags_join
        rows = self.conn.execute(
            f"""
            SELECT t.ZTITLE FROM ZSFNOTETAG t
            JOIN {table} j ON j.{tag_col} = t.Z_PK
            WHERE j.{note_col} = ?
            ORDER BY t.ZTITLE
            """,
            (note_pk,),
        ).fetchall()
        return [r["ZTITLE"] for r in rows]

    def list_tags(self) -> list[tuple[str, int]]:
        """All tags with their note counts (excluding trashed/deleted notes)."""
        table, note_col, tag_col = self._tags_join
        rows = self.conn.execute(
            f"""
            SELECT t.ZTITLE, COUNT(n.Z_PK)
            FROM ZSFNOTETAG t
            LEFT JOIN {table} j ON j.{tag_col} = t.Z_PK
            LEFT JOIN ZSFNOTE n
                ON n.Z_PK = j.{note_col} AND n.ZTRASHED = 0 AND n.ZPERMANENTLYDELETED = 0
            GROUP BY t.Z_PK
            ORDER BY t.ZTITLE
            """
        ).fetchall()
        return [(row[0], row[1]) for row in rows]

    def _attachments_for_note(self, note_pk: int) -> list[Attachment]:
        rows = self.conn.execute(
            """
            SELECT ZUNIQUEIDENTIFIER, ZFILENAME, ZFILESIZE FROM ZSFNOTEFILE
            WHERE ZNOTE = ? AND ZPERMANENTLYDELETED = 0 ORDER BY ZFILENAME
            """,
            (note_pk,),
        ).fetchall()
        attachments = []
        for row in rows:
            # Images live under "Note Images", everything else under "Note Files";
            # the database doesn't record which, so probe both.
            candidates = [
                self.files_dir / subdir / row["ZUNIQUEIDENTIFIER"] / row["ZFILENAME"]
                for subdir in ("Note Images", "Note Files")
            ]
            path = next((c for c in candidates if c.exists()), candidates[0])
            attachments.append(
                Attachment(
                    id=row["ZUNIQUEIDENTIFIER"],
                    filename=row["ZFILENAME"],
                    path=path,
                    size=row["ZFILESIZE"],
                    exists=path.exists(),
                )
            )
        return attachments

    def list_notes(
        self,
        limit: int | None = None,
        tag: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        modified_after: datetime | None = None,
        modified_before: datetime | None = None,
        search: str | None = None,
        only: str | None = None,
        include_trashed: bool = False,
        include_archived: bool = False,
    ) -> list[Note]:
        table, note_col, tag_col = self._tags_join
        # Deleted-pending-sync rows linger in the table; never show them.
        where = ["n.ZPERMANENTLYDELETED = 0"]
        params: list[object] = []

        if only == "pinned":
            where.append("n.ZPINNED = 1")
        elif only == "encrypted":
            where.append("n.ZENCRYPTED = 1")

        if only == "trashed":
            where.append("n.ZTRASHED = 1")
        elif not include_trashed:
            where.append("n.ZTRASHED = 0")
        if only == "archived":
            where.append("n.ZARCHIVED = 1")
        elif not include_archived and only != "trashed":
            # A note trashed from the archive keeps both flags; Bear shows it in
            # the trash, so --only trashed must not exclude archived notes.
            where.append("n.ZARCHIVED = 0")
        if tag:
            # Match the tag itself and its nested sub-tags (e.g. "work" matches "work/ideas").
            where.append(
                f"""n.Z_PK IN (
                    SELECT j.{note_col} FROM {table} j
                    JOIN ZSFNOTETAG t ON t.Z_PK = j.{tag_col}
                    WHERE t.ZTITLE = ? OR t.ZTITLE LIKE ? ESCAPE '\\'
                )"""
            )
            escaped = tag.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            params += [tag, f"{escaped}/%"]
        if created_after:
            where.append("n.ZCREATIONDATE >= ?")
            params.append(datetime_to_core_data(created_after))
        if created_before:
            where.append("n.ZCREATIONDATE < ?")
            params.append(datetime_to_core_data(created_before))
        if modified_after:
            where.append("n.ZMODIFICATIONDATE >= ?")
            params.append(datetime_to_core_data(modified_after))
        if modified_before:
            where.append("n.ZMODIFICATIONDATE < ?")
            params.append(datetime_to_core_data(modified_before))
        if search:
            where.append("(n.ZTITLE LIKE ? OR n.ZTEXT LIKE ?)")
            params += [f"%{search}%", f"%{search}%"]

        query = """
            SELECT n.Z_PK, n.ZUNIQUEIDENTIFIER, n.ZTITLE, n.ZCREATIONDATE,
                   n.ZMODIFICATIONDATE, n.ZPINNED, n.ZENCRYPTED, n.ZARCHIVED, n.ZTRASHED
            FROM ZSFNOTE n
        """
        if where:
            query += " WHERE " + " AND ".join(where)
        query += " ORDER BY n.ZMODIFICATIONDATE DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)

        notes = []
        for row in self.conn.execute(query, params):
            notes.append(
                Note(
                    id=row["ZUNIQUEIDENTIFIER"],
                    title=row["ZTITLE"] or "(untitled)",
                    created=core_data_to_datetime(row["ZCREATIONDATE"]),
                    modified=core_data_to_datetime(row["ZMODIFICATIONDATE"]),
                    pinned=bool(row["ZPINNED"]),
                    encrypted=bool(row["ZENCRYPTED"]),
                    archived=bool(row["ZARCHIVED"]),
                    trashed=bool(row["ZTRASHED"]),
                    tags=self._tags_for_note(row["Z_PK"]),
                )
            )
        return notes

    def get_note(self, note_id: str) -> Note | None:
        row = self.conn.execute(
            """
            SELECT Z_PK, ZUNIQUEIDENTIFIER, ZTITLE, ZTEXT, ZCREATIONDATE,
                   ZMODIFICATIONDATE, ZPINNED, ZENCRYPTED, ZARCHIVED, ZTRASHED
            FROM ZSFNOTE
            WHERE ZUNIQUEIDENTIFIER = ? COLLATE NOCASE
            """,
            (note_id,),
        ).fetchone()
        if row is None:
            return None
        return Note(
            id=row["ZUNIQUEIDENTIFIER"],
            title=row["ZTITLE"] or "(untitled)",
            created=core_data_to_datetime(row["ZCREATIONDATE"]),
            modified=core_data_to_datetime(row["ZMODIFICATIONDATE"]),
            pinned=bool(row["ZPINNED"]),
            encrypted=bool(row["ZENCRYPTED"]),
            archived=bool(row["ZARCHIVED"]),
            trashed=bool(row["ZTRASHED"]),
            tags=self._tags_for_note(row["Z_PK"]),
            text=row["ZTEXT"],
            attachments=self._attachments_for_note(row["Z_PK"]),
        )
