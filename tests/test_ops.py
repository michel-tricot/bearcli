"""Verified-write behavior, with the x-callback layer stubbed out."""

import pytest

from bearkit import actions, ops


@pytest.fixture(autouse=True)
def fast_verify(monkeypatch):
    monkeypatch.setattr(ops, "VERIFY_TIMEOUT", 0.15)


def test_write_raises_when_bear_does_nothing(populated, monkeypatch):
    monkeypatch.setattr(actions, "call_bear", lambda *a, **k: None)
    db = populated.open()
    note = db.get_note("AAAA1111")
    with pytest.raises(ops.BearWriteError):
        ops.trash(db, note)


def test_write_returns_fresh_note_when_applied(populated, monkeypatch):
    def apply_trash(action, foreground=False, **params):
        populated.conn.execute("UPDATE ZSFNOTE SET ZTRASHED = 1 WHERE ZUNIQUEIDENTIFIER = ?", (params["id"],))
        populated.conn.commit()

    monkeypatch.setattr(actions, "call_bear", apply_trash)
    db = populated.open()
    note = db.get_note("AAAA1111")
    fresh = ops.trash(db, note)
    assert fresh.trashed


def test_remove_tag_without_marker_raises(populated, monkeypatch):
    monkeypatch.setattr(actions, "call_bear", lambda *a, **k: None)
    db = populated.open()
    note = db.get_note("AAAA1111")  # tagged "home" but marker not in body text
    with pytest.raises(ops.TagMarkerNotFound):
        ops.remove_tag(db, note, "nonexistent")


def test_text_mode_accepts_strings_and_rejects_junk():
    assert ops.TextMode("replace_all") is ops.TextMode.REPLACE_ALL
    with pytest.raises(ValueError):
        ops.TextMode("bogus")


def test_note_filter_validates(populated):
    db = populated.open()
    with pytest.raises(ValueError):
        db.list_notes(only="bogus")


def test_beardb_context_manager(populated):
    with populated.open() as db:
        assert db.list_notes(limit=1)
