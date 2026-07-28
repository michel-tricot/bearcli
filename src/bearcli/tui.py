"""Interactive note browser (Textual)."""

from __future__ import annotations

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Footer, Input, OptionList, Static
from textual.widgets.option_list import Option

from bearcli import actions
from bearcli.db import Note
from bearcli.search import SearchResult, naive_search, search_notes

HIGHLIGHT = "black on #dcb96a"


def _highlighted(value: str, query: str, base_style: str = "") -> Text:
    text = Text(value, style=base_style)
    words = [w for w in query.split() if len(w) >= 2]
    if words:
        text.highlight_words(words, HIGHLIGHT, case_sensitive=False)
    return text


class BrowseApp(App):
    """Type to filter, Tab to switch panes, Enter to open in Bear."""

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
        Binding("enter", "open_selected", "Open in Bear", show=True),
        Binding("tab", "focus_next", "Switch pane", show=True),
    ]

    def __init__(self, notes: list[Note], fuzzy: bool = False):
        super().__init__()
        self.notes = notes
        self.fuzzy = fuzzy
        self.search_query = ""
        self.shown: list[Note] = []

    def compose(self) -> ComposeResult:
        yield Input(placeholder="Search notes…", id="query")
        with Horizontal():
            yield OptionList(id="results")
            yield Static(id="preview-pane")
        yield Footer()

    def on_mount(self) -> None:
        self._show_results("", [SearchResult(note=n, snippet="") for n in self.notes])

    def on_input_changed(self, event: Input.Changed) -> None:
        self._filter(event.value)

    @work(exclusive=True, thread=True)
    def _filter(self, query: str) -> None:
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
        if event.option_id:
            actions.open_note(event.option_id)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.action_open_selected()

    def action_open_selected(self) -> None:
        results = self.query_one("#results", OptionList)
        if self.shown and results.highlighted is not None:
            actions.open_note(self.shown[results.highlighted].id)


def browse(notes: list[Note], fuzzy: bool = False) -> None:
    BrowseApp(notes, fuzzy=fuzzy).run()
