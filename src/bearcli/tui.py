"""Interactive note browser (Textual)."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from bearcli import actions
from bearcli.db import Note
from bearcli.search import naive_search, search_notes

MAX_RESULTS = 50


class BrowseApp(App):
    """Type to filter, arrows to move, Enter to open in Bear, Esc to quit."""

    CSS = """
    #query { dock: top; }
    #status { dock: bottom; height: 1; color: $text-muted; padding: 0 1; }
    #results { height: 1fr; }
    #preview { width: 45%; border-left: solid $surface; padding: 0 1; color: $text-muted; }
    """
    BINDINGS = [("escape", "quit", "Quit")]

    def __init__(self, notes: list[Note], fuzzy: bool = False):
        super().__init__()
        self.notes = notes
        self.fuzzy = fuzzy
        self.shown: list[Note] = []

    def compose(self) -> ComposeResult:
        yield Input(placeholder="Search notes…", id="query")
        with Horizontal():
            yield OptionList(id="results")
            yield Static(id="preview")
        yield Static(id="status")

    def on_mount(self) -> None:
        self._refresh("")

    def on_input_changed(self, event: Input.Changed) -> None:
        self._refresh(event.value)

    def _refresh(self, query: str) -> None:
        if not query.strip():
            self.shown = self.notes[:MAX_RESULTS]
        elif self.fuzzy:
            self.shown = [r.note for r in search_notes(self.notes, query)[:MAX_RESULTS]]
        else:
            self.shown = [r.note for r in naive_search(self.notes, query)[:MAX_RESULTS]]

        results = self.query_one("#results", OptionList)
        results.clear_options()
        for note in self.shown:
            date = note.modified.strftime("%Y-%m-%d") if note.modified else "          "
            tags = f"  #{' #'.join(note.tags)}" if note.tags else ""
            results.add_option(Option(f"{date}  {note.title}{tags}", id=note.id))
        if self.shown:
            results.highlighted = 0
        self.query_one("#status", Static).update(
            f"{len(self.shown)} shown / {len(self.notes)} notes · Enter: open in Bear · Esc: quit"
        )

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        note = next((n for n in self.shown if n.id == event.option_id), None)
        preview = "\n".join((note.text or "").splitlines()[:40]) if note else ""
        self.query_one("#preview", Static).update(preview)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_id:
            actions.open_note(event.option_id)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        results = self.query_one("#results", OptionList)
        if self.shown and results.highlighted is not None:
            actions.open_note(self.shown[results.highlighted].id)


def browse(notes: list[Note], fuzzy: bool = False) -> None:
    BrowseApp(notes, fuzzy=fuzzy).run()
