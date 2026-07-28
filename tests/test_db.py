import pytest

from bearkit.db import AmbiguousNoteId


def test_list_excludes_trashed_archived_deleted_by_default(populated):
    db = populated.open()
    titles = {n.title for n in db.list_notes()}
    assert titles == {"Groceries", "Project plan", "Vault"}


def test_list_include_flags(populated):
    db = populated.open()
    titles = {n.title for n in db.list_notes(include_trashed=True, include_archived=True)}
    assert titles == {"Groceries", "Project plan", "Vault", "Old stuff", "Gone"}
    assert "Ghost" not in titles  # permanently deleted rows never appear


def test_only_filters(populated):
    db = populated.open()
    assert [n.title for n in db.list_notes(only="pinned")] == ["Project plan"]
    assert [n.title for n in db.list_notes(only="archived")] == ["Old stuff"]
    assert [n.title for n in db.list_notes(only="trashed")] == ["Gone"]


def test_only_trashed_includes_archived_trashed(bear):
    bear.add_note("AAAA0000-0000-0000-0000-00000000000A", "Both", archived=True, trashed=True)
    db = bear.open()
    assert [n.title for n in db.list_notes(only="trashed")] == ["Both"]


def test_tag_filter_includes_nested(populated):
    db = populated.open()
    assert [n.title for n in db.list_notes(tag="work")] == ["Project plan"]
    assert [n.title for n in db.list_notes(tag="work/ideas")] == ["Project plan"]
    assert db.list_notes(tag="wor") == []  # no substring matching


def test_get_note_exact_and_prefix(populated):
    db = populated.open()
    assert db.get_note("AAAA1111-0000-0000-0000-000000000001").title == "Groceries"
    assert db.get_note("aaaa1111").title == "Groceries"  # case-insensitive prefix
    assert db.get_note("ZZZZ9999") is None
    assert db.get_note("AAA") is None  # below the minimum prefix length


def test_get_note_ambiguous_prefix(bear):
    bear.add_note("ABCD0001-0000-0000-0000-000000000001", "One")
    bear.add_note("ABCD0002-0000-0000-0000-000000000002", "Two")
    db = bear.open()
    with pytest.raises(AmbiguousNoteId) as exc:
        db.get_note("ABCD")
    assert {title for _, title in exc.value.matches} == {"One", "Two"}


def test_encrypted_note_has_no_text(populated):
    db = populated.open()
    note = db.get_note("EEEE5555")
    assert note.encrypted and note.text is None


def test_list_tags_counts_and_empty(populated):
    db = populated.open()
    assert dict(db.list_tags()) == {"home": 1, "work": 1, "work/ideas": 1}


def test_attachments_resolve_on_disk(bear):
    bear.add_note(
        "AAAA0000-0000-0000-0000-00000000000B",
        "With file",
        attachments=(("ATT-1", "pic 2.png", b"12345"),),
    )
    db = bear.open()
    note = db.get_note("AAAA0000")
    (att,) = note.attachments
    assert att.filename == "pic 2.png" and att.size == 5 and att.exists
