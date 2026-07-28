from bearcli.db import Note
from bearcli.search import naive_search, search_notes


def make_note(note_id: str, title: str, text: str = "", tags: tuple[str, ...] = ()) -> Note:
    return Note(
        id=note_id,
        title=title,
        created=None,
        modified=None,
        pinned=False,
        encrypted=False,
        archived=False,
        trashed=False,
        tags=list(tags),
        text=text or f"# {title}\n",
    )


NOTES = [
    make_note("N1", "Field notes", "# Field notes\nquarterly planning doc\n"),
    make_note("N2", "Bindi", "# Bindi\nshort note\n"),
    make_note("N3", "Groceries", "# Groceries\nmilk, eggs, BREAD\n", tags=("home",)),
]


def test_naive_is_case_insensitive_and_ordered():
    results = naive_search(NOTES, "bread")
    assert [r.note.id for r in results] == ["N3"]
    assert results[0].score is None


def test_naive_matches_tags():
    assert [r.note.id for r in naive_search(NOTES, "home")] == ["N3"]


def test_fuzzy_typo_matches_title():
    results = search_notes(NOTES, "fieldnotse")
    assert results and results[0].note.id == "N1"


def test_fuzzy_body_typo_with_snippet():
    results = search_notes(NOTES, "quarterly planing")
    assert results[0].note.id == "N1"
    assert "quarterly planning" in results[0].snippet


def test_short_titles_do_not_score_high_against_long_queries():
    results = search_notes(NOTES, "completely unrelated long query text")
    assert all(r.note.id != "N2" for r in results)
