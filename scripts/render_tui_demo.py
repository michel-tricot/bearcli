"""Render docs/tui.svg - a real screenshot of the TUI over fabricated notes.

Run with: uv run python scripts/render_tui_demo.py
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

from bearcli.tui import BearUI
from bearkit.db import Note


def note(note_id: str, title: str, text: str, tags: tuple[str, ...] = (), modified: str = "2026-07-27") -> Note:
    return Note(
        id=note_id,
        title=title,
        created=datetime.fromisoformat("2026-01-05"),
        modified=datetime.fromisoformat(modified),
        pinned=False,
        encrypted=False,
        archived=False,
        trashed=False,
        tags=list(tags),
        text=text,
    )


NOTES = [
    note(
        "A1B2C3D4-0000-0000-0000-000000000001",
        "Quarterly planning",
        "# Quarterly planning\n\n## Goals\n\n- Ship the onboarding revamp\n- Cut page load times **in half**\n"
        "- Hire two engineers\n\n## Notes\n\nBudget review is on *Thursday* - bring the `metrics.csv` export.\n",
        ("work", "planning"),
        "2026-07-27",
    ),
    note(
        "B2C3D4E5-0000-0000-0000-000000000002",
        "AWS sandbox credentials",
        "# AWS sandbox credentials\n\nAccess Key: AKIAIOSFODNN7EXAMPLE\n",
        ("infra",),
        "2026-07-25",
    ),
    note(
        "C3D4E5F6-0000-0000-0000-000000000003",
        "Reading list",
        "# Reading list\n\n- The Design of Everyday Things\n- Thinking in Systems\n",
        ("books",),
        "2026-07-21",
    ),
    note(
        "D4E5F6A7-0000-0000-0000-000000000004",
        "Sourdough starter log",
        "# Sourdough starter log\n\nDay 6: doubled in four hours.\n",
        ("home",),
        "2026-07-18",
    ),
    note(
        "E5F6A7B8-0000-0000-0000-000000000005",
        "Trip ideas",
        "# Trip ideas\n\n- Kyoto in autumn\n- Dolomites traverse\n",
        ("travel",),
        "2026-07-12",
    ),
]


def _strip_chrome(svg: str) -> str:
    """Remove Textual's window chrome so the site can supply its own.

    Drops the rounded frame rect, the title text, and the traffic-light
    circles, then re-crops the viewBox to the terminal content.
    """
    import re

    svg = re.sub(r'<rect[^>]*rx="8"/>', "", svg, count=1)
    svg = re.sub(r'<text class="terminal-\d+-title"[^>]*>[^<]*</text>', "", svg, count=1)
    svg = re.sub(r'<g transform="translate\(26,22\)">\s*(?:<circle[^>]*/>\s*)+</g>', "", svg, count=1)
    viewbox = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg)
    content = re.search(r'<g transform="translate\((\d+), (\d+)\)"', svg)
    assert viewbox and content
    width = float(viewbox.group(1)) - 2 * int(content.group(1))
    height = float(viewbox.group(2)) - int(content.group(2))
    svg = svg.replace(viewbox.group(0), f'viewBox="0 0 {width} {height}"', 1)
    svg = svg.replace(content.group(0), '<g transform="translate(0, 0)"', 1)
    return svg


async def main() -> None:
    app = BearUI(list(NOTES))
    async with app.run_test(size=(118, 30)) as pilot:
        await pilot.pause(1.0)  # let the secrets scan land
        svg = _strip_chrome(app.export_screenshot())
    out = Path(__file__).parent.parent / "docs" / "tui.svg"
    out.write_text(svg)
    print(f"wrote {out} ({len(svg) // 1024} KB)")


if __name__ == "__main__":
    asyncio.run(main())
