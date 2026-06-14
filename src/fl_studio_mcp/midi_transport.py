"""MIDI SysEx transport to the FL Studio bridge.

FL Studio 2025 runs MIDI scripts in a locked subinterpreter (no threads, no
sockets, no file I/O), so TCP is impossible there. The bridge and this client
speak JSON over SysEx frames instead, through a pair of loopMIDI virtual
ports:

    server --SysEx--> [loopMIDI "fLMCP In"]  --> FL input  (bridge script)
    server <--SysEx-- [loopMIDI "fLMCP Out"] <-- FL output (same port number)

Frame layout (mirrors the codec in bridge/device_FLStudioMCP.py):
    F0 7D 46 4C <flags> <seq_lo> <seq_hi> <base64 slice> F7
The JSON message is base64-encoded (pure ASCII, SysEx-safe) and sliced into
chunks of SYSEX_CHUNK chars; flags bit0 marks the final chunk.
"""

from __future__ import annotations

import base64
import itertools
import json
import threading
import time
from typing import Any

from .client import BridgeUnavailable

SYSEX_MAGIC = (0x7D, 0x46, 0x4C)
SYSEX_CHUNK = 512
_MAX_NOTIFICATIONS = 64

# Default loopMIDI port names (substring match, case-insensitive).
PORT_TO_FL = "fLMCP In"     # we write here; FL reads it as controller input
PORT_FROM_FL = "fLMCP Out"  # FL writes here; we read responses from it


def encode_frames(obj: dict) -> list[list[int]]:
    """JSON message -> list of SysEx data payloads (without F0/F7).

    Returned lists are mido-style ``data`` sequences: every value 0..127.
    """
    payload = base64.b64encode(
        json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    frames = []
    nchunks = max(1, (len(payload) + SYSEX_CHUNK - 1) // SYSEX_CHUNK)
    for i in range(nchunks):
        chunk = payload[i * SYSEX_CHUNK:(i + 1) * SYSEX_CHUNK]
        flags = 0x01 if i == nchunks - 1 else 0x00
        frames.append(list(SYSEX_MAGIC) + [flags, i & 0x7F, (i >> 7) & 0x7F]
                      + list(chunk))
    return frames


class Reassembler:
    """Accumulates SysEx data payloads; yields decoded JSON messages."""

    def __init__(self):
        self._chunks: list[bytes] = []

    def feed(self, data) -> dict | None:
        """Feed one SysEx ``data`` payload (no F0/F7). Returns the decoded
        message when the final chunk arrives, else None. Foreign SysEx
        (wrong magic) is ignored and returns None."""
        data = bytes(data)
        if len(data) < 6 or tuple(data[0:3]) != SYSEX_MAGIC:
            return None
        flags = data[3]
        self._chunks.append(data[6:])
        if not (flags & 0x01):
            return None
        blob = b"".join(self._chunks)
        self._chunks = []
        return json.loads(base64.b64decode(blob).decode("utf-8"))


class _SysexMessage:
    """Minimal stand-in for mido.Message used with injected test ports."""

    def __init__(self, data):
        self.type = "sysex"
        self.data = list(data)


class MidiBridgeClient:
    """Same call() contract as BridgeClient, but over loopMIDI SysEx."""

    def __init__(self, to_fl_hint: str = PORT_TO_FL,
                 from_fl_hint: str = PORT_FROM_FL,
                 timeout: float = 90.0,
                 _out_port=None, _in_port=None):
        self.to_fl_hint = to_fl_hint
        self.from_fl_hint = from_fl_hint
        self.timeout = timeout
        self._out = _out_port  # injectable for tests
        self._in = _in_port
        # injected ports take any message-like object; real ports need
        # mido.Message — the factory is swapped in _connect()
        self._msg_factory = _SysexMessage
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._rx = Reassembler()

    # -- connection -----------------------------------------------------

    def _connect(self):
        if self._out is not None and self._in is not None:
            return
        backend = None
        try:
            import mido
            # mido needs a working rtmidi backend, not just the package
            mido.get_output_names()
            backend = "mido"
        except Exception:
            pass
        if backend == "mido":
            get_out, get_in = mido.get_output_names, mido.get_input_names
            open_out, open_in = mido.open_output, mido.open_input
            msg_factory = lambda data: mido.Message("sysex", data=data)  # noqa: E731
        else:
            # dependency-free Windows fallback (no rtmidi wheel needed)
            from . import winmm_midi
            get_out, get_in = winmm_midi.get_output_names, winmm_midi.get_input_names
            open_out, open_in = winmm_midi.MidiOut, winmm_midi.MidiIn
            msg_factory = _SysexMessage
        out_name = self._find_port(get_out(), self.to_fl_hint)
        in_name = self._find_port(get_in(), self.from_fl_hint)
        if out_name is None or in_name is None:
            raise BridgeUnavailable(
                "loopMIDI ports not found (need one named like %r for "
                "server->FL and one like %r for FL->server). Create them in "
                "loopMIDI, then enable both in FL Studio's MIDI settings "
                "(input assigned to the fLMCP Bridge controller, output with "
                "the same port number)."
                % (self.to_fl_hint, self.from_fl_hint))
        self._out = open_out(out_name)
        self._in = open_in(in_name)
        self._msg_factory = msg_factory

    @staticmethod
    def _find_port(names, hint):
        hint = hint.lower()
        for name in names:
            if hint in name.lower():
                return name
        return None

    # -- request/response -----------------------------------------------

    def call(self, action: str, params: dict | None = None) -> Any:
        with self._lock:
            self._connect()
            request = {"id": next(self._ids), "action": action,
                       "params": params or {}}
            for frame in encode_frames(request):
                self._send_sysex(frame)
            response = self._read_response(request["id"])
            if not response.get("ok"):
                raise RuntimeError(f"{action}: {response.get('error')}")
            return response.get("result")

    def _send_sysex(self, data: list[int]):
        self._out.send(self._msg_factory(data))

    def _read_response(self, request_id: int) -> dict:
        deadline = time.monotonic() + self.timeout
        skipped = 0
        while time.monotonic() < deadline:
            msg = self._poll_message(deadline)
            if msg is None:
                continue
            if "event" in msg:  # notification push — ignored in v0
                skipped += 1
                if skipped > _MAX_NOTIFICATIONS:
                    raise BridgeUnavailable(
                        "too many notifications before response")
                continue
            if msg.get("id") == request_id:
                return msg
            # Stale response from a previous timed-out call: skip it.
        raise BridgeUnavailable(
            f"bridge did not respond within {self.timeout}s (is FL Studio "
            "running with the fLMCP Bridge controller enabled?)")

    def _poll_message(self, deadline: float) -> dict | None:
        """Poll the input port until one complete JSON message is decoded."""
        while time.monotonic() < deadline:
            midi_msg = self._in.poll()
            if midi_msg is None:
                time.sleep(0.005)
                continue
            if midi_msg.type != "sysex":
                continue
            decoded = self._rx.feed(midi_msg.data)
            if decoded is not None:
                return decoded
        return None

    def close(self):
        with self._lock:
            for port in (self._out, self._in):
                try:
                    if port is not None:
                        port.close()
                except Exception:
                    pass
            self._out = self._in = None
