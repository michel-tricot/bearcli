# Agent instructions for bearcli

CLI that reads notes from the Bear note app (macOS) by opening Bear's SQLite
database directly. The database is strictly read-only; write actions (create,
append, trash, archive) go exclusively through Bear's x-callback-url API in
`src/bearcli/actions.py` — never through SQL. Reading never requires the Bear
app to be running; write actions launch it via the URL scheme.

## Commands

```sh
uv sync                  # install dependencies
uv run bearcli --help    # run the CLI
uv run bearcli list -n 5 # quick smoke test (needs Bear installed locally)

uv run ruff format src/  # format (line length 120)
uv run ruff check src/   # lint — must pass before committing
uv run ty check src/     # type check — must pass before committing
uv run pytest tests/ -q  # test suite — must pass before committing
uv run python scripts/check_docs.py       # docs cover every command
uv run python scripts/render_tui_demo.py  # regenerate docs/tui.svg after TUI changes
```

Run `uv run pytest tests/` - the suite uses a synthetic Bear database
(tests/conftest.py builds the real schema with fabricated data), so it needs
no local Bear. Behavior changes still deserve a manual check against the real
database. The database lives at
`~/Library/Group Containers/9K33E3U3T4.net.shinyfrog.bear/Application Data/database.sqlite`;
pass `--db` or set `BEAR_DB_PATH` to use a copy.

## Layout

Two packages ship from this repo: `bearlib` (the fundamentals for talking to
Bear - no UI dependencies) and `bearcli` (the CLI/TUI product built on it).
bearlib must never import from bearcli.

`src/bearlib/`:
- `db.py` — database layer. Opens SQLite in read-only URI mode, converts
  Core Data timestamps, detects the note/tag join table dynamically.
- `actions.py` — write actions via Bear's x-callback-url scheme. No database
  access; fire-and-forget `open -g bear://...` calls.
- `ops.py` — verified write operations: fire the Bear action, confirm via
  the database, return the fresh note.
- `markdown.py` — Bear markdown conventions (attachment link rewriting, tag
  markers).
- `search.py` — naive and fuzzy (rapidfuzz) search over notes.
- `secrets.py` — detect-secrets-based scanning and redaction. Redact matches
  in output; never print the secret itself.

`src/bearcli/`:
- `cli/` — Typer CLI package: `common.py` (apps, output types, shared
  helpers), `notes.py` (the `note` group), `tags.py` (the `tag` group),
  `export.py`, `misc.py` (stats, ui), `__init__.py` (assembly + top-level
  aliases shown in the "Shortcuts" help panel). All presentation (Rich
  tables, JSON/text formats, spinner) lives here.
- `tui.py` — the interactive `ui` Textual app (search, edit, create, tag;
  writes via bearlib.ops, verified like the CLI).
- `export.py` — export to per-note directories with index generation.
  UI-free; reports progress through an optional callback. Export blocks on
  secret findings before writing anything (`--allow-secrets` overrides).
- `gitsync.py` — `export --push`: commit/merge/push convergence loop
  treating the destination repo as a one-way mirror (Bear wins in HEAD,
  overwritten edits stay in history, never force-pushes).

## Hard rules

- Open the database with `mode=ro` (URI). Never take a writable connection.
  All mutations go through `bear://x-callback-url/` (see `actions.py`); after
  firing one, verify the outcome by re-reading the database (Bear applies URL
  actions asynchronously and returns nothing).
- Use parameterized SQL; never interpolate values into queries.
- Do not hardcode the tag join table names (`Z_5TAGS`, `Z_13TAGS` etc.) — the
  numeric prefixes change between Bear versions; use the runtime detection in
  `BearDB._detect_tags_join`.
- Always filter `ZPERMANENTLYDELETED = 0` when listing notes or attachments.
- Export must only modify files/directories it owns: note directories are
  identified by a `README.md` whose frontmatter has an `id:` field; the root
  `README.md`/`index.json` are always bearcli's to overwrite. Never delete or
  overwrite anything else in the destination.
- Encrypted notes (`ZENCRYPTED = 1`) have no readable text; surface them in
  listings/indexes but never fail trying to read their content.

## Documentation — part of every change

Docs must always describe the current state of the CLI and TUI. Any commit
that changes behavior updates the docs in the same commit; do not push and
"catch up later". Checklist by kind of change:

- Commands/flags added, removed, renamed, or behavior changed → update
  `README.md` (usage examples, section prose) and `docs/index.html` (command
  table, feature cards, demo terminal text if output shapes changed). CI runs
  `scripts/check_docs.py`, but it only verifies command *names* appear —
  accurate descriptions and examples are on you.
- TUI keybindings or interactions changed → update the README "Terminal UI"
  key-map paragraph AND the in-app help (`HELP_ROWS`) AND the key bar
  (`BROWSE_KEYS_*`/`EDIT_KEYS_*`) so all three agree.
- TUI appearance changed (layout, colors, indicators, key bar) → regenerate
  the website screenshot: `uv run python scripts/render_tui_demo.py` and
  commit `docs/tui.svg`.
- bearlib public API changed (functions, signatures, enums, errors,
  behavior) → update `docs/BEARLIB.md`, including the **code sample for each
  affected function** (every public function has one; add a sample for new
  functions). Samples must be self-contained (own imports and setup) and
  pass the project's ruff lint + format. `tests/test_bearlib_docs.py`
  enforces compilation, name existence, and lint/format - but only you can
  keep the samples idiomatic and reflective of the change.
- Design decisions, Bear-schema learnings, or non-obvious internals → record
  them in `docs/IMPLEMENTATION.md`.
- New modules or moved responsibilities → update the Layout section here.

## Conventions

- Machine-readable output (`-f text`, `-f json`, `--ids`) goes through plain
  `print`, never through the Rich console (no wrapping, no styling, pipeable).
- Text format is tab-separated with the title as the last field (titles can
  contain spaces; earlier fields are then safe for `cut`/`awk`).
- Dates are timezone-aware ISO in machine output, `YYYY-MM-DD HH:MM` in tables.
