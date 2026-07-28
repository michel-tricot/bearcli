"""Synthetic Bear database fixture — the real schema, fabricated data."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from bearlib.db import BearDB, datetime_to_core_data

SCHEMA = """
CREATE TABLE ZSFNOTE (
    Z_PK INTEGER PRIMARY KEY, ZUNIQUEIDENTIFIER VARCHAR, ZTITLE VARCHAR,
    ZTEXT VARCHAR, ZCREATIONDATE TIMESTAMP, ZMODIFICATIONDATE TIMESTAMP,
    ZPINNED INTEGER DEFAULT 0, ZENCRYPTED INTEGER DEFAULT 0,
    ZARCHIVED INTEGER DEFAULT 0, ZTRASHED INTEGER DEFAULT 0,
    ZPERMANENTLYDELETED INTEGER DEFAULT 0
);
CREATE TABLE ZSFNOTETAG (Z_PK INTEGER PRIMARY KEY, ZTITLE VARCHAR);
CREATE TABLE Z_5TAGS (Z_5NOTES INTEGER, Z_13TAGS INTEGER);
CREATE TABLE ZSFNOTEFILE (
    Z_PK INTEGER PRIMARY KEY, ZNOTE INTEGER, ZUNIQUEIDENTIFIER VARCHAR,
    ZFILENAME VARCHAR, ZFILESIZE INTEGER, ZPERMANENTLYDELETED INTEGER DEFAULT 0
);
"""


class FakeBear:
    """Builds a Bear-shaped database (and Local Files tree) under a tmp dir."""

    def __init__(self, root: Path):
        self.dir = root / "Application Data"
        self.dir.mkdir(parents=True)
        self.path = self.dir / "database.sqlite"
        self.conn = sqlite3.connect(self.path)
        self.conn.executescript(SCHEMA)
        self._pk = 0
        self._tag_pks: dict[str, int] = {}

    def add_note(
        self,
        note_id: str,
        title: str,
        text: str | None = None,
        created: object = None,
        modified: object = None,
        tags: tuple[str, ...] = (),
        pinned: bool = False,
        encrypted: bool = False,
        archived: bool = False,
        trashed: bool = False,
        deleted: bool = False,
        attachments: tuple[tuple[str, str, bytes], ...] = (),  # (uuid, filename, content)
    ) -> int:
        self._pk += 1
        if text is None and not encrypted:
            text = f"# {title}\nbody of {title}\n"
        self.conn.execute(
            "INSERT INTO ZSFNOTE VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                self._pk,
                note_id,
                title,
                None if encrypted else text,
                datetime_to_core_data(created) if created else 700000000.0 + self._pk,
                datetime_to_core_data(modified) if modified else 800000000.0 + self._pk,
                int(pinned),
                int(encrypted),
                int(archived),
                int(trashed),
                int(deleted),
            ),
        )
        for tag in tags:
            if tag not in self._tag_pks:
                self._tag_pks[tag] = len(self._tag_pks) + 1
                self.conn.execute("INSERT INTO ZSFNOTETAG VALUES (?,?)", (self._tag_pks[tag], tag))
            self.conn.execute("INSERT INTO Z_5TAGS VALUES (?,?)", (self._pk, self._tag_pks[tag]))
        for att_uuid, filename, content in attachments:
            self.conn.execute(
                "INSERT INTO ZSFNOTEFILE (ZNOTE, ZUNIQUEIDENTIFIER, ZFILENAME, ZFILESIZE) VALUES (?,?,?,?)",
                (self._pk, att_uuid, filename, len(content)),
            )
            file_path = self.dir / "Local Files" / "Note Images" / att_uuid / filename
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(content)
        return self._pk

    def open(self) -> BearDB:
        self.conn.commit()
        return BearDB(self.path)


@pytest.fixture
def bear(tmp_path: Path) -> FakeBear:
    return FakeBear(tmp_path)


@pytest.fixture
def populated(bear: FakeBear) -> FakeBear:
    bear.add_note("AAAA1111-0000-0000-0000-000000000001", "Groceries", "# Groceries\nmilk and eggs\n", tags=("home",))
    bear.add_note(
        "BBBB2222-0000-0000-0000-000000000002",
        "Project plan",
        "# Project plan\nroadmap draft\n",
        tags=("work", "work/ideas"),
        pinned=True,
    )
    bear.add_note("CCCC3333-0000-0000-0000-000000000003", "Old stuff", archived=True)
    bear.add_note("DDDD4444-0000-0000-0000-000000000004", "Gone", trashed=True)
    bear.add_note("EEEE5555-0000-0000-0000-000000000005", "Vault", encrypted=True)
    bear.add_note("FFFF6666-0000-0000-0000-000000000006", "Ghost", deleted=True)
    return bear
