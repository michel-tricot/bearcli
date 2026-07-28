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
