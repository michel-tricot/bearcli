"""Interactive note browser and editor (Textual).

All writes go through Bear's x-callback-url API (never SQL) and are verified
by re-reading the database, mirroring the CLI's write commands.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path

from rich.console import Group, RenderableType
from rich.markdown import Heading, Markdown
from rich.segment import Segment
from rich.style import Style
from rich.table import Table as RichTable
from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Label, LoadingIndicator, OptionList, Static, TextArea
from textual.widgets.option_list import Option

from bearlib import actions, ops
from bearlib.db import DEFAULT_DB_PATH, BearDB, Note, pretty_status
from bearlib.search import SearchResult, naive_search, search_notes
from bearlib.secrets import redaction_map, scan_notes

HIGHLIGHT = "black on #dcb96a"
SECRET_STYLE = "black on #ff9999"


class _LeftHeading(Heading):
    """Left-aligned headings; Rich centers them (and boxes h1) by default."""

    def __rich_console__(self, console, options):
        text = self.text
        text.justify = "left"
        yield text


class _LeftMarkdown(Markdown):
    elements = {**Markdown.elements, "heading_open": _LeftHeading}


class _StyledMatches:
    """Restyle substring matches inside an already-rendered renderable.

    Rich's Markdown is a renderable, not a Text, so search-term and secret
    highlighting cannot be applied up front; this wrapper re-styles matching
    runs in the rendered segments instead.
    """

    def __init__(self, renderable: RenderableType, rules: list[tuple[str, str, bool]]):
        self.renderable = renderable
        self.rules = [(needle, Style.parse(style), cs) for needle, style, cs in rules if needle]

    def __rich_console__(self, console, options):
        for line in console.render_lines(self.renderable, options, pad=False):
            text = "".join(seg.text for seg in line)
            overrides: list[Style | None] = [None] * len(text)
            for needle, style, case_sensitive in self.rules:
                hay = text if case_sensitive else text.lower()
                nd = needle if case_sensitive else needle.lower()
                start = 0
                while (found := hay.find(nd, start)) != -1:
                    overrides[found : found + len(nd)] = [style] * len(nd)
                    start = found + len(nd)
            pos = 0
            for seg in line:
                if seg.control or not seg.text:
                    yield seg
                    continue
                run_start = 0
                t = seg.text
                for k in range(1, len(t) + 1):
                    if k == len(t) or overrides[pos + k] is not overrides[pos + run_start]:
                        override = overrides[pos + run_start]
                        style = seg.style
                        if override is not None:
                            style = style + override if style else override
                        yield Segment(t[run_start:k], style)
                        run_start = k
                pos += len(t)
            yield Segment.line()


def _highlighted(value: str, query: str, base_style: str = "") -> Text:
    text = Text(value, style=base_style)
    words = [w for w in query.split() if len(w) >= 2]
    if words:
        text.highlight_words(words, HIGHLIGHT, case_sensitive=False)
    return text


class SecretTextArea(TextArea):
    """TextArea that renders detected secret values on a light red background."""

    async def _on_key(self, event: events.Key) -> None:
        # With tab_behavior="indent", TextArea claims escape as its
        # focus-escape key (in _on_key, not via bindings); route it to the
        # app's editor-exit instead.
        if event.key == "escape":
            event.stop()
            event.prevent_default()
            app = self.app
            assert isinstance(app, BearUI)
            app.action_back_or_quit()
            return
        await super()._on_key(event)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.secret_values: list[str] = []

    def get_line(self, line_index: int) -> Text:
        line = super().get_line(line_index)
        if self.secret_values:
            line.highlight_words(self.secret_values, SECRET_STYLE, case_sensitive=True)
        return line


class _TagSuggestions(OptionList):
    """Suggestion list that hands focus back to the input instead of wrapping."""

    def action_cursor_up(self) -> None:
        if self.highlighted in (None, 0):
            self.screen.query_one("#tag-name", Input).focus()
        else:
            super().action_cursor_up()

    def action_cursor_down(self) -> None:
        if self.option_count and self.highlighted == self.option_count - 1:
            return
        super().action_cursor_down()


class ConfirmDiscard(ModalScreen[str | None]):
    """Confirmation shown when leaving the editor with unsaved changes."""

    BINDINGS = [
        Binding("s", "answer('save')", "Save"),
        Binding("y", "answer('discard')", "Discard"),
        Binding("n,escape", "answer('keep')", "Keep editing"),
    ]
    CSS = """
    ConfirmDiscard { align: center middle; }
    #confirm-box {
        width: 52; height: auto; padding: 1 2;
        border: round $warning; background: $panel;
    }
    #confirm-keys { color: $text-muted; margin-top: 1; }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Label("You have unsaved changes.")
            yield Label("[b]s[/b] save   [b]y[/b] discard   [b]n[/b]/[b]esc[/b] keep editing", id="confirm-keys")

    def action_answer(self, answer: str) -> None:
        self.dismiss(answer)


