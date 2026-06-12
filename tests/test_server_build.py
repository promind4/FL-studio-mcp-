"""TDD: verify the MCP server builds and registers all v0 tools."""

import asyncio

EXPECTED_TOOLS = {
    "fl_ping",
    "fl_discover_plugin_params",
    "fl_set_plugin_params",
    "fl_get_plugin_param",
    "fl_set_track_volume",
    "fl_set_track_pan",
    "fl_set_track_mute",
    "fl_set_track_solo",
    "fl_get_track_info",
    "fl_list_tracks",
    "fl_probe_plugin_loading",
    "fl_wait_for_plugin",
    "fl_probe_export",
    "fl_resolve_track_audio",
    "fl_set_record_arm",
}


def test_server_builds_and_lists_tools():
    from fl_studio_mcp.server import build_server

    server = build_server()
    tools = asyncio.run(server.list_tools())
    tool_names = {t.name for t in tools}
    assert EXPECTED_TOOLS <= tool_names
