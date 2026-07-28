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
```

There is no test suite yet; changes are verified by running the CLI against the
local Bear database. The database lives at
`~/Library/Group Containers/9K33E3U3T4.net.shinyfrog.bear/Application Data/database.sqlite`;
pass `--db` or set `BEAR_DB_PATH` to use a copy.

## Layout

- `src/bearcli/cli.py` — Typer app, grouped into `note` (list, get, search,
  create, append, replace, rename, attach, trash, archive, open, tag, untag)
  and `tag` (list, rename, delete) sub-apps plus top-level `export`;
  the most-used commands (list, search, get, open, create) have top-level
  aliases shown in a separate "Shortcuts" help panel. All presentation (Rich tables, JSON/text formats,
  spinner) lives here.
- `src/bearcli/actions.py` — write actions via Bear's x-callback-url scheme.
  No database access; fire-and-forget `open -g bear://...` calls.
- `src/bearcli/db.py` — database layer. Opens SQLite in read-only URI mode,
  converts Core Data timestamps, detects the note/tag join table dynamically.
  No CLI or output concerns.
- `src/bearcli/export.py` — export to per-note directories with index
  generation. UI-free; reports progress through an optional callback.
- `src/bearcli/gitsync.py` — `export --push`: commit/merge/push convergence
  loop treating the destination repo as a one-way mirror (Bear wins in HEAD,
  overwritten edits stay in history, never force-pushes).

See `docs/IMPLEMENTATION.md` for Bear's schema details and export design.

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
  identified by a `README.md` whose frontmatter has an `id:` field, the root
  index by `generated-by: bearcli` frontmatter. Never delete or overwrite
  anything else in the destination.
- Encrypted notes (`ZENCRYPTED = 1`) have no readable text; surface them in
  listings/indexes but never fail trying to read their content.

## Documentation

When changing the CLI surface (commands added/removed/renamed, notable flags,
changed behavior), update `README.md` (usage examples) and `docs/index.html`
(the GitHub Pages one-pager: command table, demo terminal if output changed)
in the same commit. CI runs `scripts/check_docs.py`, which fails if any
command is missing from either file — but it only checks command names, so
keeping descriptions and examples accurate is on you.

## Conventions

- Machine-readable output (`-f text`, `-f json`, `--ids`) goes through plain
  `print`, never through the Rich console (no wrapping, no styling, pipeable).
- Text format is tab-separated with the title as the last field (titles can
  contain spaces; earlier fields are then safe for `cut`/`awk`).
- Dates are timezone-aware ISO in machine output, `YYYY-MM-DD HH:MM` in tables.
