"""Write actions via Bear's x-callback-url scheme.

The database stays strictly read-only; all mutations go through Bear's own
URL API (which launches the app if needed). Calls are fire-and-forget — Bear
gives no result back — so callers verify outcomes by re-reading the database.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from urllib.parse import quote, urlencode

BASE_URL = "bear://x-callback-url/"


def call_bear(action: str, **params: str | None) -> None:
    query = urlencode({k: v for k, v in params.items() if v is not None}, quote_via=quote)
    # -g keeps Bear in the background instead of stealing focus.
    subprocess.run(["open", "-g", f"{BASE_URL}{action}?{query}"], check=True)


def create_note(title: str, text: str | None = None, tags: list[str] | None = None) -> None:
    call_bear(
        "create",
        title=title,
        text=text,
        tags=",".join(tags) if tags else None,
        open_note="no",
        show_window="no",
    )


def add_text(note_id: str, text: str, mode: str = "append") -> None:
    call_bear("add-text", id=note_id, text=text, mode=mode, open_note="no", show_window="no")


def trash_note(note_id: str) -> None:
    call_bear("trash", id=note_id, show_window="no")


def archive_note(note_id: str) -> None:
    call_bear("archive", id=note_id, show_window="no")


def wait_for(predicate: Callable[[], bool], timeout: float = 6.0, interval: float = 0.3) -> bool:
    """Poll until predicate() is true; Bear applies URL actions asynchronously."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()
