"""The `doctor` command: diagnose PATH conflicts, database access, MCP wiring."""

from __future__ import annotations

import json
import os
import re
import subprocess
from importlib.metadata import version
from pathlib import Path

import typer

from bearcli.cli.common import DbPathOption, app, console
from bearcli.cli.mcp import _clients
from bearkit import Bear
from bearkit.db import DEFAULT_DB_PATH

# What our binary prints for --version; Bear's official CLI (same name) does not.
_OURS = re.compile(r"^bearcli \S+ \(bearkit ")


def _ok(message: str) -> None:
    console.print(f"[green]✓[/green] {message}")


def _warn(message: str) -> None:
    console.print(f"[yellow]![/yellow] {message}")


def _fail(message: str) -> None:
    console.print(f"[red]✗[/red] {message}")


def _path_copies() -> list[Path]:
    """Every `bearcli` executable on PATH, in lookup order, deduplicated."""
    seen: set[Path] = set()
    copies = []
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(entry) / "bearcli"
        if not (entry and candidate.is_file() and os.access(candidate, os.X_OK)):
            continue
        resolved = candidate.resolve()
        if resolved not in seen:
            seen.add(resolved)
            copies.append(candidate)
    return copies


def _is_ours(exe: Path) -> bool:
    try:
        result = subprocess.run([str(exe), "--version"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return _OURS.match(result.stdout.strip()) is not None


def _check_path() -> None:
    copies = _path_copies()
    if not copies:
        _warn("no `bearcli` on PATH — shells can't run it (MCP configs use absolute paths and still work)")
        return
    if _is_ours(copies[0]):
        _ok(f"`bearcli` on PATH is this CLI ({copies[0]})")
        for other in copies[1:]:
            if not _is_ours(other):
                console.print(f"  Another `bearcli` (Bear's official CLI?) is shadowed at {other} — no conflict.")
        return
    _warn(f"`bearcli` on PATH is a different tool ({copies[0]}) — likely Bear's official CLI")
    ours = next((c for c in copies[1:] if _is_ours(c)), None)
    if ours is not None:
        console.print(f'  Fix: in your shell profile, put this CLI first:  export PATH="{ours.parent}:$PATH"')
    else:
        console.print("  This CLI is not on PATH; add its bin directory, or invoke it by absolute path.")
    console.print("  MCP configs are unaffected: `bearcli mcp install` writes absolute paths.")


def _check_bear_app() -> None:
    locations = [
        Path("/Applications/Bear.app"),
        Path("/Applications/Setapp/Bear.app"),
        Path.home() / "Applications/Bear.app",
    ]
    if any(p.exists() for p in locations):
        _ok("Bear app is installed")
    else:
        _warn("Bear.app not found in /Applications — reading may work, but writes need the Bear app")


def _check_database(db_path: Path) -> bool:
    try:
        os.stat(db_path)
    except PermissionError:
        _fail(f"macOS denied access to the Bear database ({db_path})")
        console.print("  Grant access in System Settings → Privacy & Security → Files & Folders,")
        console.print("  or give this app Full Disk Access, then retry.")
        return False
    except FileNotFoundError:
        _fail(f"Bear database not found at {db_path}")
        console.print("  Launch Bear at least once, or point --db / BEAR_DB_PATH at the database.")
        return False
    with Bear(db_path) as bear:
        notes = bear.list_notes(include_trashed=True, include_archived=True)
        tags = bear.list_tags()
    _ok(f"database opens read-only: {len(notes)} notes, {len(tags)} tags")
    return True


def _check_mcp_configs() -> None:
    for client in _clients():
        if client.config_path is None:
            continue
        path = Path.home() / client.config_path
        if not path.exists():
            continue
        try:
            config = json.loads(path.read_text() or "{}")
        except json.JSONDecodeError:
            _warn(f"{client.label}: {path} is not valid JSON")
            continue
        entry = config.get(client.servers_key, {}).get("bear")
        if not isinstance(entry, dict):
            continue
        exe = Path(str(entry.get("command", "")))
        if exe.is_file():
            _ok(f"{client.label}: MCP server wired to {exe}")
        else:
            _warn(f"{client.label}: MCP entry points at a missing binary ({exe})")
            console.print(f"  Fix: rerun `bearcli mcp install {client.key}` (upgrades can move the binary).")


@app.command(rich_help_panel="Goodies")
def doctor(db_path: DbPathOption = DEFAULT_DB_PATH) -> None:
    """Diagnose the setup: PATH conflicts, Bear app, database access, MCP wiring."""
    _ok(f"bearcli {version('bearcli')} (bearkit {version('bearkit')})")
    _check_path()
    _check_bear_app()
    healthy = _check_database(db_path)
    _check_mcp_configs()
    if not healthy:
        raise typer.Exit(1)
