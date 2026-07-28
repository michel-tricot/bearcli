"""Fail if any CLI command is missing from README.md or docs/index.html.

Walks the Typer app so the command list can never drift from the code. Run by
CI; run locally with `uv run python scripts/check_docs.py`.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from bearcli.cli import app

ROOT = Path(__file__).parent.parent


def commands() -> list[tuple[str | None, str]]:
    grouped = []
    group_callbacks = set()
    for group in app.registered_groups:
        sub = group.typer_instance
        assert sub is not None and group.name
        for cmd in sub.registered_commands:
            grouped.append((group.name, cmd.name or cmd.callback.__name__))  # type: ignore[union-attr]
            group_callbacks.add(cmd.callback)
    top_level = [
        (None, cmd.name or cmd.callback.__name__)  # type: ignore[union-attr]
        for cmd in app.registered_commands
        if cmd.callback not in group_callbacks  # skip aliases of grouped commands
    ]
    return grouped + top_level


def main() -> int:
    readme = (ROOT / "README.md").read_text()
    page = (ROOT / "docs/index.html").read_text()

    missing = []
    for group, name in commands():
        full = f"bearcli {group} {name}" if group else f"bearcli {name}"
        # README must show the command invocation (grouped or alias form).
        if full not in readme and f"bearcli {name}" not in readme:
            missing.append(f"{full!r} is not mentioned in README.md")
        # The landing page's command table may combine verbs, so require the verb.
        if not re.search(rf"\b{re.escape(name)}\b", page):
            missing.append(f"{full!r} is not mentioned in docs/index.html")

    for problem in missing:
        print(f"ERROR: {problem}")
    if missing:
        print("\nUpdate README.md and docs/index.html when changing the CLI surface.")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
