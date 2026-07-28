"""Export into a git worktree and push, converging without manual intervention.

The repository is a one-way mirror owned by bearcli: Bear is the source of
truth, and HEAD always converges to Bear's state. Nothing is ever lost —
local or remote edits are committed/merged before being overwritten, so they
remain in history — and nothing is ever force-pushed. Every failure mode
either self-heals (merge preferring local, reset to origin as last resort,
bounded push retries) or raises a clear error; there is no state that
requires manual git surgery to resume.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from bearcli.export import ExportResult, export_notes
from bearkit.db import BearDB


class GitError(RuntimeError):
    pass


def _git(dest: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(dest), *args], capture_output=True, text=True, check=False)


def _run(dest: Path, *args: str) -> str:
    proc = _git(dest, *args)
    if proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def _ok(dest: Path, *args: str) -> bool:
    return _git(dest, *args).returncode == 0


def _commit_if_dirty(dest: Path, message: str) -> None:
    _run(dest, "add", "-A")
    if not _ok(dest, "diff", "--cached", "--quiet"):
        _run(dest, "commit", "-m", message)


def export_and_push(
    db: BearDB,
    dest: Path,
    sync: bool = True,
    progress: Callable[[str], None] | None = None,
    redactions: dict[str, dict[str, str]] | None = None,
    attempts: int = 3,
) -> tuple[ExportResult, str]:
    def report(message: str) -> None:
        if progress is not None:
            progress(message)

    if not _ok(dest, "rev-parse", "--is-inside-work-tree"):
        raise GitError(f"{dest} is not a git repository — clone your notes repo (or `git init`) first")
    branch = _run(dest, "symbolic-ref", "--short", "HEAD")
    has_remote = _ok(dest, "remote", "get-url", "origin")

    last_error = "unknown"
    result = ExportResult()
    for _ in range(attempts):
        # Anything lying around (manual edits, a previous crashed run) gets
        # committed first: merges start from a clean tree and nothing is lost.
        _commit_if_dirty(dest, "bear export: local changes")

        full = not sync
        if has_remote:
            report("Fetching origin…")
            _run(dest, "fetch", "origin")
            if (
                _ok(dest, "rev-parse", "--verify", f"origin/{branch}")
                and _run(dest, "rev-list", "--count", f"HEAD..origin/{branch}") != "0"
            ):
                report("Integrating remote changes…")
                if not (
                    _ok(dest, "merge", "--ff-only", f"origin/{branch}")
                    or _ok(dest, "merge", "-X", "ours", "--no-edit", f"origin/{branch}")
                ):
                    _git(dest, "merge", "--abort")
                    _run(dest, "reset", "--hard", f"origin/{branch}")
                # Whatever was pulled, Bear's state must win in the worktree:
                # a full export re-asserts every note, not just changed ones.
                full = True

        result = export_notes(db, dest, sync=not full, progress=progress, redactions=redactions)

        report("Committing…")
        parts = [f"{result.written} written"]
        if result.removed:
            parts.append(f"{result.removed} removed")
        _commit_if_dirty(dest, "bear export: " + ", ".join(parts))

        if not has_remote:
            return result, "committed (no remote configured)"
        report("Pushing…")
        push = _git(dest, "push", "-u", "origin", branch)
        if push.returncode == 0:
            return result, "pushed"
        last_error = push.stderr.strip()  # racing push; refetch and retry

    raise GitError(f"push failed after {attempts} attempts: {last_error}")
