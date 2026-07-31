"""`doctor` diagnoses PATH conflicts, database access, and MCP wiring."""

import json
import sqlite3

from typer.testing import CliRunner

from bearcli.cli import app

runner = CliRunner()


def test_doctor_healthy(populated, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    populated.conn.commit()
    result = runner.invoke(app, ["doctor", "--db", str(populated.path)])
    assert result.exit_code == 0
    assert "5 notes" in result.stdout and "3 tags" in result.stdout


def test_doctor_missing_db_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    result = runner.invoke(app, ["doctor", "--db", str(tmp_path / "nope.sqlite")])
    assert result.exit_code == 1
    assert "not found" in result.stdout


def test_doctor_unopenable_db_fails_cleanly(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("COLUMNS", "400")  # keep long diagnostic lines unwrapped
    result = runner.invoke(app, ["doctor", "--db", str(tmp_path)])  # a directory: stat ok, open fails
    assert result.exit_code == 1
    assert "could not open" in result.stdout


def test_doctor_non_bear_db_fails_cleanly(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("COLUMNS", "400")
    other = tmp_path / "other.sqlite"
    sqlite3.connect(other).executescript("CREATE TABLE t (x);").close()
    result = runner.invoke(app, ["doctor", "--db", str(other)])
    assert result.exit_code == 1
    assert "does not look like a Bear database" in result.stdout


def test_doctor_flags_official_cli_shadowing_ours(populated, tmp_path, monkeypatch):
    populated.conn.commit()
    official = tmp_path / "official" / "bearcli"
    official.parent.mkdir()
    official.write_text("#!/bin/sh\necho 'Bear CLI 2.0'\n")
    official.chmod(0o755)
    ours = tmp_path / "ours" / "bearcli"
    ours.parent.mkdir()
    ours.write_text("#!/bin/sh\necho 'bearcli 9.9.9 (bearkit 9.9.9)'\n")
    ours.chmod(0o755)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", f"{official.parent}:{ours.parent}")
    monkeypatch.setenv("COLUMNS", "400")  # keep long Fix lines unwrapped
    result = runner.invoke(app, ["doctor", "--db", str(populated.path)])
    assert result.exit_code == 0  # a warning, not a failure
    assert "different tool" in result.stdout
    assert f'"{ours.parent}:$PATH"' in result.stdout


def test_doctor_reports_shadowed_official_cli_as_harmless(populated, tmp_path, monkeypatch):
    populated.conn.commit()
    ours = tmp_path / "ours" / "bearcli"
    ours.parent.mkdir()
    ours.write_text("#!/bin/sh\necho 'bearcli 9.9.9 (bearkit 9.9.9)'\n")
    ours.chmod(0o755)
    official = tmp_path / "official" / "bearcli"
    official.parent.mkdir()
    official.write_text("#!/bin/sh\necho 'Bear CLI 2.0'\n")
    official.chmod(0o755)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", f"{ours.parent}:{official.parent}")
    result = runner.invoke(app, ["doctor", "--db", str(populated.path)])
    assert result.exit_code == 0
    assert "is this CLI" in result.stdout and "no conflict" in result.stdout


def test_doctor_flags_stale_mcp_entry(populated, tmp_path, monkeypatch):
    populated.conn.commit()
    monkeypatch.setenv("HOME", str(tmp_path))
    config = tmp_path / "Library/Application Support/Claude/claude_desktop_config.json"
    config.parent.mkdir(parents=True)
    stale = {"command": str(tmp_path / "gone" / "bearcli"), "args": ["mcp", "run"]}
    config.write_text(json.dumps({"mcpServers": {"bear": stale}}))
    result = runner.invoke(app, ["doctor", "--db", str(populated.path)])
    assert result.exit_code == 0
    assert "missing binary" in result.stdout
    assert "mcp install" in result.stdout
