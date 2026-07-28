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
bearcli list --search "invoice"
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

# Attachments: Bear's markdown references them by bare filename; -r rewrites those
# references to the files' absolute paths on disk
bearcli get C44D09DC-... -r
```

Dates use ISO format (`2026-07-01` or `2026-07-01T14:30`).

The database path defaults to Bear's standard location and can be overridden with
`--db` or the `BEAR_DB_PATH` environment variable. Encrypted notes are listed
(marked 🔒) but their content cannot be read.
