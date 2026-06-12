"""Tests for mixer tools: volume, pan, mute, solo, track info.

Bridge handler formats (from device_FLStudioMCP.py):
  mixer.setVolume  → p["track"] (int), p["volume"] (float 0..1) → _mx_info dict
  mixer.setPan     → p["track"] (int), p["pan"] (float -1..1)   → _mx_info dict
  mixer.mute       → p["track"] (int), p["muted"] (bool|absent) → _mx_info dict
                     (muted=None toggles; explicit bool sets directly — NOT toggle-only)
  mixer.solo       → p["track"] (int), p["solo"] (bool|absent), p["mode"] (int, default 3) → _mx_info dict
  mixer.trackInfo  → p["track"] (int) → full _mx_info + fx_slots list
  mixer.allTracks  → p["include_empty"] (bool, default False) → {"tracks": [...]}
"""

from __future__ import annotations

import pytest

from fl_studio_mcp.tools.mixer import (
    get_track_info,
    list_tracks,
    set_mute,
    set_pan,
    set_volume,
)


# ---------------------------------------------------------------------------
# Local FakeClient (do NOT import across test files)
# ---------------------------------------------------------------------------

class FakeClient:
    """Records calls and returns pre-configured responses.

    Each value in *responses* may be:
    - a plain dict  → returned as-is every time
    - a callable    → called with the params dict; its return value is used
    - a list        → items consumed in order (one per call); raises if exhausted
    """

    def __init__(self, responses: dict):
        self.responses = responses
        self.calls: list[tuple[str, dict]] = []

    def call(self, action: str, params: dict) -> object:
        self.calls.append((action, params))
        if action not in self.responses:
            raise KeyError(f"FakeClient: no response configured for action {action!r}")
        handler = self.responses[action]
        if callable(handler):
            return handler(params)
        if isinstance(handler, list):
            if not handler:
                raise IndexError(
                    f"FakeClient: response list for {action!r} is exhausted"
                )
            return handler.pop(0)
        return handler


# ---------------------------------------------------------------------------
# Shared fake track-info response
# ---------------------------------------------------------------------------

def _fake_track_info(track: int = 1) -> dict:
    return {
        "index": track,
        "name": f"Track {track}",
        "volume": 0.8,
        "pan": 0.0,
        "is_muted": False,
        "is_solo": False,
        "is_armed": False,
    }


# ---------------------------------------------------------------------------
# Test 1: set_volume clamps to valid range [0.0, 1.0]
# ---------------------------------------------------------------------------

def test_set_volume_clamps_to_valid_range():
    """Volume=1.5 must be clamped to 1.0 before calling the bridge."""
    client = FakeClient({"mixer.setVolume": _fake_track_info()})

    set_volume(client, track=1, volume=1.5)

    assert len(client.calls) == 1
    action, params = client.calls[0]
    assert action == "mixer.setVolume"
    assert params["track"] == 1
    assert params["volume"] == 1.0


def test_set_volume_clamps_negative():
    """Volume=-0.2 must be clamped to 0.0 before calling the bridge."""
    client = FakeClient({"mixer.setVolume": _fake_track_info()})

    set_volume(client, track=2, volume=-0.2)

    action, params = client.calls[0]
    assert action == "mixer.setVolume"
    assert params["volume"] == 0.0


def test_set_volume_passes_valid_value():
    """Volume=0.8 (0 dB in FL Studio) must be passed through unchanged."""
    client = FakeClient({"mixer.setVolume": _fake_track_info()})

    result = set_volume(client, track=1, volume=0.8)

    action, params = client.calls[0]
    assert params["volume"] == 0.8
    assert result == _fake_track_info()


# ---------------------------------------------------------------------------
# Test 2: set_pan passes through valid values and clamps out-of-range ones
# ---------------------------------------------------------------------------

def test_set_pan_passes_through_valid_value():
    """pan=-0.5 must be sent as-is."""
    client = FakeClient({"mixer.setPan": _fake_track_info()})

    set_pan(client, track=1, pan=-0.5)

    action, params = client.calls[0]
    assert action == "mixer.setPan"
    assert params["track"] == 1
    assert params["pan"] == pytest.approx(-0.5)


