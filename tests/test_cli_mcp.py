"""`mcp install` configures MCP clients."""

import json
from pathlib import Path

from typer.testing import CliRunner

from bearcli.cli import app

runner = CliRunner()

DESKTOP_CONFIG = "Library/Application Support/Claude/claude_desktop_config.json"


def test_install_creates_claude_desktop_config(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    result = runner.invoke(app, ["mcp", "install", "claude-desktop"])
    assert result.exit_code == 0
    config = json.loads((tmp_path / DESKTOP_CONFIG).read_text())
    server = config["mcpServers"]["bear"]
    assert server["args"] == ["mcp", "run"] and Path(server["command"]).name == "bearcli"


def test_install_merges_and_backs_up(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    path = tmp_path / DESKTOP_CONFIG
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"theme": "dark", "mcpServers": {"other": {"command": "x"}}}))
    result = runner.invoke(app, ["mcp", "install", "claude-desktop"])
    assert result.exit_code == 0
    config = json.loads(path.read_text())
    assert config["theme"] == "dark" and set(config["mcpServers"]) == {"other", "bear"}
    assert path.with_name(path.name + ".bak").exists()


def test_install_vscode_uses_servers_key_and_stdio(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    result = runner.invoke(app, ["mcp", "install", "vscode"])
    assert result.exit_code == 0
    config = json.loads((tmp_path / "Library/Application Support/Code/User/mcp.json").read_text())
    assert config["servers"]["bear"]["type"] == "stdio"


def test_install_manual_client_prints_instructions(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    result = runner.invoke(app, ["mcp", "install", "zed"])
    assert result.exit_code == 0
    assert "context_servers" in result.stdout
    assert not any(tmp_path.iterdir())  # nothing written


def test_install_unknown_client_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    result = runner.invoke(app, ["mcp", "install", "nope"])
    assert result.exit_code == 2 and "claude-desktop" in result.stdout


def test_install_unparseable_config_shows_manual_entry(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    path = tmp_path / DESKTOP_CONFIG
    path.parent.mkdir(parents=True)
    path.write_text("{not json")
    result = runner.invoke(app, ["mcp", "install", "claude-desktop"])
    assert result.exit_code == 1 and "mcpServers" in result.stdout
    assert path.read_text() == "{not json"  # untouched
