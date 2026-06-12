"""Track audio resolution for analysis: probe, source file, record arm.

Project render is not scriptable in FL's public API. Order of strategies:
1. source file of the channel (works for recorded/imported audio, pre-effects)
2. disk recording per mixer track (arm + record, post-effects)
3. assisted export: user renders, we read the file (orchestrated by the LLM)

Bridge handler facts (device_FLStudioMCP.py):
  export.capabilities  → {}                                       → {"strategies": {api_name: bool}}
  channels.sampleInfo  → p["channel"] (int)                       → {"channel", "name", "sample_path", ["hint"]}
  mixer.recordArm      → p["track"] (int), p["armed"] (bool)      → {"track", "armed", "recording_file", ["hint"]}
                         armTrack is a toggle; the bridge only toggles when
                         current state differs from the requested one.
"""

from __future__ import annotations

from pathlib import Path


def probe_export_capabilities(client) -> dict:
    """One-time runtime probe of render/export and disk-recording APIs.

    Returns:
        {"strategies": {"<module>.<fn>": bool, ...}} — which entry points the
        running FL build actually exposes.
    """
    return client.call("export.capabilities", {})


def resolve_track_audio(client, channel: int) -> dict:
    """Find an analyzable audio file for a channel (source-file strategy).

    The bridge cannot read files (FL sandbox); this runs in the MCP server
    process, which can — so the existence check happens here.

    Args:
        channel: Global channel index in the channel rack.

    Returns:
        {"available": True,  "path": str, "name": str}              on success
        {"available": False, "path": str|None, "hint": str}          otherwise
    """
    info = client.call("channels.sampleInfo", {"channel": channel})
    path = info.get("sample_path")
    if not path:  # None or "" — the bridge may return either for no sample
        return {"available": False, "path": None,
                "hint": "No source file on this channel. Ask the user to "
                        "export the track (right-click mixer track → "
                        "'render to wav') and provide the file path."}
    if not Path(path).exists():
        return {"available": False, "path": path,
                "hint": f"Source file not found on disk: {path}"}
    return {"available": True, "path": path, "name": info.get("name")}


def set_record_arm(client, track: int, armed: bool = True) -> dict:
    """Arm or disarm a mixer track for disk recording (post-effects audio).

    Full flow, orchestrated from the server side: arm the track, start
    transport record+play, let FL write the WAV, stop, disarm, then read
    ``recording_file`` from disk.

    Args:
        track: Mixer track index.
        armed: True to arm, False to disarm.

    Returns:
        {"track": int, "armed": bool, "recording_file": str|None} — the path
        of the WAV FL will write while recording (None when the running FL
        build does not expose getTrackRecordingFileName).
    """
    return client.call("mixer.recordArm", {"track": track, "armed": armed})
