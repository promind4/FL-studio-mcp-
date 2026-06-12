"""Tests for export tools: capability probe + source-file resolution + record arm.

TDD: tests written before implementation.
"""

from __future__ import annotations

from fl_studio_mcp.tools.export import (
    probe_export_capabilities,
    resolve_track_audio,
    set_record_arm,
)


class FakeClient:
    """Records calls and returns pre-configured responses per action."""

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
        return handler


def _sample_info_client(sample_path):
    return FakeClient({
        "channels.sampleInfo": lambda p: {
            "channel": p["channel"], "name": "Vocal", "sample_path": sample_path,
        },
    })


# ---------------------------------------------------------------------------
# resolve_track_audio
# ---------------------------------------------------------------------------

def test_resolve_returns_existing_file(tmp_path):
    wav = tmp_path / "vocal.wav"
    wav.write_bytes(b"RIFF")
    client = _sample_info_client(str(wav))
    result = resolve_track_audio(client, channel=0)
    assert result["available"] is True
    assert result["path"] == str(wav)
    assert result["name"] == "Vocal"
    assert client.calls == [("channels.sampleInfo", {"channel": 0})]


def test_resolve_reports_missing_file():
    client = _sample_info_client("C:/nonexistent/fLMCP/vocal.wav")
    result = resolve_track_audio(client, channel=0)
    assert result["available"] is False
    assert result["path"] == "C:/nonexistent/fLMCP/vocal.wav"
    assert "not found" in result["hint"]


def test_resolve_handles_no_path():
    client = _sample_info_client(None)
    result = resolve_track_audio(client, channel=0)
    assert result["available"] is False
    assert result["path"] is None
    assert "hint" in result


def test_resolve_treats_empty_string_path_as_missing():
    # The bridge may return "" rather than None for channels without a sample.
    client = _sample_info_client("")
    result = resolve_track_audio(client, channel=3)
    assert result["available"] is False
    assert result["path"] is None
    assert "hint" in result


# ---------------------------------------------------------------------------
# probe_export_capabilities
# ---------------------------------------------------------------------------

def test_probe_passes_through_bridge_report():
    report = {"strategies": {"mixer.armTrack": True, "transport.render": False}}
    client = FakeClient({"export.capabilities": report})
    assert probe_export_capabilities(client) == report
    assert client.calls == [("export.capabilities", {})]


# ---------------------------------------------------------------------------
# set_record_arm
# ---------------------------------------------------------------------------

def test_set_record_arm_passes_explicit_state():
    client = FakeClient({
        "mixer.recordArm": lambda p: {
            "track": p["track"], "armed": p["armed"],
            "recording_file": "C:/rec/track2.wav",
        },
    })
    result = set_record_arm(client, track=2, armed=True)
    assert result["armed"] is True
    assert result["recording_file"] == "C:/rec/track2.wav"
    assert client.calls == [("mixer.recordArm", {"track": 2, "armed": True})]


def test_set_record_arm_disarm():
    client = FakeClient({
        "mixer.recordArm": lambda p: {
            "track": p["track"], "armed": p["armed"], "recording_file": None,
        },
    })
    result = set_record_arm(client, track=5, armed=False)
    assert result["armed"] is False
    assert client.calls == [("mixer.recordArm", {"track": 5, "armed": False})]
