"""The Bear facade delegates reads and performs verified writes."""

import pytest

from bearlib import Bear, BearWriteError, actions, ops


@pytest.fixture(autouse=True)
def fast_verify(monkeypatch):
    monkeypatch.setattr(ops, "VERIFY_TIMEOUT", 0.15)


def test_reads_delegate(populated):
    populated.conn.commit()
    with Bear(populated.path) as bear:
        assert {n.title for n in bear.list_notes()} == {"Groceries", "Project plan", "Vault"}
        note = bear.get_note("AAAA1111")
        assert note is not None and note.title == "Groceries"
        assert dict(bear.list_tags())["home"] == 1
        count, _ = bear.attachment_stats()
        assert count == 0


def test_verified_write_success_and_failure(populated, monkeypatch):
    def apply_archive(action, foreground=False, **params):
        populated.conn.execute("UPDATE ZSFNOTE SET ZARCHIVED = 1 WHERE ZUNIQUEIDENTIFIER = ?", (params["id"],))
        populated.conn.commit()

    monkeypatch.setattr(actions, "call_bear", apply_archive)
    populated.conn.commit()
    bear = Bear(populated.path)
    note = bear.get_note("AAAA1111")
    assert bear.archive(note).archived

    monkeypatch.setattr(actions, "call_bear", lambda *a, **k: None)
    other = bear.get_note("BBBB2222")
    with pytest.raises(BearWriteError):
        bear.trash(other)


def test_note_methods(populated):
    populated.conn.commit()
    bear = Bear(populated.path)
    note = bear.get_note("BBBB2222")
    assert note.has_tag("WORK")  # case-insensitive
    assert note.to_dict()["pinned"] is True
    assert note.status_line == "pinned"
