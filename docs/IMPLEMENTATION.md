# Implementation notes

How bearcli reads Bear's data and how the export is designed. Everything here
was verified against a live Bear database (Bear 2.x, mid-2026); the parts most
likely to drift across Bear versions are called out.

## Bear's data storage

Bear is a Core Data app backed by SQLite:

```
~/Library/Group Containers/9K33E3U3T4.net.shinyfrog.bear/Application Data/
  database.sqlite          # notes, tags, attachment metadata
  Local Files/
    Note Images/<attachment-uuid>/<filename>   # image attachments
    Note Files/<attachment-uuid>/<filename>    # other attachments
```

bearcli opens the database with `sqlite3.connect("file:...?mode=ro", uri=True)`.
Read-only mode means no locks that could interfere with Bear, and the Bear app
does not need to be running (it only needs to be running for x-callback-url
based *writing*, which bearcli deliberately does not do).

### Tables

`ZSFNOTE` — one row per note:

| Column | Meaning |
|---|---|
| `Z_PK` | Core Data primary key (internal; used for joins only) |
| `ZUNIQUEIDENTIFIER` | public note id (usually a UUID; sometimes longer, e.g. `...-536-0000575D...` — never assume 36 chars) |
| `ZTITLE`, `ZTEXT` | title and full markdown body (`ZTEXT` is NULL for encrypted notes) |
| `ZCREATIONDATE`, `ZMODIFICATIONDATE` | Core Data timestamps (see below) |
| `ZPINNED`, `ZENCRYPTED`, `ZARCHIVED`, `ZTRASHED` | status flags (0/1) |
| `ZPERMANENTLYDELETED` | 1 for deleted rows lingering until iCloud sync; must always be filtered out |

`ZSFNOTETAG` — one row per tag (`Z_PK`, `ZTITLE`). Nested tags are stored as
full paths (`work/ideas` is one row whose title contains the slash), which is
why the tag filter matches `title = ?` OR `title LIKE '<tag>/%'`.

Note↔tag join table — named `Z_<N>TAGS` with columns `Z_<N>NOTES` and
`Z_<M>TAGS`, where N and M are Core Data entity numbers that **change between
Bear versions** (currently `Z_5TAGS(Z_5NOTES, Z_13TAGS)`). `BearDB._detect_tags_join`
finds the table and columns at runtime by pattern-matching `sqlite_master`,
so bearcli survives Bear schema migrations.

