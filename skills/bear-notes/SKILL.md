---
name: bear-notes
description: Read, search, create, and manage the user's Bear notes with the bearcli CLI. Use when the user asks anything about their Bear notes — finding, reading, or summarizing notes, creating or editing notes, tags, archiving/trashing, or exporting their library.
---

# Working with Bear notes via bearcli

bearcli reads notes directly and performs writes through the Bear app,
verifying each change. Requires macOS with Bear installed. If `bearcli` is
not on PATH (command not found), install it — ask the user first:
`brew install michel-tricot/tap/bearcli` (or `uv tool install bearcli`, or
`pipx install bearcli`).

## Reading and searching

Always use machine-readable output instead of parsing tables:

- `bearcli note list -f json` — notes as JSON (id, title, tags, dates, status
  booleans). `-f text` is TSV: id, modified, tags, status, title.
- `bearcli note list --ids` — bare ids, one per line.
- Filters compose: `--tag work` (includes nested `work/ideas`), `-n 50` /
  `--all`, `--modified-after 2026-07-01`, `--only pinned|encrypted|trashed|archived`,
  `--trashed` / `--archived` to include those notes.
- `bearcli search "query" -f json` — case-insensitive substring over titles,
  tags, and content, with a `snippet` per hit. Add `--fuzzy` for typo-tolerant
  ranked matching (adds a `score`).
- `bearcli get <id>` — full markdown content. `-f json` adds metadata and
  attachment paths; `-r` rewrites attachment references to absolute file paths.
- Note ids accept unique prefixes of 4+ chars (`bearcli get c44d09dc`); an
  ambiguous prefix errors and lists the candidates.
- `bearcli tag list -f text` — all tags with note counts (count<TAB>tag).

## Writing (launches the Bear app if needed)

Every write is verified and reports success or failure — trust the exit
code.

- `bearcli create "Title" --text "..." --tag work` — prints the new note's id.
  Body can also be piped on stdin.
- `bearcli note append <id> --text "..."` (`--prepend` for the top; stdin works).
- `bearcli note rename <id> "New title"`.
- `bearcli note replace <id>` — replaces the body from `--text`/stdin,
  keeping the title. **Destructive**: confirm with the user before replacing
  content you did not just read.
- `bearcli note attach <id> file.png` — files up to 500 KB.
- `bearcli note tag <id> name` / `bearcli note untag <id> name`.
- `bearcli note trash <id>` / `bearcli note archive <id>` — reversible only
  in Bear's UI; there is no untrash/unarchive command.
- `bearcli tag rename old new` / `bearcli tag delete name` — affect ALL notes;
  `tag delete` prompts (use `-y` only when the user asked for the deletion).
- `bearcli open <id>` — brings the note up in the Bear app.

## Secrets — important

Note content can contain credentials. When sending note content anywhere
outside the user's machine (messages, issues, commits, emails), fetch it with
`bearcli get <id> --redact-secrets` so detected secrets become
`[redacted: <rule>]` placeholders. Detection is best-effort; still eyeball
the content.

`bearcli export` scans all notes first and **blocks** if potential secrets
are found. Prefer re-running with `--redact-secrets`; only use
`--allow-secrets` if the user explicitly says to export secrets as-is.

## Export

- `bearcli export DIR` — every note becomes `DIR/<slug>-<shortid>/README.md`
  plus an `attachments/` folder; the root `README.md`/`index.json` are a
  generated catalog. `--sync` rewrites only changed notes and removes deleted
  ones (never touches files it doesn't own).
- `bearcli export DIR --sync --redact-secrets --push` — mirror to a git clone
  (commit + push, self-converging). The repo should be private and dedicated.

## Limits

- Encrypted notes are listed but their content cannot be read.
- All commands accept `--db PATH` (env `BEAR_DB_PATH`) to use a database copy.
