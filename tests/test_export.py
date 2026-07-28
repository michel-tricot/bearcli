from bearcli.export import export_notes, slugify
from bearcli.secrets import redaction_map, scan_notes


def test_slugify():
    assert slugify("Hello, World!") == "hello-world"
    assert slugify("") == "untitled"
    assert len(slugify("x" * 500)) <= 60


def test_full_export_layout(populated, tmp_path):
    db = populated.open()
    dest = tmp_path / "out"
    result = export_notes(db, dest)
    assert result.written == 3  # active + archived; encrypted skipped, trashed excluded
    assert result.skipped_encrypted == 1
    dirs = {p.name for p in dest.iterdir() if p.is_dir()}
    assert "groceries-aaaa1111" in dirs and "old-stuff-cccc3333" in dirs
    assert (dest / "groceries-aaaa1111" / "README.md").read_text().startswith("---\nid: AAAA1111")
    assert (dest / "README.md").exists() and (dest / "index.json").exists()


def test_sync_skips_unchanged_and_removes_stale(populated, tmp_path):
    db = populated.open()
    dest = tmp_path / "out"
    export_notes(db, dest)
    result = export_notes(db, dest, sync=True)
    assert result.written == 0 and result.unchanged == 3

    # a stale managed dir is removed; an unmanaged dir is preserved
    stale = dest / "bygone-99999999"
    stale.mkdir()
    (stale / "README.md").write_text("---\nid: GONE\n---\nx\n")
    keep = dest / "mine"
    keep.mkdir()
    (keep / "README.md").write_text("hands off")
    result = export_notes(db, dest, sync=True)
    assert result.removed == 1
    assert not stale.exists() and keep.exists()


def test_attachments_copied_and_refs_rewritten(bear, tmp_path):
    bear.add_note(
        "AAAA0000-0000-0000-0000-00000000000C",
        "Pics",
        text="# Pics\n![](img%202.png)\n",
        attachments=(("ATT-2", "img 2.png", b"png"),),
    )
    db = bear.open()
    dest = tmp_path / "out"
    export_notes(db, dest)
    note_dir = dest / "pics-aaaa0000"
    assert (note_dir / "attachments" / "img 2.png").read_bytes() == b"png"
    assert "](attachments/img%202.png)" in (note_dir / "README.md").read_text()


def test_redaction_state_participates_in_sync(bear, tmp_path):
    bear.add_note("AAAA0000-0000-0000-0000-00000000000D", "Keys", text="# Keys\nkey AKIAIOSFODNN7EXAMPLE\n")
    db = bear.open()
    dest = tmp_path / "out"
    notes = db.list_notes(limit=None, include_archived=True, with_text=True)
    redactions = redaction_map(scan_notes(notes))

    export_notes(db, dest, redactions=redactions)
    readme = (dest / "keys-aaaa0000" / "README.md").read_text()
    assert "AKIAIOSFODNN7EXAMPLE" not in readme and "redacted: true" in readme

    # same mode: skip; mode off: rewrite with the real content
    assert export_notes(db, dest, sync=True, redactions=redactions).unchanged == 1
    assert export_notes(db, dest, sync=True).written == 1
    assert "AKIAIOSFODNN7EXAMPLE" in (dest / "keys-aaaa0000" / "README.md").read_text()


def test_index_content(populated, tmp_path):
    db = populated.open()
    dest = tmp_path / "out"
    export_notes(db, dest)
    index = (dest / "README.md").read_text()
    assert "## 📌 Pinned" in index and "## 🗄 Archived" in index
    assert index.index("Old stuff") > index.index("Groceries")  # archived at the bottom
    assert "`aaaa1111`" in index  # short ids
    assert "Vault" in index  # encrypted listed, unlinked
    assert "vault-" not in index
