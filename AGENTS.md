# Agent instructions for bearcli

CLI that reads notes from the Bear note app (macOS) by opening Bear's SQLite
database directly. Read-only by design: this tool must never write to Bear's
database or require the Bear app to be running.

## Commands

```sh
uv sync                  # install dependencies
uv run bearcli --help    # run the CLI
uv run bearcli list -n 5 # quick smoke test (needs Bear installed locally)
```

There is no test suite yet; changes are verified by running the CLI against the
local Bear database. The database lives at
`~/Library/Group Containers/9K33E3U3T4.net.shinyfrog.bear/Application Data/database.sqlite`;
pass `--db` or set `BEAR_DB_PATH` to use a copy.

## Layout

- `src/bearcli/cli.py` — Typer app (commands: `list`, `get`, `export`). All
  presentation (Rich tables, JSON/text formats, spinner) lives here.
- `src/bearcli/db.py` — database layer. Opens SQLite in read-only URI mode,
  converts Core Data timestamps, detects the note/tag join table dynamically.
  No CLI or output concerns.
- `src/bearcli/export.py` — export to per-note directories with index
  generation. UI-free; reports progress through an optional callback.

See `docs/IMPLEMENTATION.md` for Bear's schema details and export design.

## Hard rules

- Open the database with `mode=ro` (URI). Never take a writable connection.
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

## Conventions

- Machine-readable output (`-f text`, `-f json`, `--ids`) goes through plain
  `print`, never through the Rich console (no wrapping, no styling, pipeable).
- Text format is tab-separated with the title as the last field (titles can
  contain spaces; earlier fields are then safe for `cut`/`awk`).
- Dates are timezone-aware ISO in machine output, `YYYY-MM-DD HH:MM` in tables.
