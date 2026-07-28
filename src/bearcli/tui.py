"""Interactive note browser and editor (Textual).

All writes go through Bear's x-callback-url API (never SQL) and are verified
by re-reading the database, mirroring the CLI's write commands.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from rich.table import Table as RichTable
from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, Input, Label, OptionList, Static, TextArea
from textual.widgets.option_list import Option

from bearcli import actions
from bearcli.db import DEFAULT_DB_PATH, BearDB, Note
from bearcli.markdown import remove_tag_marker, tag_marker
from bearcli.search import SearchResult, naive_search, search_notes
from bearcli.secrets import redaction_map, scan_notes
from bearcli.write import create_and_find

HIGHLIGHT = "black on #dcb96a"
SECRET_STYLE = "black on #ff9999"


def _highlighted(value: str, query: str, base_style: str = "") -> Text:
    text = Text(value, style=base_style)
    words = [w for w in query.split() if len(w) >= 2]
    if words:
        text.highlight_words(words, HIGHLIGHT, case_sensitive=False)
    return text


class SecretTextArea(TextArea):
    """TextArea that renders detected secret values on a light red background."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.secret_values: list[str] = []

    def get_line(self, line_index: int) -> Text:
        line = super().get_line(line_index)
        if self.secret_values:
            line.highlight_words(self.secret_values, SECRET_STYLE, case_sensitive=True)
        return line


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
    #suggestions { max-height: 8; margin-top: 1; display: none; }
    """

    def __init__(self, prompt: str, choices: list[str]):
        super().__init__()
        self.prompt = prompt
        self.choices = choices

    def compose(self) -> ComposeResult:
        with Vertical(id="box"):
            yield Label(self.prompt, id="tag-prompt")
            yield Input(placeholder="tag name…", id="tag-name")
            yield OptionList(id="suggestions")

    def on_mount(self) -> None:
        self._suggest("")

    def _suggest(self, value: str) -> None:
        matches = [t for t in self.choices if value.lower() in t.lower()][:8]
        suggestions = self.query_one("#suggestions", OptionList)
        suggestions.clear_options()
        suggestions.add_options([Option(t, id=t) for t in matches])
        suggestions.styles.display = "block" if matches else "none"

    def on_input_changed(self, event: Input.Changed) -> None:
        self._suggest(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)

    def on_key(self, event: events.Key) -> None:
        if event.key == "down" and self.query_one("#tag-name", Input).has_focus:
            suggestions = self.query_one("#suggestions", OptionList)
            if suggestions.option_count:
                event.stop()
                suggestions.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option_id)

    def action_cancel(self) -> None:
        self.dismiss(None)


class BearUI(App):
    """Browse, edit, and organize Bear notes from the terminal."""

    TITLE = "bearcli"
    ENABLE_COMMAND_PALETTE = False

    CSS = """
    #query { dock: top; margin: 0 1; border: round $primary; }
    #query:focus { border: round $accent; }
    #results { width: 34%; border: round $panel-lighten-2; }
    #results:focus { border: round $accent; }
    #side { width: 66%; }
    #preview-pane { height: 1fr; border: round $panel-lighten-2; padding: 0 1; }
    #editor { height: 1fr; border: round $accent; display: none; }
    Horizontal { height: 1fr; margin: 0 1; }
    """

    BINDINGS = [
        Binding("escape", "back_or_quit", "Quit"),
        Binding("/", "focus_search", "Search"),
        Binding("enter", "edit_selected", "Edit", show=True),
        Binding("n", "new_note", "New", key_display="n/c"),
        Binding("c", "new_note", "New", show=False),
        Binding("t", "add_tag", "Tag"),
        Binding("T", "remove_tag", "Untag", show=False),
        Binding("o", "open_in_bear", "Open in Bear"),
        Binding("r", "refresh", "Refresh", show=False),
        Binding("a", "archive_note", "Archive"),
        Binding("d", "trash_note", "Trash"),
        Binding("ctrl+s", "save_edit", "Save to Bear"),
        Binding("tab", "focus_next", "Switch pane", show=False),
    ]

    def __init__(
        self,
        notes: list[Note],
        fuzzy: bool = False,
        db_path: Path = DEFAULT_DB_PATH,
        tag_filter: str | None = None,
    ):
        super().__init__()
        self.notes = notes
        self.fuzzy = fuzzy
        self.db_path = db_path
        self.tag_filter = tag_filter
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
        with Horizontal():
            yield OptionList(id="results")
            with Vertical(id="side"):
                yield Static(id="preview-pane")
                yield SecretTextArea(language="markdown", id="editor")
        yield Footer()

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
        }
        if self.edit_mode and action in browse_only:
            return False
        if not self.edit_mode and action == "save_edit":
            return False
        return True

    # ── searching / listing ──────────────────────────────────────────────

    def on_mount(self) -> None:
        self._show_results("", [SearchResult(note=n, snippet="") for n in self.notes])
        self.query_one("#results", OptionList).focus()
        self._scan_secrets()

    @work(exclusive=True, thread=True, group="scan")
    def _scan_secrets(self) -> None:
        self.call_from_thread(self._apply_secret_values, redaction_map(scan_notes(self.notes)))

    def _apply_secret_values(self, values: dict[str, dict[str, str]]) -> None:
        self.secret_values = values
        self._run_filter(self.search_query)

    @work(thread=True, group="refresh")
    def _refresh_note(self, note_id: str) -> None:
        """Re-read one note after a write; far cheaper than a full reload."""
        db = BearDB(self.db_path)
        try:
            fresh = db.get_note(note_id)
        finally:
            db.close()
        if fresh is None or fresh.trashed:
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
        """Reload every note from the database - manual refresh, also catches edits made in Bear."""
        db = BearDB(self.db_path)
        try:
            notes = db.list_notes(limit=None, tag=self.tag_filter, with_text=True)
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
            date = note.modified.strftime("%Y-%m-%d") if note.modified else " " * 10
            label = Text.assemble((date, "dim"), "  ")
            label.append(_highlighted(note.title, query, "bold"))
            if note.tags:
                label.append("  ")
                label.append(_highlighted(" ".join(f"#{t}" for t in note.tags), query, "dim cyan"))
            has_secret = bool(self.secret_values.get(note.id))
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
            if has_secret:
                row.style = "on dark_red"
            options.append(Option(row, id=note.id))
        result_list = self.query_one("#results", OptionList)
        result_list.clear_options()
        result_list.add_options(options)
        result_list.border_title = f"{len(self.shown)} / {len(self.notes)} notes"
        select_id, self._select_id = self._select_id, None
        index = next((i for i, n in enumerate(self.shown) if n.id == select_id), None) if select_id else None
        if self.shown:
            result_list.highlighted = index if index is not None else 0
        else:
            self.query_one("#preview-pane", Static).update("")
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
            body = _highlighted("\n".join((note.text or "").splitlines()[:60]), self.search_query)
            for value in self.secret_values.get(note.id, []):
                body.highlight_words([value], SECRET_STYLE, case_sensitive=True)
            meta.append(body)
        return meta

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if self.edit_mode:
            return
        note = next((n for n in self.shown if n.id == event.option_id), None)
        if note:
            self.query_one("#preview-pane", Static).update(self._preview(note))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.action_edit_selected()

    # ── inline editor (right panel) ──────────────────────────────────────

    def _enter_editor(
        self, title: str, text: str, cursor: tuple[int, int] | None = None, secrets: Iterable[str] | None = None
    ) -> None:
        editor = self.query_one("#editor", SecretTextArea)
        editor.secret_values = list(secrets or [])
        editor.text = text
        editor.border_title = title
        self.query_one("#preview-pane", Static).styles.display = "none"
        editor.styles.display = "block"
        editor.focus()
        if cursor:
            editor.cursor_location = cursor
        self.refresh_bindings()

    def _exit_editor(self) -> None:
        self.editing = None
        self.creating = False
        self.query_one("#editor", TextArea).styles.display = "none"
        self.query_one("#preview-pane", Static).styles.display = "block"
        self.query_one("#results", OptionList).focus()
        if note := self._selected():
            self.query_one("#preview-pane", Static).update(self._preview(note))
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

    def action_refresh(self) -> None:
        self._rehydrate()
        self.notify("Reloading from Bear…")

    def action_archive_note(self) -> None:
        self._file_away("archive")

    def action_trash_note(self) -> None:
        self._file_away("trash")

    # ── write workers (fire x-callback, verify via db, refresh UI) ───────

    @work(thread=True)
    def _save_note(self, note: Note, new_text: str) -> None:
        actions.add_text(note.id, new_text, mode="replace_all")
        self._finish_write(note.id, lambda db: self._modified_after(db, note), "Saved to Bear", "Save")

    @work(thread=True)
    def _create_note(self, text: str) -> None:
        head, _, body = text.partition("\n")
        title = head.lstrip("# ").strip() or "Untitled"
        db = BearDB(self.db_path)
        try:
            created = create_and_find(db, title, body.strip() or None)
            if created is not None:
                self.notes.insert(0, created)
                self.call_from_thread(self._run_filter, self.search_query)
                self.call_from_thread(self.notify, f"Created {created.title!r}")
                self._refresh_note(created.id)
            else:
                self.call_from_thread(self.notify, "Create failed - is Bear able to run?", severity="error")
        finally:
            db.close()

    @work(thread=True)
    def _tag_note(self, note: Note, tag: str, add: bool) -> None:
        if add:
            actions.add_text(note.id, tag_marker(tag), mode="append")
            self._finish_write(
                note.id, lambda db: self._has_tag(db, note.id, tag), f"Tagged with {tag!r}", "Tag", edit_after=True
            )
        else:
            new_text = remove_tag_marker(note.text or "", tag)
            if new_text is None:
                self.call_from_thread(self.notify, f"Note has no tag {tag!r}", severity="warning")
                return
            actions.add_text(note.id, new_text, mode="replace_all")
            self._finish_write(
                note.id,
                lambda db: not self._has_tag(db, note.id, tag),
                f"Removed tag {tag!r}",
                "Untag",
                edit_after=True,
            )

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

    def _finish_write(self, note_id: str, predicate, ok_message: str, operation: str, edit_after: bool = False) -> None:
        if self._wait(predicate):
            self.call_from_thread(self.notify, ok_message)
            self._select_id = note_id
            if edit_after:
                self._pending_edit_id = note_id
            self._refresh_note(note_id)
        else:
            self.call_from_thread(self.notify, f"{operation} failed - is Bear able to run?", severity="error")


def run_ui(
    notes: list[Note],
    fuzzy: bool = False,
    db_path: Path = DEFAULT_DB_PATH,
    tag_filter: str | None = None,
) -> None:
    BearUI(notes, fuzzy=fuzzy, db_path=db_path, tag_filter=tag_filter).run()
