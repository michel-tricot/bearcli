"""The MCP server serves notes through real tool calls."""

import asyncio

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from bearcli.mcpserver import build_server

EXPECTED_TOOLS = {
    "list_notes",
    "get_note",
    "search_notes",
    "list_tags",
    "create_note",
    "append_to_note",
    "rename_note",
    "add_tag",
    "remove_tag",
    "trash_note",
    "archive_note",
    "open_note_in_bear",
}


def call(server, name, arguments):
    async def _call():
        async with Client(server) as client:
            return (await client.call_tool(name, arguments)).data

    return asyncio.run(_call())


def test_exposes_expected_tools(populated):
    server = build_server(populated.path)

    async def _names():
        async with Client(server) as client:
            return {t.name for t in await client.list_tools()}

    assert asyncio.run(_names()) == EXPECTED_TOOLS


def test_list_and_get(populated):
    populated.conn.commit()
    server = build_server(populated.path)
    notes = call(server, "list_notes", {})
    assert {n["title"] for n in notes} == {"Groceries", "Project plan", "Vault"}
    note = call(server, "get_note", {"note_id": "AAAA1111"})
    assert note["title"] == "Groceries" and "milk" in note["text"]


def test_get_note_redacts_by_default(populated):
    populated.add_note("SEC00000-0000-0000-0000-000000000009", "Keys", text="# Keys\nkey AKIAIOSFODNN7EXAMPLE\n")
    populated.conn.commit()
    server = build_server(populated.path)
    note = call(server, "get_note", {"note_id": "SEC00000"})
    assert "AKIAIOSFODNN7EXAMPLE" not in note["text"] and "[redacted:" in note["text"]
    raw = call(server, "get_note", {"note_id": "SEC00000", "redact_secrets": False})
    assert "AKIAIOSFODNN7EXAMPLE" in raw["text"]


def test_search_and_tags(populated):
    populated.conn.commit()
    server = build_server(populated.path)
    hits = call(server, "search_notes", {"query": "milk"})
    assert [h["title"] for h in hits] == ["Groceries"] and hits[0]["snippet"]
    tags = call(server, "list_tags", {})
    assert {"tag": "home", "notes": 1} in tags


def test_unknown_note_is_a_tool_error(populated):
    populated.conn.commit()
    server = build_server(populated.path)

    async def _call():
        async with Client(server) as client:
            await client.call_tool("get_note", {"note_id": "ZZZZ9999"})

    with pytest.raises(ToolError, match="ZZZZ9999"):
        asyncio.run(_call())


def test_every_tool_has_a_description(populated):
    server = build_server(populated.path)

    async def _tools():
        async with Client(server) as client:
            return await client.list_tools()

    for spec in asyncio.run(_tools()):
        assert spec.description, spec.name
