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
            assert len(app.secret_values.get("SEC00000-0000-0000-0000-000000000009", [])) >= 1
            from rich.console import Console

            console = Console(width=100)
            option_texts = []
            for i in range(len(notes)):
                with console.capture() as capture:
                    console.print(app.query_one("#results", OptionList).get_option_at_index(i).prompt)
                option_texts.append(capture.get())
            assert any("🚨" in t and "Keys" in t for t in option_texts)

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


def test_refresh_note_updates_single_entry(populated):
    db = populated.open()
    notes = db.list_notes(limit=None, with_text=True)

    async def probe():
        app = BearUI(notes, db_path=populated.path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            populated.conn.execute(
                "UPDATE ZSFNOTE SET ZTEXT = '# Groceries\nkey AKIAIOSFODNN7EXAMPLE\n' "
                "WHERE ZUNIQUEIDENTIFIER LIKE 'AAAA1111%'"
            )
            populated.conn.commit()
            app._refresh_note("AAAA1111-0000-0000-0000-000000000001")
            await pilot.pause(0.8)
            fresh = next(n for n in app.notes if n.id.startswith("AAAA1111"))
            assert "AKIA" in fresh.text
            assert len(app.secret_values.get(fresh.id, [])) >= 1

    run(probe())


def test_encrypted_note_preview_message(populated):
    db = populated.open()
    notes = db.list_notes(limit=None, with_text=True)
    app = BearUI(notes)
    vault = next(n for n in notes if n.title == "Vault")
    preview = str(app._preview(vault))
    assert "encrypted" in preview.lower() and "directly in Bear" in preview


def test_pending_edit_selects_and_opens_editor():
    async def probe():
        app = BearUI(list(NOTES))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._select_id = "N2"
            app._pending_edit_id = "N2"
            app._run_filter(app.search_query)
            await pilot.pause(0.5)
            results = app.query_one("#results", OptionList)
            assert results.highlighted == 1  # N2 selected
            editor = app.query_one("#editor", TextArea)
            assert str(editor.styles.display) == "block"
            assert app.editing is not None and app.editing.id == "N2"

    run(probe())


def test_removal_selects_neighbour():
    async def probe():
        notes = [make_note(f"N{i}", f"Note {i}") for i in range(1, 5)]
        app = BearUI(notes)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            results = app.query_one("#results", OptionList)
            results.highlighted = 1  # "Note 2"
            # simulate the post-removal path the worker takes
            removed = app.shown[1]
            index = 1
            neighbour = app.shown[index + 1]
            app._select_id = neighbour.id
            app.notes = [n for n in app.notes if n.id != removed.id]
            app._run_filter(app.search_query)
            await pilot.pause(0.5)
            assert results.highlighted == 1  # now "Note 3", in the removed slot
            assert app.shown[results.highlighted].id == "N3"

    run(probe())


def test_view_switching(populated):
    db = populated.open()
    notes = db.list_notes(limit=None, with_text=True)

    async def probe():
        app = BearUI(notes, db_path=populated.path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause(0.8)
            assert {n.title for n in app.notes} == {"Gone"}
            await pilot.press("2")
            await pilot.pause(0.8)
            assert {n.title for n in app.notes} == {"Old stuff"}
            await pilot.press("1")
            await pilot.pause(0.8)
            assert "Groceries" in {n.title for n in app.notes}

    run(probe())


def test_help_overlay():
    async def probe():
        app = BearUI(list(NOTES))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("question_mark")
            await pilot.pause()
            from bearcli.tui import HelpScreen

            assert isinstance(app.screen, HelpScreen)
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, HelpScreen)

    run(probe())


def test_async_initial_load_with_spinner(populated):
    populated.open().close()

    async def probe():
        app = BearUI(db_path=populated.path)
        async with app.run_test(size=(120, 40)) as pilot:
            results = app.query_one("#results", OptionList)
            await pilot.pause(1.0)
            assert results.loading is False
            assert len(app.notes) >= 3  # loaded by the worker, not the caller
            assert app.focused is results  # focus lands on the list once loaded

    run(probe())


def test_preview_pane_focusable():
    async def probe():
        app = BearUI(list(NOTES))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("tab")  # results -> preview scroll
            assert app.focused is not None and app.focused.id == "preview-pane"

    run(probe())
