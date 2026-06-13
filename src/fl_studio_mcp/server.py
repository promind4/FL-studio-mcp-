"""MCP server entry point. Exposes FL Studio control tools to the LLM."""

from __future__ import annotations

import os
import socket
import threading

from fastmcp import FastMCP

from . import protocol
from .client import BridgeClient, BridgeUnavailable

_client = None
_client_lock = threading.Lock()


def _make_client():
    """Pick the bridge transport.

    FLMCP_TRANSPORT=tcp|midi forces one; default "auto" uses TCP when the
    bridge port answers (FL builds that allow sockets) and falls back to
    MIDI SysEx via loopMIDI (FL Studio 2025, whose sandbox blocks sockets).
    """
    transport = os.environ.get("FLMCP_TRANSPORT", "auto").lower()
    if transport == "midi":
        from .midi_transport import MidiBridgeClient
        return MidiBridgeClient()
    if transport == "tcp":
        return BridgeClient()
    try:
        probe = socket.create_connection((protocol.HOST, protocol.PORT),
                                         timeout=0.5)
        probe.close()
        return BridgeClient()
    except OSError:
        from .midi_transport import MidiBridgeClient
        return MidiBridgeClient()


def get_client():
    # Double-checked: FastMCP runs sync tools in worker threads, so two
    # concurrent tool calls could otherwise both construct a client.
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = _make_client()
    return _client


def build_server() -> FastMCP:
    mcp = FastMCP("fl-studio-mcp")

    from .tools import export, mixer, plugin_loader
    from .tools import plugins as plugin_tools

    # --- Connectivity ---------------------------------------------------

    @mcp.tool()
    def fl_ping() -> dict:
        """Check that FL Studio is running and the bridge is reachable."""
        try:
            result = get_client().call("meta.ping")
            return {"connected": True, "bridge": result}
        except BridgeUnavailable as exc:
            return {"connected": False, "error": str(exc)}

    # --- Plugin browser ---------------------------------------------------

    @mcp.tool()
    def fl_list_available_plugins() -> dict:
        """List all plugins installed in FL Studio's plugin database.

        Reads the on-disk database (no FL Studio round-trip required).
        Returns name, type (effect/generator) and format (fruity/vst/vst3)
        for every installed plugin.

        Example result:
          {"total": 243, "plugins": [
            {"name": "Pro-Q 3", "type": "effect", "format": "vst3"},
            {"name": "Serum", "type": "generator", "format": "vst"},
            ...
          ]}
        """
        return plugin_tools.list_available_plugins()

    # --- Plugin parameters ------------------------------------------------

    @mcp.tool()
    def fl_discover_plugin_params(track: int, slot: int,
                                   location: str = "mixer") -> dict:
        """Full parameter map (index, name, value) of the plugin at
        (track, slot). Cached per plugin name, so the first call on a big
        plugin is slow but repeats are instant.
        location: "mixer" (default) for FX chain plugins, "channel" for
        channel-rack instruments."""
        return plugin_tools.discover_params(get_client(), track, slot,
                                            location=location)

    @mcp.tool()
    def fl_set_plugin_params(track: int, slot: int, changes: list[dict],
                              location: str = "mixer") -> dict:
        """Batch-apply plugin parameter changes in one round-trip.
        changes: [{"index": int, "value": float 0.0..1.0 normalized}].
        location: "mixer" (default) for FX chain plugins, "channel" for
        channel-rack instruments."""
        return plugin_tools.set_params(get_client(), track, slot, changes,
                                       location=location)

    @mcp.tool()
    def fl_get_plugin_param(track: int, slot: int, index: int,
                             location: str = "mixer") -> dict:
        """Read one plugin parameter's current value (normalized 0.0..1.0)
        plus its display string.
        location: "mixer" (default) for FX chain plugins, "channel" for
        channel-rack instruments."""
        return plugin_tools.get_param(get_client(), track, slot, index,
                                      location=location)

    # --- Mixer ------------------------------------------------------------

    @mcp.tool()
    def fl_set_track_volume(track: int, volume: float) -> dict:
        """Set mixer track volume. Linear gain 0.0..1.0 where 0.8 = 0 dB
        (FL Studio default). track 0 is the Master."""
        return mixer.set_volume(get_client(), track, volume)

    @mcp.tool()
    def fl_set_track_pan(track: int, pan: float) -> dict:
        """Set mixer track pan: -1.0 (full left) .. 0.0 (center) .. 1.0
        (full right)."""
        return mixer.set_pan(get_client(), track, pan)

    @mcp.tool()
    def fl_set_track_mute(track: int, muted: bool) -> dict:
        """Mute (True) or unmute (False) a mixer track."""
        return mixer.set_mute(get_client(), track, muted)

    @mcp.tool()
    def fl_set_track_solo(track: int, solo: bool) -> dict:
        """Solo (True) or unsolo (False) a mixer track."""
        return mixer.set_solo(get_client(), track, solo)

    @mcp.tool()
    def fl_get_track_info(track: int) -> dict:
        """Track name, volume, pan, mute/solo state and loaded FX plugins
        for one mixer track."""
        return mixer.get_track_info(get_client(), track)

    @mcp.tool()
    def fl_list_tracks(include_empty: bool = False) -> dict:
        """Overview of all mixer tracks. By default skips unnamed empty
        Insert tracks; pass include_empty=True to list everything."""
        return mixer.list_tracks(get_client(), include_empty)

    # --- Plugin loading -----------------------------------------------------

    @mcp.tool()
    def fl_probe_plugin_loading() -> dict:
        """Check which plugin-loading strategies this FL Studio build
        supports. Run once before trying to load plugins."""
        return plugin_loader.probe_capabilities(get_client())

    @mcp.tool()
    def fl_wait_for_plugin(track: int, slot: int, expected: str,
                           timeout: float = 60.0) -> dict:
        """Assisted plugin insertion: after asking the user to insert a
        plugin at (mixer track, slot), poll until a plugin whose name
        contains `expected` appears, or timeout (seconds)."""
        return plugin_loader.wait_for_plugin(get_client(), track, slot,
                                             expected, timeout)

    # --- Audio export -------------------------------------------------------

    @mcp.tool()
    def fl_probe_export() -> dict:
        """Check which audio export / disk-recording strategies this FL
        Studio build supports. Run once before exporting audio."""
        return export.probe_export_capabilities(get_client())

    @mcp.tool()
    def fl_resolve_track_audio(channel: int) -> dict:
        """Find an analyzable audio file for a channel-rack channel
        (source-file strategy, pre-effects). Returns the path if the
        sample file exists on disk."""
        return export.resolve_track_audio(get_client(), channel)

    @mcp.tool()
    def fl_set_record_arm(track: int, armed: bool = True) -> dict:
        """Arm (True) or disarm (False) a mixer track for disk recording
        (post-effects audio). Returns the WAV path FL will write while
        recording, when the running build exposes it."""
        return export.set_record_arm(get_client(), track, armed)

    return mcp


def main():
    build_server().run()
