"""The Bear facade delegates reads and performs verified writes."""

import pytest

from bearkit import Bear, BearWriteError, actions, ops


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


def test_facade_scan_secrets_covers_archived(populated):
    populated.add_note(
        "SECA0000-0000-0000-0000-000000000001",
        "Old keys",
        text="# Old keys\nkey AKIAIOSFODNN7EXAMPLE\n",
        archived=True,
    )
    populated.conn.commit()
    bear = Bear(populated.path)
    report = bear.scan_secrets()
    assert report.has("SECA0000-0000-0000-0000-000000000001")
    subset = bear.scan_secrets(bear.list_notes())  # active notes only
    assert not subset


def test_facade_search(populated):
    populated.conn.commit()
    bear = Bear(populated.path)
    hits = bear.search("milk")
    assert [r.note.title for r in hits] == ["Groceries"]
    fuzzy = bear.search("grocries", fuzzy=True)
    assert fuzzy and fuzzy[0].note.title == "Groceries" and fuzzy[0].score is not None


def test_facade_search_scope(populated):
    # The fixture ships "Old stuff" archived and "Gone" trashed.
    populated.conn.commit()
    bear = Bear(populated.path)
    assert not bear.search("Old stuff") and not bear.search("Gone")
    archived = bear.search("Old stuff", include_archived=True)
    assert [r.note.title for r in archived] == ["Old stuff"]
    trashed = bear.search("Gone", include_trashed=True)
    assert [r.note.title for r in trashed] == ["Gone"]