`ZSFNOTEFILE` — one row per attachment: `ZNOTE` (FK to note `Z_PK`),
`ZUNIQUEIDENTIFIER` (the attachment's own uuid = its directory on disk),
`ZFILENAME`, `ZFILESIZE`, and `ZPERMANENTLYDELETED`. The row does *not* record
whether the file lives under `Note Images` or `Note Files`, so bearcli probes
both paths and reports an `exists` flag.

### Timestamps

Core Data stores dates as float seconds since **2001-01-01 00:00:00 UTC**
(unix epoch + 978307200). `db.core_data_to_datetime` converts to timezone-aware
local datetimes; comparisons in SQL convert the other way rather than
converting every row.

### Attachment references in note text

The markdown body references attachments by **bare filename only** —
`![](image.png)` — and the filename is **percent-encoded** in the text
(`image%202.png` on disk is `image 2.png`). Any link rewriting must therefore
match both the raw and percent-encoded forms of the filename, and emit
percent-encoded targets (Bear's own data directory contains spaces, so
unencoded absolute paths would produce broken markdown links). Only filenames
known from `ZSFNOTEFILE` are rewritten — regular URLs in the text are never
touched.

## CLI design (`cli.py`)

- `list` / `get` / `export`. `--db` (env `BEAR_DB_PATH`) is per-subcommand
  rather than a top-level option, deliberately: with the env var covering
  "set it once", trailing-position ergonomics win.
- Output formats: `table` (Rich, human), `json` (full data, ISO dates),
  `text` (TSV: id, modified, tags, status, title — title last because it can
  contain spaces). Machine formats bypass Rich entirely.
- Status (pinned/encrypted/trashed/archived) is one comma-joined column/field,
  not icons. `--only <status>` filters to exactly one status; `--trashed` /
  `--archived` include those notes in results.

## Export design (`export.py`)

Each note becomes a self-contained directory:

```
DEST/
  README.md                    # generated index (see below)
  index.json                   # machine-readable catalog
  <slug>-<shortid>/
    README.md                  # frontmatter (id/title/tags/created/modified) + body
    attachments/<filename>     # copied attachment files
```

Decisions and their reasons:

- **Per-note directory, README.md inside**: the folder is portable as a unit,
  and GitHub renders the note when you browse into the folder.
- **Attachments in a subdirectory** (not next to README.md): avoids any
  possibility of an attachment named `README.md` colliding with the note file.
  Links in the body are rewritten to `attachments/<filename>` (percent-encoded).
- **Directory name `<slug>-<shortid>`** (60-char title slug + first 8 chars of
  the note id, e.g. `bearcli-fieldnotes-c44d09dc`): the id fragment makes names
  unique by construction, eliminating title-dedup suffix logic and its
  order-dependent renumbering. If two notes ever collide on slug+prefix, both
  fall back to their full id — deterministically, regardless of iteration
  order. Title renames do rename the directory (path stability was explicitly
  traded away for readability).
- **Sync** (`--sync`): a note is skipped when the existing README's frontmatter
  matches on both `id` and `modified` (exact ISO string compare). Bear bumps
  `ZMODIFICATIONDATE` on any edit including renames, so this is a reliable
  change signal.
- **Cleanup**: directories whose name is no longer produced by the current
  export are removed — but only if they contain a `README.md` with an `id:`
  frontmatter field. This makes deletion safe: user-created files/dirs in the
  destination are never touched. A title rename is therefore new-dir + cleanup
  of the old one.
- **Index**: the root `README.md` has a pinned section then per-year sections
  (year of modification, descending), rows linking to note *folders* (GitHub
  auto-renders each folder's README). Encrypted notes appear unlinked (they
  export no folder). It is rewritten only when content changed (no churn on
  no-op syncs) and only if it carries `generated-by: bearcli` frontmatter (or
  doesn't exist) — a hand-written README is preserved with a warning.
  `index.json` carries the same catalog for scripts.
- **Encrypted notes** are counted and indexed but never exported (`ZTEXT` is
  NULL; content only exists in `ZENCRYPTEDDATA`).
- Export is UI-free: progress is reported through an optional callback, and the
  CLI renders it as a Rich status spinner (escaping titles so `[...]` isn't
  parsed as markup).

## Write actions (`actions.py`)

The database is never written — not because of caution alone, but because Bear
tracks sync state (`ZSFCHANGE`, server-data tables) that direct SQL writes
would desynchronize. Mutations go through Bear's `bear://x-callback-url/`
scheme (`create`, `add-text`, `trash`, `archive`), fired with `open -g` so
Bear stays in the background. The URL scheme launches Bear if it isn't
running — this is the only part of bearcli that needs the app.

URL actions are fire-and-forget (no result without an x-success callback
server), so each CLI command verifies the outcome by polling the read-only
database: `create` looks for a note with the given title created after the
call, `append` for a bumped modification date, `trash`/`archive` for the flag.
A missing verification within ~6s is reported as an error.

Learned from testing: trashing an archived note keeps `ZARCHIVED = 1`
alongside `ZTRASHED = 1`, and Bear shows such notes in the Trash — so the
`--only trashed` filter must not apply the default archived-exclusion.

## Reference

Prior art: [sandip-mane/bear-github-sync](https://github.com/sandip-mane/bear-github-sync)
(bash, bidirectional). Its export half validated this design; differences:
bearcli detects the tag join table instead of hardcoding it, opens the DB
read-only, uses parameterized SQL, and rewrites only known attachment
filenames instead of regex-rewriting every relative image link.
