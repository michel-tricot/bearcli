"""Interactive note browser and editor (Textual).

All writes go through Bear's x-callback-url API (never SQL) and are verified
by re-reading the database, mirroring the CLI's write commands.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import ModalScreen, Screen
from textual.widgets import Footer, Input, Label, OptionList, Static, TextArea
from textual.widgets.option_list import Option

from bearcli import actions
from bearcli.db import DEFAULT_DB_PATH, BearDB, Note
from bearcli.search import SearchResult, naive_search, search_notes

HIGHLIGHT = "black on #dcb96a"


def _highlighted(value: str, query: str, base_style: str = "") -> Text:
    text = Text(value, style=base_style)
    words = [w for w in query.split() if len(w) >= 2]
    if words:
        text.highlight_words(words, HIGHLIGHT, case_sensitive=False)
    return text


class EditScreen(Screen[str | None]):
    """Full-screen markdown editor; dismisses with the new text, or None."""

    BINDINGS = [
        Binding("ctrl+s", "save", "Save to Bear"),
        Binding("escape", "cancel", "Discard"),
    ]

    CSS = "TextArea { border: round $accent; margin: 0 1; }"

    def __init__(self, title: str, text: str):
        super().__init__()
        self.note_title = title
        self.initial_text = text

    def compose(self) -> ComposeResult:
        area = TextArea(self.initial_text, language="markdown", id="editor")
        area.border_title = self.note_title
        yield area
        yield Footer()

    def action_save(self) -> None:
        self.dismiss(self.query_one("#editor", TextArea).text)

    def action_cancel(self) -> None:
        self.dismiss(None)


class TagScreen(ModalScreen[str | None]):
    """Prompt for a tag name."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]
    CSS = """
    TagScreen { align: center middle; }
    #box { width: 50; height: auto; border: round $accent; padding: 1 2; background: $panel; }
    """

    def __init__(self, prompt: str):
        super().__init__()
        self.prompt = prompt

    def compose(self) -> ComposeResult:
        with Horizontal(id="box"):
            yield Label(self.prompt + " ")
            yield Input(id="tag-name")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class BrowseApp(App):
    """Browse, edit, and organize Bear notes from the terminal."""

    TITLE = "bearcli"

    CSS = """
    #query { dock: top; margin: 0 1; border: round $primary; }
    #query:focus { border: round $accent; }
    #results { width: 55%; border: round $panel-lighten-2; }
    #results:focus { border: round $accent; }
    #preview-pane { width: 45%; border: round $panel-lighten-2; padding: 0 1; }
    Horizontal { height: 1fr; margin: 0 1; }
    """

    BINDINGS = [
        Binding("escape", "quit", "Quit"),
        Binding("enter", "edit_selected", "Edit", show=True),
        Binding("n", "new_note", "New"),
        Binding("t", "add_tag", "Tag"),
        Binding("T", "remove_tag", "Untag", show=False),
        Binding("o", "open_in_bear", "Open in Bear"),
        Binding("tab", "focus_next", "Switch pane", show=False),
    ]

    def __init__(self, notes: list[Note], fuzzy: bool = False, db_path: Path = DEFAULT_DB_PATH):
        super().__init__()
        self.notes = notes
        self.fuzzy = fuzzy
        self.db_path = db_path
        self.search_query = ""
        self.shown: list[Note] = []

    # ── layout ────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Input(placeholder="Search notes…", id="query")
        with Horizontal():
            yield OptionList(id="results")
            yield Static(id="preview-pane")
        yield Footer()

    def get_system_commands(self, screen: Screen) -> Iterable[SystemCommand]:
        yield from super().get_system_commands(screen)
        yield SystemCommand("Open in Bear", "Open the selected note in the Bear app", self.action_open_in_bear)
        yield SystemCommand("New note", "Create a note in Bear", self.action_new_note)
        yield SystemCommand("Add tag", "Tag the selected note", self.action_add_tag)
        yield SystemCommand("Remove tag", "Untag the selected note", self.action_remove_tag)
        yield SystemCommand("Archive note", "Archive the selected note", lambda: self._file_away("archive"))
        yield SystemCommand("Trash note", "Move the selected note to Bear's trash", lambda: self._file_away("trash"))

    # ── searching / listing ──────────────────────────────────────────────

    def on_mount(self) -> None:
        self._show_results("", [SearchResult(note=n, snippet="") for n in self.notes])

    def on_input_changed(self, event: Input.Changed) -> None:
        self._run_filter(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.query_one("#results", OptionList).focus()

    @work(exclusive=True, thread=True)
    def _run_filter(self, query: str) -> None:
        if not query.strip():
            results = [SearchResult(note=n, snippet="") for n in self.notes]
        elif self.fuzzy:
            results = search_notes(self.notes, query)
        else:
            results = naive_search(self.notes, query)
        self.call_from_thread(self._show_results, query, results)

    def _show_results(self, query: str, results: list[SearchResult]) -> None:
        self.search_query = query
        self.shown = [r.note for r in results]
        options = []
        for note in self.shown:
            date = note.modified.strftime("%Y-%m-%d") if note.modified else " " * 10
            label = Text.assemble((date, "dim"), "  ")
            label.append(_highlighted(note.title, query, "bold"))
            if note.tags:
                label.append("  ")
                label.append(_highlighted(" ".join(f"#{t}" for t in note.tags), query, "dim cyan"))
            options.append(Option(label, id=note.id))
        result_list = self.query_one("#results", OptionList)
        result_list.clear_options()
        result_list.add_options(options)
        result_list.border_title = f"{len(self.shown)} / {len(self.notes)} notes"
        if self.shown:
            result_list.highlighted = 0
        else:
            self.query_one("#preview-pane", Static).update("")

    def _selected(self) -> Note | None:
        results = self.query_one("#results", OptionList)
        if self.shown and results.highlighted is not None:
            return self.shown[results.highlighted]
        return None

    def _preview(self, note: Note) -> Text:
        status = ", ".join(
            s for s, on in (("pinned", note.pinned), ("archived", note.archived), ("encrypted", note.encrypted)) if on
        )
        meta = Text()
        meta.append(note.title + "\n", "bold")
        meta.append(f"id       {note.id}\n", "dim")
        if note.created:
            meta.append(f"created  {note.created.strftime('%Y-%m-%d %H:%M')}\n", "dim")
        if note.modified:
            meta.append(f"modified {note.modified.strftime('%Y-%m-%d %H:%M')}\n", "dim")
        meta.append(f"words    {len((note.text or '').split())}\n", "dim")
        if note.tags:
            meta.append(f"tags     {', '.join(note.tags)}\n", "dim")
        if status:
            meta.append(f"status   {status}\n", "dim")
        meta.append("─" * 30 + "\n", "dim")
        body = "\n".join((note.text or "").splitlines()[:60])
        meta.append(_highlighted(body, self.search_query))
        return meta

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        note = next((n for n in self.shown if n.id == event.option_id), None)
        if note:
            self.query_one("#preview-pane", Static).update(self._preview(note))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.action_edit_selected()

    # ── actions ──────────────────────────────────────────────────────────

    def action_open_in_bear(self) -> None:
        if note := self._selected():
            actions.open_note(note.id)

    def action_edit_selected(self) -> None:
        note = self._selected()
        if note is None:
            return
        if note.text is None:
            self.notify("Encrypted notes can't be edited here", severity="warning")
            return

        def on_done(new_text: str | None) -> None:
            if new_text is not None and new_text != note.text:
                self._save_note(note, new_text)

        self.push_screen(EditScreen(note.title, note.text), on_done)

    def action_new_note(self) -> None:
        def on_done(new_text: str | None) -> None:
            if new_text and new_text.strip():
                self._create_note(new_text)

        self.push_screen(EditScreen("New note", "# \n"), on_done)

    def action_add_tag(self) -> None:
        if note := self._selected():

            def on_done(tag: str | None) -> None:
                if tag:
                    self._tag_note(note, tag, add=True)

            self.push_screen(TagScreen("Add tag:"), on_done)

    def action_remove_tag(self) -> None:
        if note := self._selected():

            def on_done(tag: str | None) -> None:
                if tag:
                    self._tag_note(note, tag, add=False)

            self.push_screen(TagScreen("Remove tag:"), on_done)

    # ── write workers (fire x-callback, verify via db, refresh UI) ───────

    @work(thread=True)
    def _save_note(self, note: Note, new_text: str) -> None:
        actions.add_text(note.id, new_text, mode="replace_all")
        self._finish_write(note.id, lambda db: self._modified_after(db, note), "Saved to Bear", "Save")

    @work(thread=True)
    def _create_note(self, text: str) -> None:
        head, _, body = text.partition("\n")
        title = head.lstrip("# ").strip() or "Untitled"
        started = datetime.now(UTC)
        actions.create_note(title, text=body or None)
        db = BearDB(self.db_path)
        try:

            def find(db: BearDB = db) -> Note | None:
                return next(
                    (
                        n
                        for n in db.list_notes(limit=10)
                        if n.title == title and n.created and n.created >= started - timedelta(seconds=5)
                    ),
                    None,
                )

            if actions.wait_for(lambda: find() is not None) and (created := find()) is not None:
                fresh = db.get_note(created.id)
                if fresh:
                    self.notes.insert(0, fresh)
                    self.call_from_thread(self._run_filter, self.search_query)
                    self.call_from_thread(self.notify, f"Created {fresh.title!r}")
            else:
                self.call_from_thread(self.notify, "Create failed - is Bear able to run?", severity="error")
        finally:
            db.close()

    @work(thread=True)
    def _tag_note(self, note: Note, tag: str, add: bool) -> None:
        if add:
            marker = f"#{tag}#" if any(not (c.isalnum() or c in "/-_") for c in tag) else f"#{tag}"
            actions.add_text(note.id, marker, mode="append")
            self._finish_write(note.id, lambda db: self._has_tag(db, note.id, tag), f"Tagged with {tag!r}", "Tag")
        else:
            if note.text is None or tag.lower() not in (t.lower() for t in note.tags):
                self.call_from_thread(self.notify, f"Note has no tag {tag!r}", severity="warning")
                return
            import re

            escaped = re.escape(tag)
            new_text = re.sub(rf"[ \t]?#{escaped}#", "", note.text, flags=re.IGNORECASE)
            new_text = re.sub(rf"[ \t]?#{escaped}(?![\w/-])", "", new_text, flags=re.IGNORECASE)
            actions.add_text(note.id, new_text.rstrip("\n") + "\n", mode="replace_all")
            self._finish_write(note.id, lambda db: not self._has_tag(db, note.id, tag), f"Removed tag {tag!r}", "Untag")

    def _file_away(self, operation: str) -> None:
        if note := self._selected():
            self._file_away_worker(note, operation)

    @work(thread=True)
    def _file_away_worker(self, note: Note, operation: str) -> None:
        if operation == "trash":
            actions.trash_note(note.id)
            ok = self._wait(lambda db: (n := db.get_note(note.id)) is not None and n.trashed)
        else:
            actions.archive_note(note.id)
            ok = self._wait(lambda db: (n := db.get_note(note.id)) is not None and n.archived)
        if ok:
            self.notes = [n for n in self.notes if n.id != note.id]
            self.call_from_thread(self._run_filter, self.search_query)
            self.call_from_thread(self.notify, f"{operation.capitalize()}ed {note.title!r}")
        else:
            self.call_from_thread(self.notify, f"{operation} failed - is Bear able to run?", severity="error")

    # ── write plumbing ───────────────────────────────────────────────────

    @staticmethod
    def _modified_after(db: BearDB, note: Note) -> bool:
        fresh = db.get_note(note.id)
        return (
            fresh is not None
            and fresh.modified is not None
            and (note.modified is None or fresh.modified > note.modified)
        )

    @staticmethod
    def _has_tag(db: BearDB, note_id: str, tag: str) -> bool:
        fresh = db.get_note(note_id)
        return fresh is not None and tag.lower() in (t.lower() for t in fresh.tags)

    def _wait(self, predicate) -> bool:
        db = BearDB(self.db_path)
        try:
            return actions.wait_for(lambda: predicate(db))
        finally:
            db.close()

    def _finish_write(self, note_id: str, predicate, ok_message: str, operation: str) -> None:
        if self._wait(predicate):
            db = BearDB(self.db_path)
            try:
                fresh = db.get_note(note_id)
            finally:
                db.close()
            if fresh:
                self.notes = [fresh if n.id == note_id else n for n in self.notes]
            self.call_from_thread(self._run_filter, self.search_query)
            self.call_from_thread(self.notify, ok_message)
        else:
            self.call_from_thread(self.notify, f"{operation} failed - is Bear able to run?", severity="error")


def browse(notes: list[Note], fuzzy: bool = False, db_path: Path = DEFAULT_DB_PATH) -> None:
    BrowseApp(notes, fuzzy=fuzzy, db_path=db_path).run()