class TagScreen(ModalScreen[str | None]):
    """Tag prompt with autocompletion over known tags."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]
    CSS = """
    TagScreen { align: center middle; }
    #box {
        width: 56; height: auto; padding: 1 2;
        border: round $accent; background: $panel;
    }
    #tag-prompt { color: $text-muted; margin-bottom: 1; }
    #suggestions { height: 8; margin-top: 1; }
    """

    def __init__(self, prompt: str, choices: list[str]):
        super().__init__()
        self.prompt = prompt
        self.choices = choices

    def compose(self) -> ComposeResult:
        with Vertical(id="box"):
            yield Label(self.prompt, id="tag-prompt")
            yield Input(placeholder="tag name…", id="tag-name")
            yield _TagSuggestions(id="suggestions")

    def on_mount(self) -> None:
        self._suggest("")

    def _suggest(self, value: str) -> None:
        matches = [t for t in self.choices if value.lower() in t.lower()][:8]
        suggestions = self.query_one("#suggestions", OptionList)
        suggestions.clear_options()
        suggestions.add_options([Option(t, id=t) for t in matches])

    def on_input_changed(self, event: Input.Changed) -> None:
        self._suggest(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)

    def on_key(self, event: events.Key) -> None:
        if event.key == "down" and self.query_one("#tag-name", Input).has_focus:
            suggestions = self.query_one("#suggestions", OptionList)
            if suggestions.option_count:
                event.stop()
                suggestions.highlighted = 0
                suggestions.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option_id)

    def action_cancel(self) -> None:
        self.dismiss(None)


BROWSE_KEYS_BEAR = [
    ("enter/e", "Edit"),
    ("n/c", "New"),
    ("t", "Tag"),
    ("o", "Open in Bear"),
    ("a", "Archive"),
    ("d", "Trash"),
]
BROWSE_KEYS_TUI = [
    ("/", "Search"),
    ("1/2/3", "View"),
    ("tab", "Pane"),
    ("?", "Help"),
    ("esc", "Quit"),
]
EDIT_KEYS_BEAR = [("ctrl+s", "Save to Bear")]
EDIT_KEYS_TUI = [("tab", "Indent"), ("esc", "Discard")]


def _keybar_markup(keys: list[tuple[str, str]]) -> str:
    return "  ".join(f"[bold]{key}[/bold] [dim]{label}[/dim]" for key, label in keys)


class KeyBar(Horizontal):
    """Bottom key bar: Bear actions on the left, TUI controls on the right."""

    DEFAULT_CSS = """
    KeyBar { dock: bottom; height: 1; background: $panel; padding: 0 1; }
    KeyBar > #kb-left { width: auto; }
    KeyBar > #kb-right { width: 1fr; text-align: right; }
    """

    def compose(self) -> ComposeResult:
        yield Static(id="kb-left")
        yield Static(id="kb-right")

    def show(self, bear: list[tuple[str, str]], tui: list[tuple[str, str]]) -> None:
        self.query_one("#kb-left", Static).update(_keybar_markup(bear))
        self.query_one("#kb-right", Static).update(_keybar_markup(tui))


HELP_ROWS = [
    ("Navigate", ""),
    ("↑ or k", "previous note"),
    ("↓ or j", "next note"),
    ("/", "focus search"),
    ("tab", "switch pane"),
    ("1 / 2 / 3", "notes / archive / trash view"),
    ("Act on the selected note", ""),
    ("enter or e", "edit in the right panel"),
    ("n or c", "new note"),
    ("t / T", "add / remove a tag"),
    ("o", "open in Bear"),
    ("a", "archive"),
    ("d", "move to trash"),
    ("r", "reload from Bear"),
    ("While editing", ""),
    ("ctrl+s", "save to Bear"),
    ("esc", "discard changes"),
]


class HelpScreen(ModalScreen[None]):
    """Key map overlay."""

    BINDINGS = [Binding("escape,question_mark", "close", "Close")]
    CSS = """
    HelpScreen { align: center middle; }
    #help-box {
        width: 62; height: auto; padding: 1 2;
        border: round $accent; background: $panel;
    }
    """

    def compose(self) -> ComposeResult:
        table = RichTable.grid(padding=(0, 2))
        table.add_column(style="bold", no_wrap=True)
        table.add_column()
        for key, description in HELP_ROWS:
            if not description:
                if table.row_count:
                    table.add_row("", "")  # blank line between sections
                table.add_row(Text(key, "dim italic"), "")
            else:
                table.add_row(key, description)
        yield Static(table, id="help-box")

    def action_close(self) -> None:
        self.dismiss(None)


class BearUI(App):
    """Browse, edit, and organize Bear notes from the terminal."""

    TITLE = "bearcli"
    ENABLE_COMMAND_PALETTE = False

    CSS = """
    #query { dock: top; margin: 0 1; border: round $primary; }
    #query:focus { border: round $accent; }
    #list-pane { width: 34%; border: round $panel-lighten-2; }
    #list-pane:focus-within { border: round $accent; }
    #results { height: 1fr; border: none; background: transparent; }
    #list-pane LoadingIndicator { height: 1fr; }
    #side { width: 66%; }
    #preview-pane { height: 1fr; border: round $panel-lighten-2; padding: 0 1; }
    #preview-pane:focus { border: round $accent; }
    #editor { height: 1fr; border: round $accent; display: none; }
    #main { height: 1fr; margin: 0 1; }
    """

    BINDINGS = [
        # Bear actions (left of the footer)
        Binding("e", "edit_selected", "Edit", key_display="enter/e"),
        Binding("enter", "edit_selected", "Edit", show=False),
        Binding("n", "new_note", "New", key_display="n/c"),
        Binding("c", "new_note", "New", show=False),
        Binding("t", "add_tag", "Tag"),
        Binding("T", "remove_tag", "Untag", show=False),
        Binding("o", "open_in_bear", "Open in Bear"),
        Binding("a", "archive_note", "Archive"),
        Binding("d", "trash_note", "Trash"),
        Binding("r", "refresh", "Refresh", show=False),
        Binding("j", "cursor_down", "Next note", show=False),
        Binding("k", "cursor_up", "Previous note", show=False),
        Binding("ctrl+s", "save_edit", "Save to Bear"),
        # TUI controls (right of the footer)
        Binding("/", "focus_search", "Search"),
        Binding("1", "switch_view('notes')", "View", key_display="1/2/3"),
        Binding("2", "switch_view('archive')", "Archive view", show=False),
        Binding("3", "switch_view('trash')", "Trash view", show=False),
        Binding("tab", "focus_next", "Switch pane", priority=True),
        Binding("question_mark", "help", "Help", key_display="?"),
        Binding("escape", "back_or_quit", "Quit"),
    ]

    def __init__(
        self,
        notes: list[Note] | None = None,
        fuzzy: bool = False,
        db_path: Path = DEFAULT_DB_PATH,
        tag_filter: str | None = None,
    ):
        super().__init__()
        self._preloaded = notes is not None
        self._focus_list_after_load = False
        self._editor_original = ""
        self.notes = notes or []
        self.fuzzy = fuzzy
        self.db_path = db_path
        self.tag_filter = tag_filter
        self.view = "notes"  # notes | archive | trash
        self.search_query = ""
        self.shown: list[Note] = []
        self.editing: Note | None = None
        self.creating = False
        self.secret_values: dict[str, dict[str, str]] = {}  # note id -> {secret value: rule}, as built for redaction
        self._select_id: str | None = None
        self._pending_edit_id: str | None = None

    # ── layout ────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Input(placeholder="Search notes…", id="query")
        with Horizontal(id="main"):
            with Vertical(id="list-pane"):
                yield OptionList(id="results")
            with Vertical(id="side"):
                with VerticalScroll(id="preview-pane"):
                    yield Static(id="preview-content")
                yield SecretTextArea(language="markdown", id="editor", tab_behavior="indent")
        yield KeyBar()

    @property
    def edit_mode(self) -> bool:
        return self.editing is not None or self.creating

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool:
        browse_only = {
            "edit_selected",
            "new_note",
            "add_tag",
            "remove_tag",
            "open_in_bear",
            "archive_note",
            "trash_note",
            "focus_search",
            "refresh",
            "switch_view",
            "focus_next",
            "cursor_down",
            "cursor_up",
        }
        if self.edit_mode and action in browse_only:
            return False
        if not self.edit_mode and action == "save_edit":
            return False
        return True

    # ── searching / listing ──────────────────────────────────────────────

    def on_mount(self) -> None:
        self.query_one(KeyBar).show(BROWSE_KEYS_BEAR, BROWSE_KEYS_TUI)
        self.query_one("#results", OptionList).focus()
        if self._preloaded:
            self._show_results("", [SearchResult(note=n, snippet="") for n in self.notes])
            self._scan_secrets()
        else:
            self._set_list_loading(True)
            self._rehydrate()

    def _set_list_loading(self, on: bool) -> None:
        results = self.query_one("#results", OptionList)
        pane = self.query_one("#list-pane")
        if on:
            self._focus_list_after_load = not (isinstance(self.focused, Input) and self.focused.value)
            results.display = False
            if not pane.query("LoadingIndicator"):
                pane.mount(LoadingIndicator())
        else:
            for indicator in pane.query(LoadingIndicator):
                indicator.remove()
            results.display = True

    @work(exclusive=True, thread=True, group="scan")
    def _scan_secrets(self) -> None:
        self.call_from_thread(self._apply_secret_values, redaction_map(scan_notes(self.notes)))

    def _apply_secret_values(self, values: dict[str, dict[str, str]]) -> None:
        self.secret_values = values
        results = self.query_one("#results", OptionList)
        self._set_list_loading(False)
        if self._focus_list_after_load:
            # The hidden list dropped focus into the search box during the
            # load; take it back unless the user started typing.
            self._focus_list_after_load = False
            if not self.query_one("#query", Input).value:
                results.focus()
        self._run_filter(self.search_query)

    @work(thread=True, group="refresh")
    def _refresh_note(self, note_id: str) -> None:
        """Re-read one note after a write; far cheaper than a full reload."""
        db = BearDB(self.db_path)
        try:
            fresh = db.get_note(note_id)
        finally:
            db.close()
        if fresh is None or not self._in_current_view(fresh):
            self.notes = [n for n in self.notes if n.id != note_id]
            self.secret_values.pop(note_id, None)
        else:
            secrets = redaction_map(scan_notes([fresh])).get(note_id)
            if note_id in {n.id for n in self.notes}:
                self.notes = [fresh if n.id == note_id else n for n in self.notes]
            else:
                self.notes.insert(0, fresh)
            if secrets:
                self.secret_values[note_id] = secrets
            else:
                self.secret_values.pop(note_id, None)
        self.call_from_thread(self._run_filter, self.search_query)

    @work(exclusive=True, thread=True, group="rehydrate")
    def _rehydrate(self) -> None:
        """Reload the current view from the database - also catches edits made in Bear."""
        db = BearDB(self.db_path)
        try:
            only = {"archive": "archived", "trash": "trashed"}.get(self.view)
            notes = db.list_notes(limit=None, tag=self.tag_filter, only=only)
        finally:
            db.close()
        self.notes = notes
        self.call_from_thread(self._apply_secret_values, redaction_map(scan_notes(notes)))

    def action_focus_search(self) -> None:
        query = self.query_one("#query", Input)
        query.focus()
        query.selection = query.selection.__class__(0, len(query.value))

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "query":
            self._run_filter(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "query":
            self.query_one("#results", OptionList).focus()

    @work(exclusive=True, thread=True, group="filter")
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
            has_secret = bool(self.secret_values.get(note.id))
            date = note.modified.strftime("%Y-%m-%d") if note.modified else " " * 10
            label = Text.assemble((date, "dim"), "  ")
            label.append(_highlighted(note.title, query, "bold red" if has_secret else "bold"))
            if note.tags:
                label.append("  ")
                label.append(_highlighted(" ".join(f"#{t}" for t in note.tags), query, "dim cyan"))
            badge = Text(no_wrap=True)
            if note.encrypted:
                badge.append(" 🔒", "dim")
            if has_secret:
                badge.append(" 🚨")
            row = RichTable.grid(expand=True)
            row.add_column(ratio=1, no_wrap=True, overflow="ellipsis")
            row.add_column(justify="right", no_wrap=True)
            row.add_column(width=2)  # spacer between badges and the scrollbar
            row.add_row(label, badge, "")
            options.append(Option(row, id=note.id))
        result_list = self.query_one("#results", OptionList)
        result_list.clear_options()
        result_list.add_options(options)
        prefix = {"notes": "", "archive": "Archive · ", "trash": "Trash · "}[self.view]
        self.query_one("#list-pane").border_title = f"{prefix}{len(self.shown)} / {len(self.notes)} notes"
        select_id, self._select_id = self._select_id, None
        index = next((i for i, n in enumerate(self.shown) if n.id == select_id), None) if select_id else None
        if self.shown:
            result_list.highlighted = index if index is not None else 0
        else:
            self.query_one("#preview-content", Static).update("")
        pending, self._pending_edit_id = self._pending_edit_id, None
        if pending and not self.edit_mode:
            note = next((n for n in self.shown if n.id == pending), None)
            if note and note.text is not None:
                self.editing = note
                self._enter_editor(note.title, note.text, secrets=self.secret_values.get(note.id, {}))

    def _selected(self) -> Note | None:
        results = self.query_one("#results", OptionList)
        if self.shown and results.highlighted is not None:
            return self.shown[results.highlighted]
        return None

    def _all_tags(self) -> list[str]:
        return sorted({tag for note in self.notes for tag in note.tags})

    def _preview(self, note: Note) -> RenderableType:
        status = pretty_status(note).replace(",", ", ")
        meta = Text()
        meta.append(note.title + "\n", "bold")
        meta.append(f"id       {note.id}\n", "dim")
        if note.created:
            meta.append(f"created  {note.created.strftime('%Y-%m-%d %H:%M')}\n", "dim")
        if note.modified:
            meta.append(f"modified {note.modified.strftime('%Y-%m-%d %H:%M')}\n", "dim")
        if not note.encrypted:
            meta.append(f"words    {len((note.text or '').split())}\n", "dim")
        if note.tags:
            meta.append(f"tags     {', '.join(note.tags)}\n", "dim")
        if status:
            meta.append(f"status   {status}\n", "dim")
        if secrets := self.secret_values.get(note.id):
            meta.append(f"secrets  🚨 {len(secrets)} potential - careful when sharing\n", "yellow")
        meta.append("─" * 30 + "\n", "dim")
        if note.encrypted:
            meta.append("\n🔒 This note is encrypted.\n", "bold")
            meta.append("View it directly in Bear: press ", "dim")
            meta.append("o", "bold")
            meta.append(".\n", "dim")
        else:
            source = "\n".join((note.text or "").splitlines()[:200])
            rules: list[tuple[str, str, bool]] = [
                (word, HIGHLIGHT, False) for word in self.search_query.split() if len(word) >= 2
            ]
            rules += [(value, SECRET_STYLE, True) for value in self.secret_values.get(note.id, {})]
            body: RenderableType = _LeftMarkdown(source)
            if rules:
                body = _StyledMatches(body, rules)
            return Group(meta, body)
        return meta

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if self.edit_mode:
            return
        note = next((n for n in self.shown if n.id == event.option_id), None)
        if note:
            self.query_one("#preview-content", Static).update(self._preview(note))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.action_edit_selected()

    # ── inline editor (right panel) ──────────────────────────────────────

    def _enter_editor(
        self, title: str, text: str, cursor: tuple[int, int] | None = None, secrets: Iterable[str] | None = None
    ) -> None:
        editor = self.query_one("#editor", SecretTextArea)
        editor.secret_values = list(secrets or [])
        editor.text = text
        self._editor_original = text
        editor.border_title = title
        self.query_one("#preview-pane").styles.display = "none"
        editor.styles.display = "block"
        editor.focus()
        if cursor:
            editor.cursor_location = cursor
        self.query_one(KeyBar).show(EDIT_KEYS_BEAR, EDIT_KEYS_TUI)
        self.refresh_bindings()

    def _exit_editor(self) -> None:
        self.editing = None
        self.creating = False
        self.query_one("#editor", TextArea).styles.display = "none"
        self.query_one("#preview-pane").styles.display = "block"
        self.query_one("#results", OptionList).focus()
        if note := self._selected():
            self.query_one("#preview-content", Static).update(self._preview(note))
        self.query_one(KeyBar).show(BROWSE_KEYS_BEAR, BROWSE_KEYS_TUI)
        self.refresh_bindings()

    def action_edit_selected(self) -> None:
        if self.edit_mode:
            return
        note = self._selected()
        if note is None:
            return
        if note.text is None:
            self.notify("Encrypted notes can't be edited here", severity="warning")
            return
        self.editing = note
        self._enter_editor(note.title, note.text, secrets=self.secret_values.get(note.id, {}))

    def action_new_note(self) -> None:
        if self.edit_mode:
            return
        self.creating = True
        self._enter_editor("New note", "# \n\n", cursor=(0, 2))

    def action_save_edit(self) -> None:
        if not self.edit_mode:
            return
        text = self.query_one("#editor", TextArea).text
        if self.creating:
            if text.strip() and text.strip() != "#":
                self._create_note(text)
        elif self.editing is not None and text != self.editing.text:
            self._save_note(self.editing, text)
        self._exit_editor()

    def action_back_or_quit(self) -> None:
        if self.edit_mode:
            if self.query_one("#editor", SecretTextArea).text != self._editor_original:

                def on_answer(answer: str | None) -> None:
                    if answer == "discard":
                        self._exit_editor()
                    elif answer == "save":
                        self.action_save_edit()

                self.push_screen(ConfirmDiscard(), on_answer)
            else:
                self._exit_editor()
        elif isinstance(self.focused, Input):
            self.query_one("#results", OptionList).focus()
        else:
            self.exit()

    # ── other actions ────────────────────────────────────────────────────

    def action_open_in_bear(self) -> None:
        if note := self._selected():
            actions.open_note(note.id)

    def action_add_tag(self) -> None:
        if note := self._selected():

            def on_done(tag: str | None) -> None:
                if tag:
                    self._tag_note(note, tag, add=True)

            self.push_screen(TagScreen(f"Add tag to “{note.title}”", self._all_tags()), on_done)

    def action_remove_tag(self) -> None:
        if (note := self._selected()) and note.tags:

            def on_done(tag: str | None) -> None:
                if tag:
                    self._tag_note(note, tag, add=False)

            self.push_screen(TagScreen(f"Remove tag from “{note.title}”", note.tags), on_done)

    def action_switch_view(self, view: str) -> None:
        if view == self.view:
            return
        self.view = view
        self._select_id = None
        self.notify({"notes": "Notes", "archive": "Archive", "trash": "Trash"}[view] + " view")
        self._set_list_loading(True)
        self._rehydrate()

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_cursor_down(self) -> None:
        if len(self.screen_stack) == 1:
            self.query_one("#results", OptionList).action_cursor_down()

    def action_cursor_up(self) -> None:
        if len(self.screen_stack) == 1:
            self.query_one("#results", OptionList).action_cursor_up()

    def action_refresh(self) -> None:
        self._set_list_loading(True)
        self._rehydrate()

    def action_archive_note(self) -> None:
        self._file_away("archive")

    def action_trash_note(self) -> None:
        self._file_away("trash")

    # ── write workers (fire x-callback, verify via db, refresh UI) ───────

    @work(thread=True)
    def _save_note(self, note: Note, new_text: str) -> None:
        fresh = self._attempt(lambda db: ops.add_text(db, note, new_text, mode=ops.TextMode.REPLACE_ALL))
        self._after_write(note.id, fresh, "Saved to Bear", "Save")

    def _attempt(self, operation: Callable[[BearDB], Note]) -> Note | None:
        """Run a verified write against a fresh db handle; None if Bear didn't apply it."""
        with BearDB(self.db_path) as db:
            try:
                return operation(db)
            except ops.BearWriteError:
                return None

    @work(thread=True)
    def _create_note(self, text: str) -> None:
        head, _, body = text.partition("\n")
        title = head.lstrip("# ").strip() or "Untitled"
        created = self._attempt(lambda db: ops.create_note(db, title, body.strip() or None))
        if created is not None:
            self.notes.insert(0, created)
            self.call_from_thread(self._run_filter, self.search_query)
            self.call_from_thread(self.notify, f"Created {created.title!r}")
            self._refresh_note(created.id)
        else:
            self.call_from_thread(self.notify, "Create failed - is Bear able to run?", severity="error")

    @work(thread=True)
    def _tag_note(self, note: Note, tag: str, add: bool) -> None:
        if add:
            fresh = self._attempt(lambda db: ops.add_tag(db, note, tag))
        else:
            try:
                fresh = self._attempt(lambda db: ops.remove_tag(db, note, tag))
            except ops.TagMarkerNotFound:
                self.call_from_thread(self.notify, f"Note has no tag {tag!r}", severity="warning")
                return
        message = f"Tagged with {tag!r}" if add else f"Removed tag {tag!r}"
        self._after_write(note.id, fresh, message, "Tag" if add else "Untag", edit_after=True)

    def _in_current_view(self, note: Note) -> bool:
        if self.view == "trash":
            return note.trashed
        if self.view == "archive":
            return note.archived and not note.trashed
        return not note.trashed and not note.archived

    def _file_away(self, operation: str) -> None:
        if (operation == "trash" and self.view == "trash") or (operation == "archive" and self.view == "archive"):
            self.notify(f"Already in the {self.view} view", severity="warning")
            return
        if note := self._selected():
            self._file_away_worker(note, operation)

    @work(thread=True)
    def _file_away_worker(self, note: Note, operation: str) -> None:
        fresh = self._attempt(lambda db: ops.trash(db, note) if operation == "trash" else ops.archive(db, note))
        if fresh is not None:
            # Selection moves to the note that takes the removed one's place.
            index = next((i for i, n in enumerate(self.shown) if n.id == note.id), None)
            if index is not None and len(self.shown) > 1:
                neighbour = self.shown[index + 1] if index + 1 < len(self.shown) else self.shown[index - 1]
                self._select_id = neighbour.id
            self.notes = [n for n in self.notes if n.id != note.id]
            self.secret_values.pop(note.id, None)
            self.call_from_thread(self._run_filter, self.search_query)
            self.call_from_thread(self.notify, f"{operation.capitalize()}ed {note.title!r}")
        else:
            self.call_from_thread(self.notify, f"{operation} failed - is Bear able to run?", severity="error")

    # ── write plumbing ───────────────────────────────────────────────────

    def _after_write(
        self, note_id: str, fresh: Note | None, ok_message: str, operation: str, edit_after: bool = False
    ) -> None:
        if fresh is not None:
            self.call_from_thread(self.notify, ok_message)
            self._select_id = note_id
            if edit_after:
                self._pending_edit_id = note_id
            self._refresh_note(note_id)
        else:
            self.call_from_thread(self.notify, f"{operation} failed - is Bear able to run?", severity="error")


def run_ui(
    fuzzy: bool = False,
    db_path: Path = DEFAULT_DB_PATH,
    tag_filter: str | None = None,
) -> None:
    BearUI(fuzzy=fuzzy, db_path=db_path, tag_filter=tag_filter).run()
