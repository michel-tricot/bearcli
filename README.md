# bearcli

Read notes from the [Bear](https://bear.app) note app from the command line.

## Install / run

```sh
uv run bearcli --help
```

## Usage

```sh
# Notes — also available as top-level shortcuts: list, search, get, open, create
bearcli note list                            # 20 most recently modified
bearcli note list --limit 5 --tag work       # filters: tag (incl. nested), dates...
bearcli note list --modified-after 2026-07-01
bearcli note list --only pinned              # or: encrypted, trashed, archived
bearcli note list --all --trashed --archived
bearcli note list --ids                      # only identifiers, one per line

# Search titles, tags, and note text (case-insensitive substring)
bearcli search "invoice" --tag work -n 5
bearcli search "quarterly planing" --fuzzy   # typo-tolerant, ranked by score

# Output formats (--format / -f): table (default), json, text
bearcli list -f json | jq -r '.[].title'
bearcli list -f text | cut -f1               # text is tab-separated: id, modified, tags, status, title

# Read a note
bearcli get C44D09DC-7F0E-43BB-BEB8-67E3A389A448
bearcli get C44D09DC-... --meta              # with YAML-style frontmatter
bearcli get C44D09DC-... -f json             # metadata + content + attachments as JSON
bearcli get C44D09DC-... -r                  # rewrite attachment refs to absolute paths
bearcli open C44D09DC-...                    # open in the Bear app

# Write actions (via Bear's x-callback-url API — the database itself is never
# written; these launch the Bear app if needed)
bearcli create "Meeting notes" --text "agenda..." --tag work
echo "follow-up item" | bearcli note append C44D09DC-...
bearcli note rename C44D09DC-... "New title"
bearcli get C44D09DC-... | sed 's/foo/bar/' | bearcli note replace C44D09DC-...
bearcli note attach C44D09DC-... screenshot.png   # ≤500 KB
bearcli note archive C44D09DC-...
bearcli note trash C44D09DC-...
bearcli note tag C44D09DC-... "work/ideas"   # add a tag to a note
bearcli note untag C44D09DC-... "work/ideas" # remove a tag from a note

# Tags
bearcli tag list                             # all tags with note counts
bearcli tag notes work                       # notes carrying a tag (incl. nested)
bearcli tag rename old-name new-name         # across all notes
bearcli tag delete old-name                  # across all notes (asks first)

# Export all notes (including archived) as self-contained directories:
# <slug>/README.md + <slug>/attachments/, with links rewritten to relative paths
# (GitHub renders each note when you open its folder)
bearcli export ~/bear-backup
bearcli export ~/bear-backup --sync          # only rewrite notes that changed
```

Dates use ISO format (`2026-07-01` or `2026-07-01T14:30`).

The database path defaults to Bear's standard location and can be overridden with
`--db` or the `BEAR_DB_PATH` environment variable. Encrypted notes are listed
but their content cannot be read.

How it works: [docs/IMPLEMENTATION.md](docs/IMPLEMENTATION.md). Contributor/agent
guidelines: [AGENTS.md](AGENTS.md).
