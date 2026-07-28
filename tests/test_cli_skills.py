"""The `skills` group serves the bundled agent skill."""

from typer.testing import CliRunner

from bearcli.cli import app

runner = CliRunner()


def test_list_names_the_bundled_skill():
    result = runner.invoke(app, ["skills", "list"])
    assert result.exit_code == 0
    assert result.stdout.startswith("bear-notes\t")


def test_show_prints_the_skill(tmp_path):
    result = runner.invoke(app, ["skills", "show"])
    assert result.exit_code == 0
    assert result.stdout.startswith("---\nname: bear-notes")


def test_install_copies_into_directory(tmp_path):
    result = runner.invoke(app, ["skills", "install", "--dir", str(tmp_path)])
    assert result.exit_code == 0
    installed = tmp_path / "bear-notes" / "SKILL.md"
    assert installed.is_file() and "bearcli" in installed.read_text()
    # Re-install overwrites (the upgrade path).
    assert runner.invoke(app, ["skills", "install", "--dir", str(tmp_path)]).exit_code == 0


def test_unknown_skill_errors():
    result = runner.invoke(app, ["skills", "show", "nope"])
    assert result.exit_code == 1
