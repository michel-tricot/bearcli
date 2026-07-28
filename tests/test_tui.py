import asyncio

from textual.widgets import Input, OptionList, TextArea

from bearcli.db import Note
from bearcli.tui import BearUI, TagScreen


def make_note(note_id: str, title: str, tags: tuple[str, ...] = ()) -> Note:
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
        text=f"# {title}\nbody\n",
    )


NOTES = [make_note("N1", "Alpha", ("work",)), make_note("N2", "Beta", ("home",))]


def run(coro):
    asyncio.run(coro)


def test_startup_focus_and_escape_layers():
    async def probe():
        app = BearUI(list(NOTES))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            assert isinstance(app.focused, OptionList)
            await pilot.press("slash")
            assert isinstance(app.focused, Input)
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.focused, OptionList) and app.is_running
            await pilot.press("escape")
            await pilot.pause()
            assert not app.is_running

    run(probe())


def test_create_seeds_cursor_and_edit_mode_gates_bindings():
    async def probe():
        app = BearUI(list(NOTES))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("c")
            await pilot.pause()
            editor = app.query_one("#editor", TextArea)
            assert str(editor.styles.display) == "block"
            assert editor.cursor_location == (0, 2)
            assert not app.check_action("new_note", ())
            assert app.check_action("save_edit", ())
            await pilot.press("escape")
            await pilot.pause()
            assert str(editor.styles.display) == "none"
            assert app.check_action("new_note", ())

    run(probe())


def test_filter_and_highlight():
    async def probe():
        app = BearUI(list(NOTES))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("slash", *"alpha")
            await pilot.pause(0.4)
            results = app.query_one("#results", OptionList)
            assert results.option_count == 1

    run(probe())


def test_tag_modal_suggestions():
    async def probe():
        app = BearUI(list(NOTES))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("t")
            await pilot.pause()
            assert isinstance(app.screen, TagScreen)
            suggestions = app.screen.query_one("#suggestions", OptionList)
            assert suggestions.option_count == 2  # work + home
            await pilot.press("w")
            await pilot.pause()
            assert suggestions.option_count == 1
            await pilot.press("escape")

    run(probe())


def test_tag_modal_typing_does_not_filter_notes():
    async def probe():
        app = BearUI(list(NOTES))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            results = app.query_one("#results", OptionList)
            await pilot.press("t")
            await pilot.pause()
            await pilot.press(*"work")
            await pilot.pause(0.4)
            assert results.option_count == len(NOTES)  # note list untouched
            await pilot.press("escape")

    run(probe())


def test_secret_indicator(populated):
    populated.add_note("SEC00000-0000-0000-0000-000000000009", "Keys", text="# Keys\nkey AKIAIOSFODNN7EXAMPLE\n")
    db = populated.open()
    notes = db.list_notes(limit=None, with_text=True)

    async def probe():
        app = BearUI(notes, db_path=populated.path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.8)
            assert app.secret_counts.get("SEC00000-0000-0000-0000-000000000009", 0) >= 1
            option_texts = [
                str(app.query_one("#results", OptionList).get_option_at_index(i).prompt) for i in range(len(notes))
            ]
            assert any("🔑" in t and "Keys" in t for t in option_texts)

    run(probe())


def test_rehydrate_picks_up_new_notes(populated):
    db = populated.open()
    notes = db.list_notes(limit=None, with_text=True)

    async def probe():
        app = BearUI(notes, db_path=populated.path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            populated.add_note("NEW00000-0000-0000-0000-000000000010", "Fresh")
            populated.conn.commit()
            app._rehydrate()
            await pilot.pause(0.8)
            assert any(n.title == "Fresh" for n in app.notes)
            results = app.query_one("#results", OptionList)
            assert results.option_count == len(app.notes)

    run(probe())
