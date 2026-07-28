# bearcli

Read notes from the [Bear](https://bear.app) note app from the command line.

## Install / run

```sh
uv run bearcli --help
```

## Usage

```sh
# List the 20 most recently modified notes
bearcli list

# Limits and filters
bearcli list --limit 5
bearcli list --tag work                      # includes nested tags like work/ideas
bearcli list --modified-after 2026-07-01
bearcli list --created-after 2026-01-01 --created-before 2026-07-01
bearcli list --only pinned                   # or: encrypted, trashed, archived
bearcli list --all --trashed --archived
bearcli list --ids                           # only note identifiers, one per line

# Output formats (--format / -f): table (default), json, text
bearcli list -f json | jq -r '.[].title'
bearcli list -f text | cut -f1               # text is tab-separated: id, modified, tags, status, title
bearcli list -f text | awk -F'\t' '$3 ~ /work/ {print $5}'

# Print a note's content by identifier
bearcli get C44D09DC-7F0E-43BB-BEB8-67E3A389A448
bearcli get C44D09DC-... --meta              # with YAML-style frontmatter
bearcli get C44D09DC-... -f json             # metadata + content + attachments as JSON

# Search titles, tags, and note text (case-insensitive substring)
bearcli search "invoice" --tag work -n 5
bearcli search "quarterly planing" --fuzzy    # typo-tolerant, ranked by score

# Attachments: Bear's markdown references them by bare filename; -r rewrites those
# references to the files' absolute paths on disk
bearcli get C44D09DC-... -r

# Export all notes (including archived) as self-contained directories:
# <slug>/README.md + <slug>/attachments/, with links rewritten to relative paths
# (GitHub renders each note when you open its folder)
bearcli export ~/bear-backup
bearcli export ~/bear-backup --sync          # only rewrite notes that changed

# Write actions (via Bear's x-callback-url API — the database itself is never
# written; these launch the Bear app if needed)
bearcli create "Meeting notes" --text "agenda..." --tag work
echo "follow-up item" | bearcli append C44D09DC-...
bearcli archive C44D09DC-...
bearcli trash C44D09DC-...

# Tags
bearcli tags                                 # all tags with note counts
bearcli list --tag work                      # notes with a tag (incl. nested)
bearcli tag C44D09DC-... "work/ideas"        # add a tag to a note
bearcli untag C44D09DC-... "work/ideas"      # remove a tag from a note

# Open a note in the Bear app
bearcli open C44D09DC-...

# More write operations
bearcli attach C44D09DC-... screenshot.png   # add an attachment (≤500 KB)
bearcli rename C44D09DC-... "New title"
bearcli get C44D09DC-... | sed 's/foo/bar/' | bearcli replace C44D09DC-...
bearcli rename-tag old-name new-name         # across all notes
bearcli delete-tag old-name                  # across all notes (asks first)
```

Dates use ISO format (`2026-07-01` or `2026-07-01T14:30`).

The database path defaults to Bear's standard location and can be overridden with
`--db` or the `BEAR_DB_PATH` environment variable. Encrypted notes are listed
but their content cannot be read.

How it works: [docs/IMPLEMENTATION.md](docs/IMPLEMENTATION.md). Contributor/agent
guidelines: [AGENTS.md](AGENTS.md).
