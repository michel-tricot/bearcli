<div align="center">

# 🐻 `bearcli`

**The missing CLI for [Bear](https://bear.app) notes** - read, search, export, and
manage your notes from the terminal.

[![CI](https://github.com/michel-tricot/bearcli/actions/workflows/ci.yml/badge.svg)](https://github.com/michel-tricot/bearcli/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue.svg)](pyproject.toml)
[![macOS](https://img.shields.io/badge/platform-macOS-lightgrey.svg)](#)

[**Website**](https://michel-tricot.github.io/bearcli/) ·
[Commands](#commands) ·
[How it works](docs/IMPLEMENTATION.md)

</div>

---

## Install

```sh
uv tool install bearcli        # or: uvx bearcli, pipx install bearcli
```

Or from a clone: `uv sync`, then `uv run bearcli --help`.

## Quick start

```sh
bearcli list                       # 20 most recently modified notes
bearcli search "quarterly report"  # search titles, tags, and content
bearcli get <note-id>              # print a note's markdown
bearcli create "Idea" --tag inbox  # create a note
bearcli export ~/bear-backup       # export everything as markdown folders
```

## Commands

Commands are grouped under `note` and `tag`; the most common ones (`list`,
`search`, `get`, `open`, `create`) also work directly as shortcuts.

### Browse & read

```sh
bearcli note list                            # 20 most recently modified
bearcli note list --limit 5 --tag work       # filters: tag (incl. nested), dates...
bearcli note list --modified-after 2026-07-01
bearcli note list --only pinned              # or: encrypted, trashed, archived
bearcli note list --all --trashed --archived
bearcli note list --ids                      # only identifiers, one per line

bearcli get C44D09DC       # a unique id prefix (4+ chars) works everywhere
bearcli get C44D09DC-... --meta              # with YAML-style frontmatter
bearcli get C44D09DC-... -r                  # rewrite attachment refs to absolute paths
bearcli get C44D09DC-... --redact-secrets    # secrets replaced by placeholders
bearcli open C44D09DC-...                    # open in the Bear app
bearcli browse                               # interactive: type to filter, Enter opens
bearcli stats                                # counts, words, top tags, notes per year
```

### Search

```sh
bearcli search "invoice" --tag work -n 5     # case-insensitive substring
bearcli search "quarterly planing" --fuzzy   # typo-tolerant, ranked by score
```

### Write

Writes go through Bear's x-callback-url API - the database itself is never
written. These launch the Bear app if needed.

```sh
bearcli create "Meeting notes" --text "agenda..." --tag work
echo "follow-up item" | bearcli note append C44D09DC-...
bearcli note rename C44D09DC-... "New title"
bearcli get C44D09DC-... | sed 's/foo/bar/' | bearcli note replace C44D09DC-...
bearcli note attach C44D09DC-... screenshot.png   # ≤500 KB
bearcli note archive C44D09DC-...
bearcli note trash C44D09DC-...
```

### Tags

```sh
bearcli tag list                             # all tags with note counts
bearcli note tag C44D09DC-... "work/ideas"   # add a tag to a note
bearcli note untag C44D09DC-... "work/ideas" # remove a tag from a note
bearcli tag rename old-name new-name         # across all notes
bearcli tag delete old-name                  # across all notes (asks first)
```

### Export

Every note becomes a self-contained directory - `<slug>/README.md` plus its
attachments - with a generated index, so GitHub renders the whole export as a
browsable tree.

Before anything is written, the notes are scanned for potential secrets
(token formats, key blocks, credential assignments, high-entropy strings);
findings block the export with a list of the affected notes. Override with
`--allow-secrets` (export as-is) or `--redact-secrets` (replace each secret
with a `[redacted: <rule>]` placeholder - notes in Bear are untouched).

> **⚠️ Warning** - detection and redaction are best-effort: a secret that
> reads like ordinary text (a password written as prose, an account number)
> will not be caught. Ideally, don't keep secrets in notes at all - use a
> password manager, or at least Bear's encrypted notes, which never leave
> the app.

```sh
bearcli export ~/bear-backup
bearcli export ~/bear-backup --sync          # only rewrite notes that changed
bearcli export ~/bear-backup --redact-secrets  # secrets become [redacted: <rule>]

# Mirror to a git repository (clone it first; use a *private* repo - these are
# your notes). Bear is the source of truth: remote or manual edits are kept in
# git history but overwritten in HEAD. Never force-pushes, never gets stuck.
git clone git@github.com:you/bear-notes.git ~/bear-notes
bearcli export ~/bear-notes --sync --push
```

## Scripting

Every listing takes `--format` / `-f`: `table` (default), `json`, or
tab-separated `text` built for pipes.

```sh
bearcli list -f json | jq -r '.[].title'
bearcli list -f text | cut -f1               # text is: id, modified, tags, status, title
```

Dates use ISO format (`2026-07-01` or `2026-07-01T14:30`). The database path
defaults to Bear's standard location and can be overridden with `--db` or the
`BEAR_DB_PATH` environment variable. Encrypted notes are listed but their
content cannot be read.

## Agent skill

An [Agent Skill](https://docs.claude.com/en/docs/agents-and-tools/agent-skills)
teaching AI agents (Claude Code, etc.) how to use `bearcli` ships in
[`skills/bear-notes`](skills/bear-notes/SKILL.md):

```sh
cp -r skills/bear-notes ~/.claude/skills/   # or a project's .claude/skills/
```

## Development

```sh
uv sync
uv run ruff format src/ && uv run ruff check src/
uv run ty check src/
uv run python scripts/check_docs.py          # docs must cover every command
```

Design notes and Bear database internals: [docs/IMPLEMENTATION.md](docs/IMPLEMENTATION.md).
Contributor/agent guidelines: [AGENTS.md](AGENTS.md).

## License

[MIT](LICENSE) · not affiliated with [Shiny Frog](https://shinyfrog.app)
