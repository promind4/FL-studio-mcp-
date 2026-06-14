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

    FLMCP_TRANSPORT=tcp|midi forces one transport explicitly.
    Default "auto": tries TCP first (works on macOS FL Studio builds that allow sockets)
    then falls back to MIDI SysEx (required on Windows FL Studio 2025 where the
    Python sandbox hard-blocks all socket operations).
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
    def fl_probe_sandbox() -> dict:
        """Probe what FL Studio 2025's Python subinterpreter allows: socket,
        thread, file I/O, ctypes. Returns sandbox capability evidence.
        Verdict: everything except MIDI SysEx is blocked on Windows FL 2025."""
        return get_client().call("meta.sandboxProbe")

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

    # --- Native mixer EQ (built-in 3-band, no plugin needed) ----------------

    @mcp.tool()
    def fl_get_native_eq(track: int) -> dict:
        """Read FL Studio's built-in 3-band mixer EQ for a track.
        Every mixer track has this EQ regardless of loaded plugins.
        Use for quick A/B or basic corrections; use fl_set_plugin_params
        on Pro-Q 3 for precision work. Returns raw FL values — probe first
        to understand the scale (Hz/dB or normalized)."""
        return get_client().call("mixer.getEQ", {"track": track})

    @mcp.tool()
    def fl_set_native_eq_band(track: int, band: int,
                               frequency: float | None = None,
                               gain: float | None = None,
                               bandwidth: float | None = None) -> dict:
        """Set a band on FL Studio's built-in mixer EQ.
        band: 0=low shelf, 1=mid parametric, 2=high shelf.

        All values NORMALIZED 0.0-1.0. Calibrated ranges (tested 2026-06-14):
          GAIN      : norm = dB/36 + 0.5  |  dB = (norm-0.5)*36  |  range +-18 dB
                      0.0=-18dB  0.5=0dB  0.75=+9dB  1.0=+18dB
          FREQUENCY : norm = log10(Hz/10) / log10(1600)  |  Hz = 10 * 1600^norm
                      0.0=10Hz   0.5=400Hz   1.0=16kHz
          BANDWIDTH : default=0.267 (wider Q); larger value = narrower Q (unverified)

        For precision multi-band EQ use fl_set_plugin_params on Pro-Q 3 instead."""
        p: dict = {"track": track, "band": band}
        if frequency is not None:
            p["frequency"] = frequency
        if gain is not None:
            p["gain"] = gain
        if bandwidth is not None:
            p["bandwidth"] = bandwidth
        return get_client().call("mixer.setEQBand", p)

    # --- Plugin wet/dry mix level -------------------------------------------

    @mcp.tool()
    def fl_get_plugin_mix_level(track: int, slot: int) -> dict:
        """Read the wet/dry mix ratio of an FX slot (0.0=dry, 1.0=full wet).
        Useful before parallel processing to know the current blend."""
        return get_client().call("mixer.pluginMixLevel",
                                 {"track": track, "slot": slot})

    @mcp.tool()
    def fl_set_plugin_mix_level(track: int, slot: int, level: float) -> dict:
        """Set the wet/dry blend of an FX slot plugin.
        level: 0.0 (100% dry) … 0.5 (50/50 parallel) … 1.0 (100% wet).
        Classic use: parallel compression — set compressor slot to 0.5."""
        return get_client().call("mixer.pluginMixLevel",
                                 {"track": track, "slot": slot, "level": level})

    # --- FX chain bypass (all slots) ----------------------------------------

    @mcp.tool()
    def fl_set_track_slots_enabled(track: int, enabled: bool) -> dict:
        """Enable (True) or bypass (False) ALL FX slots on a mixer track.
        Faster than toggling slots one by one. Use to A/B the full FX chain.
        To toggle a single slot use fl_set_slot_enabled instead."""
        return get_client().call("mixer.trackSlotsEnabled",
                                 {"track": track, "enabled": enabled})

    # --- Stereo & polarity tools --------------------------------------------

    @mcp.tool()
    def fl_get_track_stereo(track: int) -> dict:
        """Read stereo controls: separation, polarity inversion, L/R swap."""
        return get_client().call("mixer.stereoAdvanced", {"track": track})

    @mcp.tool()
    def fl_set_track_stereo(track: int,
                             stereo_sep: float | None = None,
                             rev_polarity: bool | None = None,
                             swap_channels: bool | None = None) -> dict:
        """Set stereo controls for a mixer track.
        stereo_sep: FL's stereo separation value (probe to confirm range).
        rev_polarity: True = invert phase (fixes comb filtering between mics).
        swap_channels: True = swap L/R (fixes reversed stereo).
        Omit any param to leave it unchanged."""
        p: dict = {"track": track}
        if stereo_sep is not None:
            p["stereo_sep"] = stereo_sep
        if rev_polarity is not None:
            p["rev_polarity"] = rev_polarity
        if swap_channels is not None:
            p["swap_channels"] = swap_channels
        return get_client().call("mixer.stereoAdvanced", p)

    # --- Undo / redo --------------------------------------------------------

    @mcp.tool()
    def fl_undo(steps: int = 1) -> dict:
        """Undo the last N actions in FL Studio (default: 1).
        Call immediately if a parameter change sounded wrong or caused issues.
        Multiple steps = multiple sequential undos."""
        results = []
        for _ in range(max(1, steps)):
            results.append(get_client().call("project.undo"))
        return {"ok": True, "steps_undone": steps}

    @mcp.tool()
    def fl_redo() -> dict:
        """Redo the last undone FL Studio action."""
        return get_client().call("project.redo")

    @mcp.tool()
    def fl_get_undo_history() -> dict:
        """Read the FL Studio undo history: count, position, last entry hint."""
        return get_client().call("project.undoHistory")

    # --- Project info -------------------------------------------------------

    @mcp.tool()
    def fl_get_project_info() -> dict:
        """Full project snapshot: title, author, genre, tempo, FL version,
        track/channel/pattern counts, play state, unsaved-changes flag.
        Call once at the start of a mixing session."""
        return get_client().call("project.metadata")

    # --- User feedback ------------------------------------------------------

    @mcp.tool()
    def fl_show_notification(message: str) -> dict:
        """Display a short notification bubble in FL Studio's UI.
        Use to keep the user informed: 'Applying EQ to VOCAL PRINCIPAL',
        'Compression set on ADLIB', etc. Max ~80 chars for readability."""
        return get_client().call("ui.showNotification", {"message": message})

    # --- Browser structure probe --------------------------------------------

    @mcp.tool()
    def fl_probe_browser_structure() -> dict:
        """Map FL Studio's browser tab and section structure.
        Tests navigateBrowserTabs and navigateBrowserMenu to find how many
        steps reach the Mixer presets section — key for fast FST loading.
        Run once; leaves browser positioned at Mixer presets if found."""
        return get_client().call("browser.probeNav")

    # --- Tool guide (LLM navigation map) ------------------------------------

    @mcp.tool()
    def fl_tool_guide() -> dict:
        """Navigation map for all FL Studio MCP tools — call once at session
        start to understand priorities and use cases.
        Acts as a sitemap: which tools to call first, which to prefer."""
        return {
            "version": "0.2.0",
            "session_start_sequence": [
                "fl_ping",
                "fl_get_project_info",
                "fl_list_tracks",
            ],
            "priority_rules": [
                "1. Always ping + get project info first.",
                "2. Use fl_get_full_track_info to see what plugins are loaded on a track.",
                "3. EQ: fl_set_plugin_params (Pro-Q 3) for precision; "
                   "fl_set_native_eq_band for quick/built-in.",
                "4. Compression parallel: fl_set_plugin_mix_level (wet/dry blend).",
                "5. Bypass chain: fl_set_track_slots_enabled (all) or "
                   "fl_set_slot_enabled (one slot).",
                "6. Phase issues: fl_set_track_stereo(rev_polarity=True).",
                "7. Always fl_show_notification before long operations.",
                "8. On mistake: fl_undo immediately.",
            ],
            "categories": {
                "1_session_start": {
                    "priority": 1,
                    "tools": ["fl_ping", "fl_get_project_info", "fl_list_tracks",
                              "fl_get_full_track_info"],
                },
                "2_mixing_core": {
                    "priority": 2,
                    "tools": ["fl_set_track_volume", "fl_set_track_pan",
                              "fl_set_plugin_params", "fl_set_native_eq_band",
                              "fl_get_native_eq", "fl_set_plugin_mix_level",
                              "fl_get_plugin_mix_level"],
                },
                "3_fx_slots": {
                    "priority": 3,
                    "tools": ["fl_set_slot_enabled", "fl_set_track_slots_enabled",
                              "fl_get_slot_info", "fl_remove_plugin"],
                },
                "4_stereo_spatial": {
                    "priority": 4,
                    "tools": ["fl_set_track_stereo", "fl_get_track_stereo",
                              "fl_set_track_pan"],
                },
                "5_routing": {
                    "priority": 5,
                    "tools": ["fl_set_sidechain", "fl_get_route_info"],
                },
                "6_safety_feedback": {
                    "priority": 6,
                    "tools": ["fl_undo", "fl_redo", "fl_show_notification",
                              "fl_get_undo_history"],
                },
                "7_discovery": {
                    "priority": 7,
                    "tools": ["fl_discover_plugin_params", "fl_list_available_plugins",
                              "fl_get_track_peaks", "fl_get_plugin_param"],
                },
                "8_preset_loading": {
                    "priority": 8,
                    "tools": ["fl_list_mixer_presets", "fl_select_mixer_preset",
                              "fl_deploy_mixer_preset", "fl_load_mixer_preset"],
                    "note": "Requires template or FST preset; may timeout on browser nav.",
                },
            },
            "pro_q3_reference": {
                "band_index_formula": "base = (band_number - 1) * 13",
                "offsets": {
                    "+0": "Band Used (0=off, 1=on)",
                    "+1": "Band Enabled",
                    "+2": "Frequency (norm: log10(hz/10)/log10(3000))",
                    "+3": "Gain (norm: 0.5 + dB/60)",
                    "+7": "Q",
                    "+8": "Shape (Bell=0, LowShelf=0.10, LowCut=0.25, "
                          "HighShelf=0.375, HighCut=0.45)",
                },
                "readback_warning": (
                    "getParamValue returns stale values after writes. "
                    "A write returning 'applied' succeeded — verify visually, "
                    "not by re-reading."
                ),
            },
        }

    return mcp


def main():
    build_server().run()