def test_set_pan_clamps_above_max():
    """pan=2.0 must be clamped to 1.0."""
    client = FakeClient({"mixer.setPan": _fake_track_info()})

    set_pan(client, track=1, pan=2.0)

    _, params = client.calls[0]
    assert params["pan"] == 1.0


def test_set_pan_clamps_below_min():
    """pan=-2.0 must be clamped to -1.0."""
    client = FakeClient({"mixer.setPan": _fake_track_info()})

    set_pan(client, track=1, pan=-2.0)

    _, params = client.calls[0]
    assert params["pan"] == -1.0


# ---------------------------------------------------------------------------
# Test 3: set_mute sends explicit muted flag (bridge supports it directly)
# ---------------------------------------------------------------------------

def test_set_mute_sends_explicit_true():
    """set_mute(muted=True) must send muted=True to the bridge."""
    client = FakeClient({"mixer.mute": _fake_track_info()})

    result = set_mute(client, track=3, muted=True)

    assert len(client.calls) == 1
    action, params = client.calls[0]
    assert action == "mixer.mute"
    assert params["track"] == 3
    assert params["muted"] is True
    assert result == _fake_track_info()


def test_set_mute_sends_explicit_false():
    """set_mute(muted=False) must send muted=False to the bridge."""
    client = FakeClient({"mixer.mute": _fake_track_info()})

    set_mute(client, track=3, muted=False)

    _, params = client.calls[0]
    assert params["muted"] is False


# ---------------------------------------------------------------------------
# Test 4: get_track_info calls the correct bridge action with correct param key
# ---------------------------------------------------------------------------

def test_get_track_info_calls_bridge():
    """get_track_info must call mixer.trackInfo with p["track"]."""
    expected = {**_fake_track_info(5), "fx_slots": []}
    client = FakeClient({"mixer.trackInfo": expected})

    result = get_track_info(client, track=5)

    assert len(client.calls) == 1
    action, params = client.calls[0]
    assert action == "mixer.trackInfo"
    assert params["track"] == 5
    assert result == expected


# ---------------------------------------------------------------------------
# Test 5: list_tracks calls the correct bridge action
# ---------------------------------------------------------------------------

def test_list_tracks_calls_bridge():
    """list_tracks must call mixer.allTracks."""
    expected = {"tracks": [_fake_track_info(0), _fake_track_info(1)]}
    client = FakeClient({"mixer.allTracks": expected})

    result = list_tracks(client)

    assert len(client.calls) == 1
    action, params = client.calls[0]
    assert action == "mixer.allTracks"
    assert result == expected


def test_list_tracks_include_empty_default():
    """list_tracks must not pass include_empty=True by default."""
    client = FakeClient({"mixer.allTracks": {"tracks": []}})

    list_tracks(client)

    _, params = client.calls[0]
    # Default should be include_empty=False (or absent, bridge defaults to False)
    assert params.get("include_empty", False) is False


def test_list_tracks_include_empty_option():
    """list_tracks(include_empty=True) must forward the flag."""
    client = FakeClient({"mixer.allTracks": {"tracks": []}})

    list_tracks(client, include_empty=True)

    _, params = client.calls[0]
    assert params["include_empty"] is True


# ---------------------------------------------------------------------------
# Test 6: return values are forwarded unchanged
# ---------------------------------------------------------------------------

def test_set_volume_returns_bridge_response():
    """set_volume must return exactly what the bridge returned."""
    bridge_response = _fake_track_info(7)
    client = FakeClient({"mixer.setVolume": bridge_response})

    result = set_volume(client, track=7, volume=0.5)

    assert result is bridge_response


def test_set_pan_returns_bridge_response():
    bridge_response = _fake_track_info(2)
    client = FakeClient({"mixer.setPan": bridge_response})

    result = set_pan(client, track=2, pan=0.3)

    assert result is bridge_response
