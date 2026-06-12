"""Mixer tools: volume, pan, mute, solo, track info.

Bridge handler facts (device_FLStudioMCP.py):
  mixer.setVolume  → p["track"] (int), p["volume"] (float 0..1)          → _mx_info dict
  mixer.setPan     → p["track"] (int), p["pan"] (float -1..1)             → _mx_info dict
  mixer.mute       → p["track"] (int), p["muted"] (bool | absent=toggle)  → _mx_info dict
                     The bridge supports explicit muted=True/False directly,
                     so set_mute does NOT need to pre-read state — it passes the value.
  mixer.solo       → p["track"] (int), p["solo"] (bool | absent=toggle),  → _mx_info dict
                     p["mode"] (int, default 3)
  mixer.trackInfo  → p["track"] (int)                                      → _mx_info + fx_slots
  mixer.allTracks  → p["include_empty"] (bool, default False)              → {"tracks": [...]}
"""

from __future__ import annotations

import math


def _finite(value: float, name: str) -> float:
    # NaN slips through max/min clamping (NaN comparisons are always False).
    if not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    return value


def set_volume(client, track: int, volume: float) -> dict:
    """Set mixer track volume.

    Args:
        track:  Mixer track index (0 = Master).
        volume: Linear gain 0.0..1.0 (0.8 ≈ 0 dB in FL Studio). Clamped.

    Returns:
        Updated track info dict from the bridge.
    """
    volume = max(0.0, min(1.0, _finite(volume, "volume")))
    return client.call("mixer.setVolume", {"track": track, "volume": volume})


def set_pan(client, track: int, pan: float) -> dict:
    """Set mixer track panning.

    Args:
        track: Mixer track index.
        pan:   -1.0 (full left) .. 1.0 (full right). Clamped.

    Returns:
        Updated track info dict from the bridge.
    """
    pan = max(-1.0, min(1.0, _finite(pan, "pan")))
    return client.call("mixer.setPan", {"track": track, "pan": pan})


def set_mute(client, track: int, muted: bool) -> dict:
    """Set mixer track mute state.

    The bridge (mixer.mute) accepts an explicit ``muted`` boolean, so there is
    no need to read current state first — the value is passed directly.

    Args:
        track:  Mixer track index.
        muted:  True to mute, False to unmute.

    Returns:
        Updated track info dict from the bridge.
    """
    return client.call("mixer.mute", {"track": track, "muted": muted})


def set_solo(client, track: int, solo: bool, mode: int = 3) -> dict:
    """Set mixer track solo state.

    Args:
        track: Mixer track index.
        solo:  True to solo, False to unsolo.
        mode:  FL Studio solo mode (default 3).

    Returns:
        Updated track info dict from the bridge.
    """
    return client.call("mixer.solo", {"track": track, "solo": solo, "mode": mode})


def get_track_info(client, track: int) -> dict:
    """Get full info for a single mixer track.

    Returns name, volume, pan, mute/solo state, and FX slot list.

    Args:
        track: Mixer track index.

    Returns:
        Track info dict (includes fx_slots list).
    """
    return client.call("mixer.trackInfo", {"track": track})


def list_tracks(client, include_empty: bool = False) -> dict:
    """Return an overview of all mixer tracks.

    Args:
        include_empty: When True, includes unnamed Insert tracks.

    Returns:
        {"tracks": [<track_info>, ...]}
    """
    return client.call("mixer.allTracks", {"include_empty": include_empty})
