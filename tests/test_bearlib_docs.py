"""The BEARLIB.md code samples must stay valid as the API evolves."""

import re
from pathlib import Path

DOC = Path(__file__).parent.parent / "docs" / "BEARLIB.md"


def blocks() -> list[str]:
    return re.findall(r"```python\n(.*?)```", DOC.read_text(), re.DOTALL)


def test_samples_found():
    assert len(blocks()) >= 15


def test_every_sample_compiles():
    for i, block in enumerate(blocks()):
        compile(block, f"BEARLIB.md block {i}", "exec")


def test_every_documented_name_exists():
    """Names imported from bearlib in samples must exist in the package."""
    import bearlib

    for block in blocks():
        for match in re.finditer(r"from bearlib import (.+)", block):
            for name in match.group(1).split(","):
                assert hasattr(bearlib, name.strip()), name

    import bearlib.markdown as md

    for block in blocks():
        for match in re.finditer(r"from bearlib\.markdown import (.+)", block):
            for name in match.group(1).split(","):
                assert hasattr(md, name.strip()), name


def test_pure_samples_run():
    """Blocks with no db/Bear dependency execute as written."""
    pure = [b for b in blocks() if "bearlib.markdown import" in b and "note" not in b]
    assert pure
    for block in pure:
        exec(compile(block, "BEARLIB.md pure block", "exec"), {})
