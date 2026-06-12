"""TDD: verify the MCP server builds and registers fl_ping."""

import asyncio


def test_server_builds_and_lists_tools():
    from fl_studio_mcp.server import build_server

    server = build_server()
    tools = asyncio.run(server.list_tools())
    tool_names = {t.name for t in tools}
    assert "fl_ping" in tool_names
