"""Tests for the MIDI SysEx transport: codec roundtrip + client behavior.

No real MIDI ports: fake port objects are injected into MidiBridgeClient.
"""

from __future__ import annotations

import pytest

from fl_studio_mcp.client import BridgeUnavailable
from fl_studio_mcp.midi_transport import (
    SYSEX_CHUNK,
    MidiBridgeClient,
    Reassembler,
    encode_frames,
)


# ---------------------------------------------------------------------------
# Codec
# ---------------------------------------------------------------------------

def test_codec_roundtrip_small_message():
    msg = {"id": 1, "action": "meta.ping", "params": {}}
    frames = encode_frames(msg)
    assert len(frames) == 1
    rx = Reassembler()
    assert rx.feed(frames[0]) == msg


def test_codec_roundtrip_multi_chunk():
    # Force > 3 chunks with a large payload.
    msg = {"id": 2, "ok": True, "result": {"params": ["x" * 50] * 60}}
    frames = encode_frames(msg)
    assert len(frames) > 3
    rx = Reassembler()
    decoded = [rx.feed(f) for f in frames]
    assert decoded[:-1] == [None] * (len(frames) - 1)
    assert decoded[-1] == msg


def test_codec_frames_are_sysex_safe():
    msg = {"id": 3, "result": "éàü — caractères non-ASCII"}
    for frame in encode_frames(msg):
        assert all(0 <= b <= 0x7F for b in frame), "SysEx data must be 7-bit"


def test_codec_chunks_respect_size_limit():
    msg = {"id": 4, "result": "y" * (SYSEX_CHUNK * 3)}
    for frame in encode_frames(msg):
        # 6 header bytes + payload
        assert len(frame) <= 6 + SYSEX_CHUNK


def test_reassembler_ignores_foreign_sysex():
    rx = Reassembler()
    assert rx.feed([0x41, 0x10, 0x42, 0x12, 0x40, 0x00]) is None  # Roland frame
    # and it must not have corrupted state for a real message afterwards
    msg = {"id": 5, "ok": True, "result": None}
    frames = encode_frames(msg)
    assert rx.feed(frames[0]) == msg


# ---------------------------------------------------------------------------
# Client (fake ports)
# ---------------------------------------------------------------------------

class _FakeMidoMessage:
    def __init__(self, data):
        self.type = "sysex"
        self.data = list(data)


class FakeOutPort:
    """Collects sent frames; a responder callable builds the reply frames."""

    def __init__(self, responder, in_port):
        self.responder = responder
        self.in_port = in_port
        self.sent = []
        self._rx = Reassembler()

    def send(self, midi_msg):
        self.sent.append(list(midi_msg.data))
        decoded = self._rx.feed(midi_msg.data)
        if decoded is not None:
            reply = self.responder(decoded)
            if reply is not None:
                for frame in encode_frames(reply):
                    self.in_port.queue.append(_FakeMidoMessage(frame))

    def close(self):
        pass


class FakeInPort:
    def __init__(self):
        self.queue = []

    def poll(self):
        return self.queue.pop(0) if self.queue else None

    def close(self):
        pass


def _client(responder, timeout=2.0):
    in_port = FakeInPort()
    out_port = FakeOutPort(responder, in_port)
    return MidiBridgeClient(timeout=timeout, _out_port=out_port,
                            _in_port=in_port), in_port


def test_call_roundtrip():
    def responder(req):
        assert req["action"] == "meta.ping"
        return {"id": req["id"], "ok": True, "result": {"pong": True}}

    client, _ = _client(responder)
    assert client.call("meta.ping") == {"pong": True}


def test_call_raises_on_bridge_error():
    def responder(req):
        return {"id": req["id"], "ok": False, "error": "boom"}

    client, _ = _client(responder)
    with pytest.raises(RuntimeError, match="boom"):
        client.call("mixer.setVolume", {"track": 1, "volume": 0.5})


def test_call_skips_event_notifications():
    def responder(req):
        return {"id": req["id"], "ok": True, "result": "done"}

    client, in_port = _client(responder)
    # a push notification already sitting in the input queue
    for frame in encode_frames({"event": "transport.tick", "data": {}}):
        in_port.queue.insert(0, _FakeMidoMessage(frame))
    assert client.call("transport.status") == "done"


def test_call_times_out_when_no_response():
    client, _ = _client(lambda req: None, timeout=0.2)
    with pytest.raises(BridgeUnavailable, match="did not respond"):
        client.call("meta.ping")


def test_call_skips_stale_response_with_wrong_id():
    def responder(req):
        return {"id": req["id"], "ok": True, "result": "fresh"}

    client, in_port = _client(responder)
    for frame in encode_frames({"id": 999, "ok": True, "result": "stale"}):
        in_port.queue.insert(0, _FakeMidoMessage(frame))
    assert client.call("meta.ping") == "fresh"
