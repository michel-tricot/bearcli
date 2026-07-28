"""Agent-skill commands (the `skills` group)."""

from __future__ import annotations

import shutil
from importlib.resources import files
from pathlib import Path
from typing import Annotated

import typer

from bearcli.cli.common import console, skills_app

DEFAULT_SKILLS_DIR = Path.home() / ".claude" / "skills"


def _skill_dirs() -> dict[str, Path]:
    root = Path(str(files("bearcli") / "skills"))
    return {d.name: d for d in sorted(root.iterdir()) if (d / "SKILL.md").is_file()}


def _description(skill_dir: Path) -> str:
    for line in (skill_dir / "SKILL.md").read_text().splitlines():
        if line.startswith("description:"):
            return line.removeprefix("description:").strip()
    return ""


def _resolve(name: str | None) -> Path:
    skills = _skill_dirs()
    if name is None and len(skills) == 1:
        return next(iter(skills.values()))
    if name in skills:
        return skills[name]
    console.print(f"[red]Error:[/red] unknown skill {name!r}; available: {', '.join(skills)}")
    raise typer.Exit(1)


@skills_app.command("list")
def list_skills() -> None:
    """List the agent skills bundled with bearcli."""
    for name, skill_dir in _skill_dirs().items():
        print(f"{name}\t{_description(skill_dir)}")


@skills_app.command()
def show(
    name: Annotated[str | None, typer.Argument(help="Skill name (optional when only one ships).")] = None,
) -> None:
    """Print a skill's SKILL.md to stdout."""
    print((_resolve(name) / "SKILL.md").read_text(), end="")


@skills_app.command()
def install(
    name: Annotated[str | None, typer.Argument(help="Skill name (optional when only one ships).")] = None,
    directory: Annotated[
        Path,
        typer.Option("--dir", help="Skills directory to install into (e.g. a project's .claude/skills)."),
    ] = DEFAULT_SKILLS_DIR,
) -> None:
    """Install a skill into an agent's skills directory (overwrites an older copy)."""
    source = _resolve(name)
    target = directory / source.name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, dirs_exist_ok=True)
    console.print(f"Installed skill {source.name!r} to {target}")
