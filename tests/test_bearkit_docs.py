"""The BEARKIT.md code samples must stay valid as the API evolves."""

import re
from pathlib import Path

DOC = Path(__file__).parent.parent / "docs" / "BEARKIT.md"


def blocks() -> list[str]:
    return re.findall(r"```python\n(.*?)```", DOC.read_text(), re.DOTALL)


def test_samples_found():
    assert len(blocks()) >= 15


def test_every_sample_compiles():
    for i, block in enumerate(blocks()):
        compile(block, f"BEARKIT.md block {i}", "exec")


def test_every_documented_name_exists():
    """Names imported from bearkit in samples must exist in the package."""
    import bearkit

    for block in blocks():
        for match in re.finditer(r"from bearkit import (.+)", block):
            for name in match.group(1).split(","):
                assert hasattr(bearkit, name.strip()), name

    import bearkit.markdown as md

    for block in blocks():
        for match in re.finditer(r"from bearkit\.markdown import (.+)", block):
            for name in match.group(1).split(","):
                assert hasattr(md, name.strip()), name


def test_pure_samples_run():
    """Blocks with no db/Bear dependency execute as written."""
    pure = [b for b in blocks() if "bearkit.markdown import" in b and "note" not in b]
    assert pure
    for block in pure:
        exec(compile(block, "BEARKIT.md pure block", "exec"), {})


def test_samples_pass_project_lint_and_format(tmp_path):
    import subprocess

    paths = []
    for i, block in enumerate(blocks()):
        p = tmp_path / f"sample_{i}.py"
        p.write_text(block)
        paths.append(str(p))
    root = str(DOC.parent.parent)
    for args in (["check", "--no-cache"], ["format", "--check"]):
        result = subprocess.run(
            ["uv", "run", "ruff", *args, "--config", f"{root}/pyproject.toml", *paths],
            capture_output=True,
            text=True,
            cwd=root,
        )
        assert result.returncode == 0, result.stdout + result.stderr
