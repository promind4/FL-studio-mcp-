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

    from .tools import export, mixer, plugin_loader, fst_loader
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

    # --- Plugin slot management --------------------------------------------

    @mcp.tool()
    def fl_get_preset_count(track: int, slot: int) -> dict:
        """Return the number of presets available for the plugin at (track, slot).
        Use before fl_load_preset to know the valid index range."""
        return get_client().call("plugins.presetCount", {
            "index": track, "slot": slot, "location": "mixer",
        })

    @mcp.tool()
    def fl_load_preset(track: int, slot: int, preset_index: int) -> dict:
        """Load a plugin preset by index (0-based).
        Loading a factory preset is the only reliable way to activate
        Pro-Q 3 / FabFilter bands without mouse interaction — the preset
        system sets the full plugin state including 'Band N Used' flags.
        After loading, override individual params with fl_set_plugin_params."""
        return get_client().call("plugins.setPreset", {
            "index": track, "slot": slot, "location": "mixer",
            "preset": preset_index,
        })

    @mcp.tool()
    def fl_next_preset(track: int, slot: int) -> dict:
        """Advance the plugin at (track, slot) to the next preset."""
        return get_client().call("plugins.nextPreset", {
            "index": track, "slot": slot, "location": "mixer",
        })

    @mcp.tool()
    def fl_set_plugin_param_rec(track: int, slot: int,
                                param: int, value: float) -> dict:
        """Set a plugin parameter via general.processRECEvent (FL REC automation bus).
        Use this instead of fl_set_plugin_params when the parameter is
        non-automatable via setParamValue — specifically Pro-Q 3 'Band N Used'
        (param indices 0, 13, 26, 39, 52, 65, 78, 91).
        value: normalized 0.0..1.0 (1.0 = band active)."""
        return get_client().call("plugins.setParamREC", {
            "index": track, "slot": slot, "location": "mixer",
            "param": param, "value": value,
        })

    @mcp.tool()
    def fl_set_slot_enabled(track: int, slot: int, enabled: bool,
                             location: str = "mixer") -> dict:
        """Enable (True) or bypass/disable (False) an FX slot green button.
        location: 'mixer' (default) for FX chain plugins."""
        return get_client().call("plugins.setSlotEnabled", {
            "index": track, "slot": slot, "location": location,
            "enabled": enabled,
        })

    @mcp.tool()
    def fl_remove_plugin(track: int, slot: int) -> dict:
        """Remove the plugin loaded in an FX slot (clears the slot).
        track: mixer track index. slot: FX chain slot 0-9."""
        return get_client().call("plugins.removeFromSlot", {
            "index": track, "slot": slot, "location": "mixer",
        })

    @mcp.tool()
    def fl_set_sidechain(src_track: int, dst_track: int,
                          enabled: bool = True, level: float = 1.0) -> dict:
        """Create or remove a send/sidechain route from src_track to dst_track.
        level: send level 0.0 (-INF) to 1.0 (0 dB / unity, default)."""
        return get_client().call("mixer.sidechain", {
            "src_track": src_track, "dst_track": dst_track,
            "enabled": enabled, "level": level,
        })

    @mcp.tool()
    def fl_get_route_info(src_track: int, dst_track: int) -> dict:
        """Check if a send/sidechain route is active between two tracks
        and read its current send level."""
        return get_client().call("mixer.getRouteInfo", {
            "src_track": src_track, "dst_track": dst_track,
        })

    @mcp.tool()
    def fl_get_slot_info(track: int, slot: int) -> dict:
        """Get plugin name + enabled/bypass state for one FX slot."""
        return get_client().call("plugins.getSlotInfo", {
            "index": track, "slot": slot,
        })

    @mcp.tool()
    def fl_get_track_peaks(track: int) -> dict:
        """Read current audio peak levels (left + right) for a mixer track.
        Returns normalised 0.0..1.0. Only works if FL Studio exposes the API."""
        return get_client().call("mixer.getPeaks", {"track": track})

    @mcp.tool()
    def fl_get_full_track_info(track: int) -> dict:
        """Extended track snapshot: volume, pan, mute/solo, all FX slots with
        enabled state, and peak levels — all in one round-trip."""
        return get_client().call("mixer.fullTrackInfo", {"track": track})

    # --- FST Mixer preset loading -------------------------------------------

    @mcp.tool()
    def fl_list_mixer_presets() -> dict:
        """List all saved mixer state presets (.fst files) with their plugin
        contents. Use this to choose which preset to load onto a track."""
        return {"presets": fst_loader.list_presets()}

    @mcp.tool()
    def fl_select_mixer_preset(wanted_plugins: list[str]) -> dict:
        """Find the mixer preset (.fst) that best matches the requested plugins.
        wanted_plugins: list of plugin name fragments to match
        (e.g. ['Pro-Q 3', 'CLA-76', 'Sibilance']).
        Returns the best matching preset with its path and plugin list."""
        result = fst_loader.select_preset(wanted_plugins)
        if result is None:
            return {"error": "No presets found in catalog"}
        return result

    @mcp.tool()
    def fl_deploy_mixer_preset(src_path: str) -> dict:
        """Copy a mixer preset .fst file to _MCP.fst (the fixed loading slot).
        Must be called before fl_load_mixer_preset.
        src_path: absolute path to the .fst file (from fl_select_mixer_preset)."""
        try:
            dest = fst_loader.deploy_preset(src_path)
            return {"ok": True, "deployed_to": dest}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @mcp.tool()
    def fl_load_mixer_preset(track: int) -> dict:
        """Load the deployed _MCP.fst mixer preset onto a mixer track.
        Navigates the FL Studio browser to _MCP.fst (always first position)
        and calls selectBrowserMenuItem to insert all plugins at once.
        Call fl_deploy_mixer_preset first to place the right .fst."""
        return get_client().call("mixer.loadFST", {"track": track})

    # --- Plugin loading -----------------------------------------------------

    @mcp.tool()
    def fl_probe_plugin_loading() -> dict:
        """Probe FL Studio window IDs (midi wid* constants + showWindow test)
        to find the Plugin Picker window for programmatic plugin loading."""
        return get_client().call("meta.probeWindows")

    @mcp.tool()
    def fl_probe_all_modules() -> dict:
        """Return all callable attributes on plugins, mixer and ui modules.
        Used to discover undocumented loading/removing functions at runtime."""
        return get_client().call("plugins.probeApi")

    @mcp.tool()
    def fl_load_plugin_via_ui(track: int, slot: int,
                              plugin_name: str = "Pro-Q 3") -> dict:
        """Attempt to load a plugin into a mixer FX slot using FL Studio's
        UI browser navigation (ui.navigateBrowser / ui.selectBrowserMenuItem).
        Returns a step-by-step log of what was attempted."""
        return get_client().call("plugins.loadViaUI", {
            "track": track, "slot": slot, "plugin_name": plugin_name,
        })

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
