# name=fLMCP Bridge
# supportedDevices=fLMCP Bridge
# url=https://github.com/your-handle/fLMCP
# receiveFrom=fLMCP Bridge

"""
fLMCP Bridge — the FL Studio side of the fl-studio-mcp Model Context Protocol server.

How it works
------------
This script runs inside FL Studio as a "MIDI device" (no real hardware needed — it's
loaded by configuring a virtual/loopback MIDI port or by any MIDI input that FL can
see). On OnInit() it opens a non-blocking TCP server on 127.0.0.1:9876 that
receives length-prefixed JSON-RPC requests from the fl-studio-mcp server.

Everything runs on FL Studio's main thread: FL 2025's Python subinterpreter
forbids creating threads (start_new_thread returns NULL), so OnIdle() — called
several times per second — polls the sockets (accept/recv non-blocking),
parses complete frames, executes the FL API calls, and sends responses back.

Piano-roll edits are deferred: we stage them into `piano_roll_requests.json` inside
this script's directory, and the fl-studio-mcp server is responsible for opening the
piano-roll window and triggering the companion `ComposeWithLLM.pyscript` via
Ctrl+Alt+Y. After the pyscript runs, it writes `piano_roll_state.json` which the
MCP server reads back.

Protocol
--------
Frame: [4-byte big-endian uint32 length][payload = utf-8 JSON]
Request:      {"id": int, "action": str, "params": {...}}
Response:     {"id": int, "ok": bool, "result": ..., "error": str|None}
Notification: {"event": str, "data": ...}   (server push, no id)
"""

import base64
import json
import os
import queue
import socket
import struct
import sys
import time
import traceback
from pathlib import Path

# FL Studio API — available when running inside FL Studio
import arrangement
import channels
import device
import general
import midi
import mixer
import patterns
import playlist
import plugins
import transport
import ui


# ----------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------

BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 9876
HEADER = struct.Struct(">I")
MAX_FRAME = 16 * 1024 * 1024
BRIDGE_VERSION = "0.1.0"


def _script_dir():
    if sys.platform == "darwin":
        base = Path.home() / "Documents" / "Image-Line" / "FL Studio" / "Settings"
    elif sys.platform == "win32":
        userprofile = os.environ.get("USERPROFILE", str(Path.home()))
        base = Path(userprofile) / "Documents" / "Image-Line" / "FL Studio" / "Settings"
    else:
        base = Path.home() / "Documents" / "Image-Line" / "FL Studio" / "Settings"
    return base / "Hardware" / "fLMCP Bridge"


SCRIPT_DIR = _script_dir()
PIANO_ROLL_DIR_NAME = "Piano roll scripts"
PR_REQUEST = Path(SCRIPT_DIR).parent.parent / PIANO_ROLL_DIR_NAME / "fLMCP_request.json"
PR_STATE = Path(SCRIPT_DIR).parent.parent / PIANO_ROLL_DIR_NAME / "fLMCP_state.json"


# ----------------------------------------------------------------------------
# Global state
# ----------------------------------------------------------------------------

# Inbox entries are (origin, request): origin is a client socket for the TCP
# transport, or None for requests that arrived over MIDI SysEx.
_inbox: "queue.Queue[tuple[object, dict]]" = queue.Queue()
_accept_socket = None
_clients = {}  # socket -> bytearray receive buffer (incremental frame parsing)
_shutting_down = False
_started_at = time.monotonic()
_idle_tick = 0
_last_refresh_push = 0.0
_known_clients = set()  # live client sockets for push notifications
_midi_active = False  # True once a SysEx request arrived (enables MIDI pushes)
_sysex_rx = []  # base64 ASCII chunks of the message currently being received


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def _log(msg):
    try:
        print("[fLMCP] " + msg)
    except Exception:
        pass


def _pack_frame(obj):
    body = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(body) > MAX_FRAME:
        raise ValueError("frame too large: %d" % len(body))
    return HEADER.pack(len(body)) + body


def _color_to_int(color):
    """Convert '#RRGGBB', 'rgb(r,g,b)' or int to FL's 0xBBGGRR integer."""
    if isinstance(color, int):
        return color
    if isinstance(color, (list, tuple)) and len(color) >= 3:
        r, g, b = int(color[0]), int(color[1]), int(color[2])
        return (b << 16) | (g << 8) | r
    s = str(color).strip()
    if s.startswith("#"):
        s = s[1:]
        if len(s) == 6:
            r = int(s[0:2], 16); g = int(s[2:4], 16); b = int(s[4:6], 16)
            return (b << 16) | (g << 8) | r
    if s.lower().startswith("rgb"):
        parts = s[s.find("(")+1:s.find(")")].split(",")
        r, g, b = [int(p.strip()) for p in parts[:3]]
        return (b << 16) | (g << 8) | r
    try:
        return int(s, 0)
    except Exception:
        return 0


def _int_to_color_hex(color):
    b = (color >> 16) & 0xFF
    g = (color >> 8) & 0xFF
    r = color & 0xFF
    return "#%02X%02X%02X" % (r, g, b)


def _bool_int(value):
    return 1 if value else 0


def _safe(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except Exception:
        return None


# ----------------------------------------------------------------------------
# Network pump — threadless, runs entirely on FL's main thread from OnIdle.
# FL Studio 2025's Python subinterpreter forbids creating threads
# (start_new_thread returns NULL), so all I/O is non-blocking and polled.
# ----------------------------------------------------------------------------

def _probe_sandbox():
    """Log which IPC channels FL 2025's Python sandbox still allows.

    FL Studio 2025 runs MIDI scripts in a restricted subinterpreter: threads
    and (apparently) sockets are blocked. This probe tells us in one restart
    what we can build on instead (file polling, MIDI SysEx, ...)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.close()
        _log("probe socket: OK")
    except BaseException as e:
        _log("probe socket: BLOCKED (%s)" % e)
    for label, path in (
            ("home", os.path.join(os.path.expanduser("~"), "flmcp_probe.txt")),
            ("repo", r"D:\Craft\FL studio LLM\flmcp_probe.txt")):
        try:
            with open(path, "w") as f:
                f.write("ok")
            os.remove(path)
            _log("probe file write %s: OK" % label)
        except BaseException as e:
            _log("probe file write %s: BLOCKED (%s)" % (label, e))
    try:
        import subprocess
        r = subprocess.run(["cmd", "/c", "echo flmcp"], capture_output=True,
                           timeout=5, text=True)
        _log("probe subprocess.run: OK (%r)" % r.stdout.strip())
    except BaseException as e:
        _log("probe subprocess.run: BLOCKED (%s)" % e)
    try:
        import ctypes
        tick = ctypes.windll.kernel32.GetTickCount()
        _log("probe ctypes kernel32: OK (tick=%d)" % tick)
    except BaseException as e:
        _log("probe ctypes kernel32: BLOCKED (%s)" % e)
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32
        GENERIC_RW = 0xC0000000
        OPEN_EXISTING = 3
        h = k32.CreateFileW(r"\\.\pipe\flmcp_probe", GENERIC_RW, 0, None,
                            OPEN_EXISTING, 0, None)
        err = k32.GetLastError()
        if h != wintypes.HANDLE(-1).value:
            k32.CloseHandle(h)
        # ERROR_FILE_NOT_FOUND (2) is the EXPECTED success signal here: the
        # call reached the OS and looked for the pipe (no server is running).
        _log("probe ctypes CreateFileW pipe: reached OS (err=%d, 2=not found=GOOD)" % err)
    except BaseException as e:
        _log("probe ctypes CreateFileW pipe: BLOCKED (%s)" % e)


_bind_attempts = 0


def _start_listening():
    global _accept_socket, _bind_attempts
    if _accept_socket is not None:
        return True
    _bind_attempts += 1
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((BRIDGE_HOST, BRIDGE_PORT))
        s.listen(4)
        s.setblocking(False)
        _accept_socket = s
        _log("TCP server listening on %s:%d" % (BRIDGE_HOST, BRIDGE_PORT))
        return True
    except Exception as e:
        _log("failed to bind bridge port: %s" % e)
        _accept_socket = None
        return False


def _drop_client(sock):
    _clients.pop(sock, None)
    _known_clients.discard(sock)
    try:
        sock.close()
    except Exception:
        pass


def _send_frame(sock, frame_bytes):
    # Localhost + small frames: a short blocking send keeps the code simple
    # without risking a partial write on the non-blocking socket.
    try:
        sock.settimeout(2.0)
        sock.sendall(frame_bytes)
        return True
    except Exception as e:
        _log("send failed: %s" % e)
        _drop_client(sock)
        return False
    finally:
        try:
            sock.setblocking(False)
        except Exception:
            pass


def _pump_network():
    """Accept pending connections and parse incoming frames. Main thread only."""
    if _accept_socket is None:
        return
    while True:
        try:
            conn, _addr = _accept_socket.accept()
        except (BlockingIOError, InterruptedError):
            break
        except Exception as e:
            _log("accept error: %s" % e)
            break
        conn.setblocking(False)
        _clients[conn] = bytearray()
        _known_clients.add(conn)

    for sock in list(_clients.keys()):
        buf = _clients.get(sock)
        if buf is None:
            continue
        closed = False
        while True:
            try:
                chunk = sock.recv(65536)
            except (BlockingIOError, InterruptedError):
                break
            except Exception:
                closed = True
                break
            if not chunk:
                closed = True
                break
            buf.extend(chunk)
        while True:
            if len(buf) < HEADER.size:
                break
            (length,) = HEADER.unpack(bytes(buf[:HEADER.size]))
            if length > MAX_FRAME:
                _log("oversized frame (%d bytes); dropping client" % length)
                closed = True
                break
            if len(buf) < HEADER.size + length:
                break  # frame incomplete — wait for the next idle tick
            body = bytes(buf[HEADER.size:HEADER.size + length])
            del buf[:HEADER.size + length]
            try:
                req = json.loads(body.decode("utf-8"))
            except Exception as e:
                _send_frame(sock, _pack_frame(
                    {"id": 0, "ok": False, "error": "frame_error: %s" % e}))
                continue
            _inbox.put((sock, req))
        if closed:
            _drop_client(sock)


# ----------------------------------------------------------------------------
# MIDI SysEx transport — the only channel FL Studio 2025's sandbox leaves open.
#
# A JSON message is base64-encoded (pure ASCII, so every byte is SysEx-safe
# 7-bit data) and sliced into chunks. Each chunk travels as:
#   F0 7D 46 4C <flags> <seq_lo> <seq_hi> <base64 slice> F7
# 0x7D is the MIDI "non-commercial / educational" manufacturer id; 46 4C is
# "FL". flags bit0 marks the final chunk. seq is a 14-bit chunk counter.
# The server side (midi_transport.py) implements the same codec over loopMIDI.
# ----------------------------------------------------------------------------

SYSEX_MAGIC = (0x7D, 0x46, 0x4C)
SYSEX_CHUNK = 512  # base64 chars per SysEx frame


def _sysex_encode(obj):
    """JSON message -> list of complete SysEx frames (bytes, F0..F7)."""
    payload = base64.b64encode(
        json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    frames = []
    nchunks = max(1, (len(payload) + SYSEX_CHUNK - 1) // SYSEX_CHUNK)
    for i in range(nchunks):
        chunk = payload[i * SYSEX_CHUNK:(i + 1) * SYSEX_CHUNK]
        flags = 0x01 if i == nchunks - 1 else 0x00
        frames.append(bytes((0xF0,) + SYSEX_MAGIC
                            + (flags, i & 0x7F, (i >> 7) & 0x7F))
                      + chunk + bytes((0xF7,)))
    return frames


def _midi_send_message(obj):
    """Send a JSON message to the MCP server over the linked MIDI output."""
    if not hasattr(device, "midiOutSysex"):
        _log("device.midiOutSysex not available in this FL build")
        return False
    try:
        for frame in _sysex_encode(obj):
            device.midiOutSysex(frame)
        return True
    except Exception as e:
        _log("midi send failed: %s" % e)
        return False


def _on_sysex_bytes(data):
    """Handle one received SysEx frame.

    Tolerates both F0-prefixed (full frame) and bare-payload forms because
    FL Studio 2025 passes event.sysex without the F0/F7 framing bytes.
    """
    global _midi_active, _sysex_rx
    data = bytes(data)
    # Strip F0 / F7 framing if present so we work with bare payload.
    if data and data[0] == 0xF0:
        data = data[1:]
    if data and data[-1] == 0xF7:
        data = data[:-1]
    # Bare payload: MAGIC(3) flags(1) seq_lo(1) seq_hi(1) base64(...)
    if len(data) < 7 or tuple(data[0:3]) != SYSEX_MAGIC:
        return False  # not ours
    flags = data[3]
    payload = bytes(data[6:])
    _sysex_rx.append(payload)
    if not (flags & 0x01):
        return True  # more chunks coming
    blob = b"".join(_sysex_rx)
    _sysex_rx = []
    try:
        req = json.loads(base64.b64decode(blob).decode("utf-8"))
    except Exception as e:
        _midi_send_message({"id": 0, "ok": False, "error": "frame_error: %s" % e})
        return True
    _midi_active = True
    _inbox.put((None, req))
    return True


# ----------------------------------------------------------------------------
# Handlers — executed on FL's main thread (from OnIdle)
# ----------------------------------------------------------------------------

def _execute(action, params):
    """Dispatch action -> result dict. Raises on error."""
    h = _HANDLERS.get(action)
    if h is None:
        raise ValueError("unknown action: %s" % action)
    return h(params or {})


# ---- meta -------------------------------------------------------------------

def h_meta_ping(_):
    return {
        "ok": True,
        "bridge_version": BRIDGE_VERSION,
        "fl_version": _safe(general.getVersion) or "unknown",
        "uptime_sec": round(time.monotonic() - _started_at, 1),
        "script_dir": str(SCRIPT_DIR),
    }


def h_meta_info(_):
    return {
        "bridge_version": BRIDGE_VERSION,
        "fl_version": _safe(general.getVersion) or "unknown",
        "api_modules": ["transport","mixer","channels","patterns","playlist",
                        "plugins","arrangement","ui","general","device","midi"],
        "script_dir": str(SCRIPT_DIR),
        "tcp_host": BRIDGE_HOST,
        "tcp_port": BRIDGE_PORT,
    }


# ---- transport --------------------------------------------------------------

def _position_unit(unit):
    # FL SONGLENGTH_* constants: 0=MS, 1=S, 2=ABSTICKS, 3=BARS, 4=STEPS, 5=TICKS
    return {"ms": 0, "seconds": 1, "ticks": 2, "bars": 3, "steps": 4}.get(unit, 3)


def h_transport_start(_):
    transport.start()
    return {"is_playing": transport.isPlaying() == 1}


def h_transport_stop(_):
    transport.stop()
    return {"stopped": True}


def h_transport_record(_):
    transport.record()
    return {"is_recording": transport.isRecording() == 1}


def h_transport_status(_):
    try:
        tempo = mixer.getCurrentTempo() / 1000.0
    except Exception:
        tempo = None
    return {
        "is_playing": transport.isPlaying() == 1,
        "is_recording": transport.isRecording() == 1,
        "position_ticks": transport.getSongPos(2),
        "position_bars": transport.getSongPos(3),
        "position_seconds": transport.getSongPos(1),
        "loop_mode": "song" if transport.getLoopMode() == 1 else "pattern",
        "bpm": tempo,
    }


def h_transport_set_position(p):
    unit = p.get("unit", "bars")
    transport.setSongPos(p.get("position", 0), _position_unit(unit))
    return {"position_bars": transport.getSongPos(3)}


def h_transport_length(_):
    return {
        "ticks": transport.getSongLength(2),
        "seconds": transport.getSongLength(1),
        "ms": transport.getSongLength(0),
        "bars": transport.getSongLength(3),
        "steps": transport.getSongLength(4),
    }


def h_transport_set_loop_mode(p):
    mode = p.get("mode", "pattern")
    target = 1 if mode == "song" else 0
    if transport.getLoopMode() != target:
        transport.setLoopMode()
    return {"mode": mode}


def h_transport_set_playback_speed(p):
    speed = float(p.get("speed", 1.0))
    transport.setPlaybackSpeed(speed)
    return {"speed": speed}


def h_transport_set_tempo(p):
    bpm = float(p.get("bpm", 140.0))
    general.processRECEvent(
        midi.REC_Tempo,
        int(round(bpm * 1000)),
        midi.REC_Control | midi.REC_UpdateControl,
    )
    return {"bpm": mixer.getCurrentTempo() / 1000.0}


def _fpt(name):
    """Resolve an FPT_* constant if it exists; return None otherwise."""
    return getattr(midi, name, None)


def h_transport_tap_tempo(_):
    fpt = _fpt("FPT_TapTempo")
    if fpt is None:
        return {"ok": False, "error": "midi.FPT_TapTempo not available in this FL version"}
    transport.globalTransport(fpt, 1)
    return {"ok": True}


def h_transport_set_time_signature(p):
    num = int(p.get("numerator", 4))
    den = int(p.get("denominator", 4))
    rec_num = getattr(midi, "REC_MainTimeSigNum", None)
    rec_den = getattr(midi, "REC_MainTimeSigDen", None)
    if rec_num is None or rec_den is None:
        return {"ok": False, "error": "REC_MainTimeSig* not available; set via UI or the General Settings.",
                "numerator": num, "denominator": den}
    flags = midi.REC_Control | midi.REC_UpdateControl
    general.processRECEvent(rec_num, num, flags)
    general.processRECEvent(rec_den, den, flags)
    return {"numerator": num, "denominator": den}


def h_transport_toggle_metronome(_):
    fpt = _fpt("FPT_Metronome")
    if fpt is None:
        return {"ok": False, "error": "midi.FPT_Metronome not available"}
    transport.globalTransport(fpt, 1)
    return {"ok": True}


def h_transport_toggle_countdown(_):
    fpt = _fpt("FPT_CountDown") or _fpt("FPT_CountDownBeforeRecording")
    if fpt is None:
        return {"ok": False, "error": "midi.FPT_CountDown* not available"}
    transport.globalTransport(fpt, 1)
    return {"ok": True}


def h_transport_jog(p):
    steps = int(p.get("steps", 0))
    fpt = _fpt("FPT_Jog")
    if fpt is None:
        return {"ok": False, "error": "midi.FPT_Jog not available"}
    for _ in range(abs(steps)):
        transport.globalTransport(fpt, 1 if steps > 0 else -1)
    return {"steps": steps}


# ---- patterns ---------------------------------------------------------------

def h_patterns_count(_):
    return {"count": patterns.patternCount()}


def h_patterns_current(_):
    idx = patterns.patternNumber()
    return {"index": idx, "name": patterns.getPatternName(idx)}


def h_patterns_list(_):
    out = []
    for i in range(1, patterns.patternCount() + 1):
        out.append({
            "index": i,
            "name": patterns.getPatternName(i),
            "color": _int_to_color_hex(patterns.getPatternColor(i)),
            "length_steps": _safe(patterns.getPatternLength, i),
        })
    return {"patterns": out}


def h_patterns_select(p):
    idx = int(p.get("index", 1))
    patterns.jumpToPattern(idx)
    return {"selected": idx, "name": patterns.getPatternName(idx)}


def h_patterns_create(p):
    name = p.get("name", "")
    # FL appends a new pattern when you setPatternName on patternCount()+1
    new_idx = patterns.patternCount() + 1
    patterns.setPatternName(new_idx, name or ("Pattern %d" % new_idx))
    return {"index": new_idx, "name": patterns.getPatternName(new_idx)}


def h_patterns_rename(p):
    idx = int(p["index"]); name = p.get("name", "")
    patterns.setPatternName(idx, name)
    return {"index": idx, "name": patterns.getPatternName(idx)}


def h_patterns_set_color(p):
    idx = int(p["index"]); color = _color_to_int(p.get("color", "#888888"))
    patterns.setPatternColor(idx, color)
    return {"index": idx, "color": _int_to_color_hex(patterns.getPatternColor(idx))}


def h_patterns_delete(p):
    """FL's public Python API has no deletePattern(). Workaround: rename to empty
    and mark as unused — the pattern stays in the pool but is effectively hidden."""
    idx = int(p["index"])
    patterns.setPatternName(idx, "")
    return {"ok": False,
            "soft_deleted": idx,
            "note": "FL Python API does not expose deletePattern; pattern was renamed to empty."}


def h_patterns_clone(p):
    """clonePattern(index=None) clones the current pattern. We jump first, then clone."""
    src = int(p["index"])
    new_name = p.get("new_name", "") or (patterns.getPatternName(src) + " (copy)")
    patterns.jumpToPattern(src)
    patterns.clonePattern()
    new_idx = patterns.patternCount()
    patterns.setPatternName(new_idx, new_name)
    return {"new_index": new_idx, "name": patterns.getPatternName(new_idx)}


def h_patterns_set_length(p):
    """FL's API does not expose a programmatic pattern-length setter (length is
    derived from notes / step grid)."""
    return {"ok": False,
            "note": "FL Python API does not expose setPatternLength; adjust length by placing notes or step bits instead."}


def h_patterns_find_by_name(p):
    target = (p.get("name") or "").lower().strip()
    for i in range(1, patterns.patternCount() + 1):
        if patterns.getPatternName(i).lower() == target:
            return {"index": i, "name": patterns.getPatternName(i)}
    return {"index": None, "name": None}


def h_patterns_jump_next(_):
    patterns.jumpToPattern(min(patterns.patternNumber() + 1, patterns.patternCount()))
    return h_patterns_current({})


def h_patterns_jump_prev(_):
    patterns.jumpToPattern(max(patterns.patternNumber() - 1, 1))
    return h_patterns_current({})


# ---- channels ---------------------------------------------------------------

def _ch_info(i):
    use_global = True
    return {
        "index": i,
        "name": channels.getChannelName(i, use_global),
        "color": _int_to_color_hex(channels.getChannelColor(i, use_global)),
        "volume": channels.getChannelVolume(i, use_global),
        "pan": channels.getChannelPan(i, use_global),
        "pitch": _safe(channels.getChannelPitch, i),
        "is_muted": channels.isChannelMuted(i, use_global) == 1,
        "is_solo": channels.isChannelSolo(i, use_global) == 1,
        "is_selected": channels.isChannelSelected(i, use_global) == 1,
        "fx_track": channels.getTargetFxTrack(i, use_global),
        "type": _safe(channels.getChannelType, i, use_global),
    }


def h_channels_count(p):
    return {"count": channels.channelCount(bool(p.get("global_count", True)))}


def h_channels_info(p):
    return _ch_info(int(p["index"]))


def h_channels_all(_):
    out = []
    for i in range(channels.channelCount(True)):
        out.append(_ch_info(i))
    return {"channels": out}


def h_channels_selected(_):
    idx = channels.selectedChannel(canBeNone=True, indexGlobal=True)
    if idx is None or idx < 0:
        return {"channel": None}
    return {"channel": _ch_info(idx)}


def h_channels_select(p):
    idx = int(p["index"])
    if p.get("exclusive", True):
        channels.selectOneChannel(idx, True)
    else:
        channels.selectChannel(idx, 1, True)
    return {"selected": idx, "name": channels.getChannelName(idx, True)}


def h_channels_set_volume(p):
    channels.setChannelVolume(int(p["index"]), float(p["volume"]), True)
    return _ch_info(int(p["index"]))


def h_channels_set_pan(p):
    channels.setChannelPan(int(p["index"]), float(p["pan"]), True)
    return _ch_info(int(p["index"]))


def h_channels_set_pitch(p):
    channels.setChannelPitch(int(p["index"]), float(p["semitones"]))
    return _ch_info(int(p["index"]))


def h_channels_mute(p):
    idx = int(p["index"]); muted = p.get("muted")
    if muted is None:
        channels.muteChannel(idx)
    else:
        want = bool(muted)
        is_m = channels.isChannelMuted(idx, True) == 1
        if want != is_m:
            channels.muteChannel(idx)
    return {"index": idx, "is_muted": channels.isChannelMuted(idx, True) == 1}


def h_channels_solo(p):
    idx = int(p["index"]); solo = p.get("solo")
    channels.soloChannel(idx)
    return {"index": idx, "is_solo": channels.isChannelSolo(idx, True) == 1}


def h_channels_set_name(p):
    idx = int(p["index"]); name = p.get("name", "")
    channels.setChannelName(idx, name)
    return _ch_info(idx)


def h_channels_set_color(p):
    idx = int(p["index"])
    channels.setChannelColor(idx, _color_to_int(p["color"]))
    return _ch_info(idx)


def h_channels_route_to_mixer(p):
    idx = int(p["index"]); tr = int(p["mixer_track"])
    channels.setTargetFxTrack(idx, tr)
    return {"index": idx, "mixer_track": channels.getTargetFxTrack(idx, True)}


def h_channels_trigger_note(p):
    idx = int(p["index"]); note = int(p.get("note", 60))
    vel = int(p.get("velocity", 100))
    midi_ch = int(p.get("midi_channel", -1))
    channels.midiNoteOn(idx, note, vel, midi_ch)
    return {"triggered": True, "note": note}


def h_channels_get_grid_bit(p):
    idx = int(p["index"]); pos = int(p["position"])
    return {"value": channels.getGridBit(idx, pos) == 1}


def h_channels_set_grid_bit(p):
    idx = int(p["index"]); pos = int(p["position"]); v = bool(p["value"])
    channels.setGridBit(idx, pos, 1 if v else 0)
    return {"value": channels.getGridBit(idx, pos) == 1}


def h_channels_get_step_sequence(p):
    idx = int(p["index"])
    # pattern length in steps:
    steps = _safe(patterns.getPatternLength, patterns.patternNumber()) or 16
    seq = [channels.getGridBit(idx, s) for s in range(steps)]
    return {"steps": seq, "length": steps}


def h_channels_set_step_sequence(p):
    idx = int(p["index"]); steps = p.get("steps", [])
    for s, v in enumerate(steps):
        channels.setGridBit(idx, s, 1 if v else 0)
    return {"written": len(steps)}


def h_channels_clear_step_sequence(p):
    idx = int(p["index"])
    steps = _safe(patterns.getPatternLength, patterns.patternNumber()) or 16
    for s in range(steps):
        channels.setGridBit(idx, s, 0)
    return {"cleared": steps}


def h_channels_quick_quantize(p):
    idx = int(p["index"])
    channels.selectOneChannel(idx, True)
    channels.quickQuantize()
    return {"ok": True}


def h_channels_sample_info(p):
    """Best-effort source file path of a sampler/audio channel."""
    idx = int(p["channel"])
    info = {"channel": idx, "name": channels.getChannelName(idx, True)}
    if hasattr(channels, "getChannelSamplePath"):
        info["sample_path"] = channels.getChannelSamplePath(idx)
    else:
        info["sample_path"] = None
        info["hint"] = "channels.getChannelSamplePath not available in this FL build"
    return info


# ---- mixer -----------------------------------------------------------------

def _mx_info(i):
    return {
        "index": i,
        "name": mixer.getTrackName(i) or ("Master" if i == 0 else ""),
        "volume": mixer.getTrackVolume(i),
        "volume_db": _safe(mixer.getTrackVolume, i, 1),
        "pan": mixer.getTrackPan(i),
        "stereo_separation": mixer.getTrackStereoSep(i),
        "is_muted": mixer.isTrackMuted(i) == 1,
        "is_solo": mixer.isTrackSolo(i) == 1,
        "is_armed": mixer.isTrackArmed(i) == 1,
        "color": _int_to_color_hex(mixer.getTrackColor(i)),
    }


def h_mixer_count(_):
    return {"count": mixer.trackCount()}


def h_mixer_track_info(p):
    tr = int(p["track"])
    info = _mx_info(tr)
    # fx slots
    slots = []
    for s in range(10):
        try:
            pid = mixer.getTrackPluginId(tr, s)
            valid = plugins.isValid(tr, s, False)
            slots.append({"slot": s, "plugin_id": pid, "valid": bool(valid),
                          "name": plugins.getPluginName(tr, s, 0, False) if valid else None})
        except Exception:
            slots.append({"slot": s, "plugin_id": -1, "valid": False, "name": None})
    info["fx_slots"] = slots
    return info


def h_mixer_all_tracks(p):
    include_empty = bool(p.get("include_empty", False))
    out = []
    for i in range(mixer.trackCount()):
        name = mixer.getTrackName(i)
        if not include_empty and (not name or name.startswith("Insert ")) and i != 0:
            continue
        out.append(_mx_info(i))
    return {"tracks": out}


def h_mixer_set_volume(p):
    mixer.setTrackVolume(int(p["track"]), float(p["volume"]))
    return _mx_info(int(p["track"]))


def h_mixer_set_pan(p):
    mixer.setTrackPan(int(p["track"]), float(p["pan"]))
    return _mx_info(int(p["track"]))


def h_mixer_mute(p):
    tr = int(p["track"]); muted = p.get("muted")
    if muted is None:
        mixer.muteTrack(tr, -1)
    else:
        mixer.muteTrack(tr, 1 if muted else 0)
    return _mx_info(tr)


def h_mixer_solo(p):
    tr = int(p["track"]); solo = p.get("solo")
    mode = int(p.get("mode", 3))
    if solo is None:
        mixer.soloTrack(tr, -1, mode)
    else:
        mixer.soloTrack(tr, 1 if solo else 0, mode)
    return _mx_info(tr)


def h_mixer_arm(p):
    tr = int(p["track"])
    mixer.armTrack(tr)
    return _mx_info(tr)


def h_mixer_record_arm(p):
    """Arm/disarm a mixer track for disk recording and report the target file.

    Flow (orchestrated by the MCP server, which CAN read files):
    arm -> transport record+play -> FL writes WAV -> disarm -> server reads it.
    """
    tr = int(p["track"])
    want = bool(p.get("armed", True))
    if (mixer.isTrackArmed(tr) == 1) != want:
        mixer.armTrack(tr)  # armTrack is a toggle
    result = {"track": tr, "armed": mixer.isTrackArmed(tr) == 1}
    if hasattr(mixer, "getTrackRecordingFileName"):
        result["recording_file"] = _safe(mixer.getTrackRecordingFileName, tr)
    else:
        result["recording_file"] = None
        result["hint"] = "mixer.getTrackRecordingFileName not available in this FL build"
    return result


def h_mixer_set_name(p):
    mixer.setTrackName(int(p["track"]), p.get("name", ""))
    return _mx_info(int(p["track"]))


def h_mixer_set_color(p):
    mixer.setTrackColor(int(p["track"]), _color_to_int(p["color"]))
    return _mx_info(int(p["track"]))


def h_mixer_set_stereo_sep(p):
    mixer.setTrackStereoSep(int(p["track"]), float(p["separation"]))
    return _mx_info(int(p["track"]))


def h_mixer_set_send_level(p):
    src = int(p["src_track"]); dst = int(p["dst_track"]); lvl = float(p["level"])
    # ensure the route exists, then set its level
    mixer.setRouteTo(src, dst, True, False)
    if hasattr(mixer, "setRouteToLevel"):
        mixer.setRouteToLevel(src, dst, lvl)
    mixer.afterRoutingChanged()
    return {"src": src, "dst": dst,
            "level": mixer.getRouteToLevel(src, dst) if hasattr(mixer, "getRouteToLevel") else lvl}


def h_mixer_route(p):
    enabled = bool(p.get("enabled", True))
    mixer.setRouteTo(int(p["src_track"]), int(p["dst_track"]), enabled, False)
    mixer.afterRoutingChanged()
    return {"enabled": enabled,
            "active": mixer.getRouteSendActive(int(p["src_track"]), int(p["dst_track"]))
            if hasattr(mixer, "getRouteSendActive") else None}


def h_mixer_fx_slots(p):
    tr = int(p["track"])
    slots = []
    for s in range(10):
        try:
            pid = mixer.getTrackPluginId(tr, s)
            valid = plugins.isValid(tr, s, False)
            slots.append({"slot": s, "plugin_id": pid, "valid": bool(valid),
                          "name": plugins.getPluginName(tr, s, 0, False) if valid else None})
        except Exception:
            slots.append({"slot": s, "plugin_id": -1, "valid": False, "name": None})
    return {"slots": slots}


def h_mixer_select(p):
    mixer.setActiveTrack(int(p["track"]))
    return {"selected": int(p["track"])}


def h_mixer_get_eq(p):
    tr = int(p["track"])
    band_count = mixer.getEqBandCount() if hasattr(mixer, "getEqBandCount") else 3
    bands = []
    for b in range(band_count):
        bands.append({
            "band": b,
            "gain": _safe(mixer.getEqGain, tr, b),
            "frequency": _safe(mixer.getEqFrequency, tr, b),
            "bandwidth": _safe(mixer.getEqBandwidth, tr, b),
        })
    return {"bands": bands, "band_count": band_count}


def h_mixer_set_eq_band(p):
    tr = int(p["track"]); band = int(p["band"])
    if p.get("gain") is not None:
        _safe(mixer.setEqGain, tr, band, float(p["gain"]))
    if p.get("frequency") is not None:
        _safe(mixer.setEqFrequency, tr, band, float(p["frequency"]))
    if p.get("bandwidth") is not None and hasattr(mixer, "setEqBandwidth"):
        _safe(mixer.setEqBandwidth, tr, band, float(p["bandwidth"]))
    return h_mixer_get_eq({"track": tr})


def h_mixer_link_channel(p):
    """Link a channel to a mixer track. `mode` legacy param is kept for API compat."""
    ch = int(p["channel"]); tr = int(p["track"])
    select = bool(p.get("select", False))
    if hasattr(mixer, "linkChannelToTrack"):
        mixer.linkChannelToTrack(ch, tr, select)
    else:
        channels.setTargetFxTrack(ch, tr)
    return {"channel": ch, "track": tr}


def h_mixer_plugin_mix_level(p):
    """Read or write the wet/dry mix level of an FX slot plugin.
    level: 0.0 = 100% dry, 1.0 = 100% wet. Omit to read only."""
    track = int(p.get("track", 1))
    slot = int(p.get("slot", 0))
    if "level" in p:
        try:
            mixer.setPluginMixLevel(track, slot, float(p["level"]))
        except Exception as e:
            return {"ok": False, "error": str(e)}
    try:
        level = mixer.getPluginMixLevel(track, slot)
        return {"ok": True, "track": track, "slot": slot, "mix_level": level}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def h_mixer_track_slots_enabled(p):
    """Enable or bypass ALL FX slots on a mixer track at once.
    enabled=True → all slots active; enabled=False → all bypassed.
    Omit 'enabled' to read current state."""
    track = int(p.get("track", 1))
    if "enabled" in p:
        try:
            mixer.enableTrackSlots(track, bool(p["enabled"]))
        except Exception as e:
            return {"ok": False, "error": str(e)}
    try:
        return {"ok": True, "track": track,
                "slots_enabled": bool(mixer.isTrackSlotsEnabled(track))}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def h_mixer_stereo_advanced(p):
    """Read/write polarity inversion and L/R swap for a mixer track.
    Pass rev_polarity=True/False or swap_channels=True/False to set;
    omit to read only. Always returns current state."""
    track = int(p.get("track", 1))
    if "rev_polarity" in p:
        try:
            want = bool(p["rev_polarity"])
            if bool(mixer.isTrackRevPolarity(track)) != want:
                mixer.revTrackPolarity(track)
        except Exception as e:
            return {"ok": False, "error": "rev_polarity: " + str(e)}
    if "swap_channels" in p:
        try:
            want = bool(p["swap_channels"])
            if bool(mixer.isTrackSwapChannels(track)) != want:
                mixer.swapTrackChannels(track)
        except Exception as e:
            return {"ok": False, "error": "swap_channels: " + str(e)}
    result = {"ok": True, "track": track}
    for key, fn in [
        ("stereo_sep",   lambda: mixer.getTrackStereoSep(track)),
        ("rev_polarity", lambda: bool(mixer.isTrackRevPolarity(track))),
        ("swap_channels", lambda: bool(mixer.isTrackSwapChannels(track))),
    ]:
        try:
            result[key] = fn()
        except Exception:
            result[key] = None
    return result


# ---- plugins ---------------------------------------------------------------

def _resolve_plugin_loc(p):
    location = p.get("location", "channel")
    slot = int(p.get("slot", -1))
    index = int(p["index"])
    # plugins.* API: (index, slot, useGlobalIndex)
    useGlobal = (location == "channel")
    return index, slot, useGlobal


def h_plugins_is_valid(p):
    idx, slot, ug = _resolve_plugin_loc(p)
    return {"valid": plugins.isValid(idx, slot, ug) == 1}


def h_plugins_name(p):
    idx, slot, ug = _resolve_plugin_loc(p)
    return {"name": plugins.getPluginName(idx, slot, 0, ug)}


def h_plugins_param_count(p):
    idx, slot, ug = _resolve_plugin_loc(p)
    return {"count": plugins.getParamCount(idx, slot, ug)}


def h_plugins_params(p):
    idx, slot, ug = _resolve_plugin_loc(p)
    limit = int(p.get("limit", 128))
    offset = int(p.get("offset", 0))
    n = plugins.getParamCount(idx, slot, ug)
    out = []
    for i in range(offset, min(offset + limit, n)):
        try:
            out.append({
                "idx": i,
                "name": plugins.getParamName(i, idx, slot, ug),
                "value": plugins.getParamValue(i, idx, slot, ug),
                "value_string": plugins.getParamValueString(i, idx, slot, ug),
            })
        except Exception:
            pass
    return {"total": n, "params": out}


def h_plugins_get_param(p):
    idx, slot, ug = _resolve_plugin_loc(p)
    pid = int(p["param"])
    return {
        "value": plugins.getParamValue(pid, idx, slot, ug),
        "value_string": plugins.getParamValueString(pid, idx, slot, ug),
    }


def h_plugins_set_param(p):
    idx, slot, ug = _resolve_plugin_loc(p)
    pid = int(p["param"]); v = float(p["value"])
    plugins.setParamValue(v, pid, idx, slot, ug)
    return {
        "value": plugins.getParamValue(pid, idx, slot, ug),
        "value_string": plugins.getParamValueString(pid, idx, slot, ug),
    }


MAX_BATCH_CHANGES = 128


def h_plugins_set_params(p):
    """Batch parameter writes: one TCP round-trip, N setParamValue calls.

    Applies up to MAX_BATCH_CHANGES (128) changes per call; excess changes are
    dropped and a truncation error entry is appended to the response.
    This path does not read back values after writing — callers needing
    confirmed values should follow up with plugins.getParam.
    """
    try:
        idx, slot, ug = _resolve_plugin_loc(p)
    except Exception as exc:
        return {"applied": 0, "errors": [{"pos": None, "index": None, "error": "invalid location: " + str(exc)}]}
    changes = p.get("changes", [])
    applied = 0
    errors = []
    truncated = len(changes) > MAX_BATCH_CHANGES
    work = changes[:MAX_BATCH_CHANGES]
    for i, change in enumerate(work):
        try:
            pid = int(change["index"]); v = float(change["value"])
            plugins.setParamValue(v, pid, idx, slot, ug)
            applied += 1
        except Exception as exc:
            errors.append({"pos": i, "index": change.get("index"), "error": str(exc)})
    if truncated:
        errors.append({"pos": None, "index": None, "error": "batch truncated to 128 changes (got %d)" % len(changes)})
    return {"applied": applied, "errors": errors}


def h_plugins_find_param(p):
    idx, slot, ug = _resolve_plugin_loc(p)
    needle = (p.get("name_contains") or "").lower()
    n = plugins.getParamCount(idx, slot, ug)
    hits = []
    for i in range(n):
        try:
            nm = plugins.getParamName(i, idx, slot, ug)
            if needle in nm.lower():
                hits.append({"idx": i, "name": nm,
                             "value": plugins.getParamValue(i, idx, slot, ug)})
        except Exception:
            pass
    return {"matches": hits}


def h_plugins_preset_count(p):
    idx, slot, ug = _resolve_plugin_loc(p)
    return {"count": plugins.getPresetCount(idx, slot, ug)}


def h_plugins_next_preset(p):
    idx, slot, ug = _resolve_plugin_loc(p)
    plugins.nextPreset(idx, slot, ug)
    return {"ok": True}


def h_plugins_prev_preset(p):
    idx, slot, ug = _resolve_plugin_loc(p)
    plugins.prevPreset(idx, slot, ug)
    return {"ok": True}


def h_plugins_set_preset(p):
    idx, slot, ug = _resolve_plugin_loc(p)
    plugins.setPreset(int(p["preset"]), idx, slot, ug)
    return {"ok": True}


def h_plugins_set_param_rec(p):
    """DISABLED — processRECEvent with plugin param event IDs causes FL Studio
    to crash with an access violation in FLEngine_x64.dll.
    The formula mixer.getTrackPluginId()+paramIdx is NOT the correct event ID.
    Use plugins.setPreset to activate bands instead."""
    return {"ok": False, "error": "disabled: processRECEvent formula caused FL crash"}


def h_plugins_show_editor(p):
    idx, slot, ug = _resolve_plugin_loc(p)
    show = p.get("show")
    try:
        if show is None:
            channels.showEditor(idx, -1)
        else:
            channels.showEditor(idx, 1 if show else 0)
    except Exception:
        pass
    return {"ok": True}


def h_plugins_list_mixer_track(p):
    tr = int(p["track"])
    out = []
    for s in range(10):
        try:
            valid = plugins.isValid(tr, s, False) == 1
            out.append({
                "slot": s,
                "valid": valid,
                "name": plugins.getPluginName(tr, s, 0, False) if valid else None,
                "param_count": plugins.getParamCount(tr, s, False) if valid else 0,
            })
        except Exception:
            out.append({"slot": s, "valid": False, "name": None, "param_count": 0})
    return {"slots": out}


def h_plugins_load_attempt(_):
    """Probe runtime API for plugin-loading capabilities + full module attribute dump."""
    # Quick hasattr checks
    report = {}
    for mod, fn in ((mixer, "loadPlugin"), (plugins, "load"),
                    (channels, "addChannel"), (mixer, "trackPluginLoad")):
        report["%s.%s" % (mod.__name__, fn)] = hasattr(mod, fn)
    for fn in ("navigateBrowser", "selectBrowserMenuItem", "findBrowserItem",
               "getFocusedNodeCaption", "enterBrowserMenu", "previewBrowserMenuItem"):
        report["ui.%s" % fn] = hasattr(ui, fn)

    # Full attribute dump for mixer and ui
    full = {}
    for mod in (mixer, ui):
        attrs = []
        for name in sorted(dir(mod)):
            if not name.startswith("_"):
                attrs.append(name)
        full[mod.__name__] = attrs

    return {"strategies": report, "all_attrs": full}


def h_meta_sandbox_probe(_):
    """Ground-truth sandbox probe — what does FL 2025's subinterpreter allow?

    Gathers IPC-capability evidence on demand over the working MIDI channel.
    Reports live listener state + fresh capability tests for socket / bind /
    thread / file / ctypes so transport decisions rest on proof, not inference.

    VERDICT (2026-06-14): everything except MIDI SysEx is hard-blocked —
    socket/thread/file constructors return NULL, _ctypes won't import in the
    subinterpreter. MIDI SysEx is the only viable transport. See LECONS-APPRISES.
    """
    result = {}

    # --- live TCP listener state (set at OnInit by _start_listening) ---
    result["accept_socket_active"] = _accept_socket is not None
    result["bind_attempts"] = _bind_attempts
    result["midi_active"] = _midi_active
    result["bridge_host"] = BRIDGE_HOST
    result["bridge_port"] = BRIDGE_PORT

    # --- can we create a TCP socket? ---
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.close()
        result["socket_create"] = "OK"
    except BaseException as e:
        result["socket_create"] = "BLOCKED: %s: %s" % (type(e).__name__, e)

    # --- can we bind + listen on an ephemeral port (non-blocking)? ---
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((BRIDGE_HOST, 0))
        port = s.getsockname()[1]
        s.listen(1)
        s.setblocking(False)
        s.close()
        result["socket_bind_listen"] = "OK (ephemeral %d)" % port
    except BaseException as e:
        result["socket_bind_listen"] = "BLOCKED: %s: %s" % (type(e).__name__, e)

    # --- can we self-connect to the bridge's own listener on 9876? ---
    if _accept_socket is not None:
        try:
            c = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            c.settimeout(1.0)
            c.connect((BRIDGE_HOST, BRIDGE_PORT))
            c.close()
            result["self_connect_9876"] = "OK — listener reachable"
        except BaseException as e:
            result["self_connect_9876"] = "FAIL: %s: %s" % (type(e).__name__, e)

    # --- thread creation (the original geezoria blocker)? ---
    try:
        import threading
        flag = {"ran": False}
        th = threading.Thread(target=lambda: flag.__setitem__("ran", True))
        th.start()
        th.join(timeout=1.0)
        result["thread_create"] = "OK (ran=%s)" % flag["ran"]
    except BaseException as e:
        result["thread_create"] = "BLOCKED: %s: %s" % (type(e).__name__, e)

    # --- file write (Calvin's file-bus approach)? ---
    try:
        p = os.path.join(os.path.expanduser("~"), "flmcp_probe2.txt")
        with open(p, "w") as f:
            f.write("ok")
        os.remove(p)
        result["file_write"] = "OK"
    except BaseException as e:
        result["file_write"] = "BLOCKED: %s: %s" % (type(e).__name__, e)

    # --- ctypes availability (does the FFI bridge to the OS work at all?) ---
    try:
        import ctypes
        tick = ctypes.windll.kernel32.GetTickCount()
        result["ctypes_kernel32"] = "OK (tick=%d)" % tick
    except BaseException as e:
        result["ctypes_kernel32"] = "BLOCKED: %s: %s" % (type(e).__name__, e)

    # --- ctypes file-bus: write + read back a file via raw Win32 API ---
    # If this works while Python open() is NULL-stubbed, we have a fast IPC
    # channel (local disk poll ~1ms) that bypasses the sandbox's io block.
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32
        k32.CreateFileW.restype = wintypes.HANDLE
        k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                    wintypes.DWORD, wintypes.LPVOID,
                                    wintypes.DWORD, wintypes.DWORD,
                                    wintypes.HANDLE]
        GENERIC_WRITE = 0x40000000
        GENERIC_READ = 0x80000000
        CREATE_ALWAYS = 2
        OPEN_EXISTING = 3
        FILE_ATTR_NORMAL = 0x80
        INVALID = wintypes.HANDLE(-1).value
        path = os.path.join(os.path.expanduser("~"), "flmcp_ctypes_bus.txt")

        # write
        h = k32.CreateFileW(path, GENERIC_WRITE, 0, None,
                            CREATE_ALWAYS, FILE_ATTR_NORMAL, None)
        if h == INVALID:
            result["ctypes_file_bus"] = "FAIL CreateFileW(write) err=%d" % k32.GetLastError()
        else:
            payload = b'{"flmcp":"ctypes-bus-ok"}'
            written = wintypes.DWORD(0)
            ok = k32.WriteFile(h, payload, len(payload),
                               ctypes.byref(written), None)
            k32.CloseHandle(h)
            # read back
            h2 = k32.CreateFileW(path, GENERIC_READ, 1, None,
                                 OPEN_EXISTING, FILE_ATTR_NORMAL, None)
            buf = ctypes.create_string_buffer(64)
            read = wintypes.DWORD(0)
            ok2 = k32.ReadFile(h2, buf, 64, ctypes.byref(read), None)
            k32.CloseHandle(h2)
            got = buf.raw[:read.value]
            # cleanup via ctypes DeleteFileW
            k32.DeleteFileW(path)
            result["ctypes_file_bus"] = (
                "OK wrote=%d read=%d match=%s"
                % (written.value, read.value, got == payload))
    except BaseException as e:
        result["ctypes_file_bus"] = "BLOCKED: %s: %s" % (type(e).__name__, e)

    return result


def h_browser_probe_nav(_):
    """Map the FL Studio browser structure using navigateBrowserTabs, navigateBrowserMenu,
    and toggleBrowserNode.

    ⚠️  SAFETY: navigateBrowserTabs/navigateBrowserMenu cause a native FL Studio crash
    ("Cannot focus a disabled or invisible window") if the browser panel is not open.
    We MUST open the browser first. The crash is native — no Python try/except can catch it.
    """
    result = {
        "browser_open_attempts": [],
        "initial": {},
        "tabs": [],
        "menu_steps": [],
        "toggle_test": None,
        "final": {},
    }

    def _snap():
        try:
            cap = ui.getFocusedNodeCaption()
        except Exception as e:
            cap = "ERR:" + str(e)
        try:
            ftype = ui.getFocusedNodeFileType()
        except Exception as e:
            ftype = "ERR:" + str(e)
        return {"caption": cap, "fileType": ftype}

    # --- 0. CRITICAL: Open browser before any navigation ---
    # navigateBrowserTabs crashes FL Studio natively if browser is hidden.
    # Try every known method to make the browser visible.
    opened = False
    for label, fn in [
        ("showBrowser", lambda: getattr(ui, "showBrowser")()),
        ("showWindow(4)", lambda: ui.showWindow(4)),
        ("setFocused(4)", lambda: ui.setFocused(4)),
        ("showWindow(0)", lambda: ui.showWindow(0)),  # last resort: mixer focus
    ]:
        try:
            fn()
            result["browser_open_attempts"].append({"method": label, "ok": True})
            opened = True
            break
        except Exception as e:
            result["browser_open_attempts"].append({"method": label, "error": str(e)})

    if not opened:
        result["error"] = "Could not open browser panel — aborting to prevent crash"
        return result

    # --- 1. Record initial state ---
    result["initial"] = _snap()

    # --- 2. Probe navigateBrowserTabs: step through tabs forward (max 12) ---
    for i in range(12):
        try:
            ui.navigateBrowserTabs(1, 1)
            s = _snap()
            s["tab_step"] = i + 1
            result["tabs"].append(s)
            if "mixer" in s["caption"].lower() or "preset" in s["caption"].lower():
                s["TARGET_FOUND"] = True
        except Exception as e:
            result["tabs"].append({"tab_step": i + 1, "error": str(e)})
            break

    # --- 3. Probe navigateBrowserMenu (up to 20 steps down) ---
    for i in range(20):
        try:
            ui.navigateBrowserMenu(1, 1)
            s = _snap()
            s["menu_step"] = i + 1
            result["menu_steps"].append(s)
            if "mixer" in s["caption"].lower() or "preset" in s["caption"].lower():
                s["TARGET_FOUND"] = True
                try:
                    ui.toggleBrowserNode()
                    after = _snap()
                    result["toggle_test"] = {"before": s["caption"], "after_toggle": after}
                except Exception as te:
                    result["toggle_test"] = {"error": str(te)}
                break
        except Exception as e:
            result["menu_steps"].append({"menu_step": i + 1, "error": str(e)})
            break

    # --- 4. Final state ---
    result["final"] = _snap()
    return result


def h_plugins_probe_api(_):
    """Return all callable attributes of ALL FL Studio API modules."""
    result = {}
    for mod in (plugins, mixer, ui, channels, transport, patterns,
                playlist, general, arrangement, device):
        attrs = {}
        for name in dir(mod):
            if name.startswith("_"):
                continue
            try:
                obj = getattr(mod, name)
                attrs[name] = callable(obj)
            except Exception:
                pass
        result[mod.__name__] = attrs
    return result


def h_plugins_probe_browser_nav(_):
    """Targeted probe to gather evidence for browser navigation:
    1. Introspect ui.navigateBrowser signature.
    2. Test ui.showWindow(wid) for wid 0-9 and read getFocusedNodeCaption after each.
    3. Find which wid gives a non-empty, non-plugin caption (= browser).
    Returns raw evidence dict for analysis.
    """
    import inspect
    result = {}

    # --- navigateBrowser signature ---
    nb = getattr(ui, "navigateBrowser", None)
    if nb:
        try:
            sig = inspect.getfullargspec(nb)
            result["navigateBrowser_argspec"] = str(sig)
        except Exception as e:
            result["navigateBrowser_argspec_error"] = str(e)
        # Also try __doc__
        result["navigateBrowser_doc"] = getattr(nb, "__doc__", None)
        # Try calling with (direction, step) to find correct signature
        for args in [(1,), (1, 1), (0, 1), (1, 0)]:
            try:
                nb(*args)
                result["navigateBrowser_working_call"] = str(args)
                break
            except TypeError as e:
                result["navigateBrowser_try_%s" % str(args)] = "TypeError: %s" % e
            except Exception as e:
                result["navigateBrowser_try_%s" % str(args)] = str(e)
    else:
        result["navigateBrowser"] = "NOT FOUND"

    # --- focusEditor signature probe ---
    fe = getattr(mixer, "focusEditor", None)
    if fe:
        result["focusEditor_doc"] = getattr(fe, "__doc__", None)
        for args in [(3,), (3, 0), (3, 1)]:
            try:
                fe(*args)
                result["focusEditor_working_call"] = str(args)
                break
            except Exception as e:
                result["focusEditor_try_%s" % str(args)] = "%s: %s" % (type(e).__name__, e)

    # --- showWindow + caption probe ---
    windows = {}
    for wid in range(12):
        entry = {}
        try:
            ui.showWindow(wid)
            cap_after = ui.getFocusedNodeCaption()
            ftype_after = getattr(ui, "getFocusedNodeFileType", lambda: -999)()
            visible = ui.getVisible(wid)
            entry["caption"] = cap_after
            entry["ftype"] = ftype_after
            entry["visible"] = visible
            entry["show"] = "ok"
        except Exception as e:
            entry["show_error"] = "%s: %s" % (type(e).__name__, e)
        windows[str(wid)] = entry
    result["windows"] = windows

    # --- current focus state ---
    try:
        result["getFocusedFormID"] = ui.getFocusedFormID()
        result["getFocusedFormCaption"] = ui.getFocusedFormCaption()
        result["getFocusedNodeCaption"] = ui.getFocusedNodeCaption()
        result["getFocusedNodeFileType"] = getattr(ui, "getFocusedNodeFileType", lambda: -999)()
    except Exception as e:
        result["focus_state_error"] = str(e)

    return result


def h_mixer_load_fst(p):
    """Load a Mixer State (.fst) file onto a mixer track via browser navigation.

    The FST must be named _MCP.fst and placed in the same folder as the other
    mixer presets — it will sort first (underscore < letters) so it is always
    reachable in at most MAX_SCAN steps from whatever item is currently focused.

    p: {"track": int, "fst_path": str}
    fst_path is used only for verification; the actual navigation targets the
    first _MCP.fst in the browser list.

    Returns: {"ok": bool, "log": list}
    """
    track = int(p.get("track", 1))
    fst_name = "_MCP.fst"
    MAX_SCAN = 30   # well under any timeout
    log = []

    # Step 1 — select the target mixer track
    try:
        mixer.setActiveTrack(track)
        log.append({"step": "setActiveTrack", "track": track, "ok": True})
    except Exception as e:
        return {"ok": False, "log": log, "error": str(e)}

    # Step 2 — read where the browser is now
    start_cap = ui.getFocusedNodeCaption()
    log.append({"step": "start_caption", "caption": start_cap})

    # Step 3 — scan UP to find _MCP.fst (it sorts before all alpha names)
    found = False
    for i in range(MAX_SCAN):
        try:
            cap = ui.getFocusedNodeCaption()
            if fst_name.lower() in cap.lower():
                found = True
                log.append({"step": "found", "caption": cap, "steps": i})
                break
            ui.navigateBrowser(-1, 1)   # go up one item
        except Exception as e:
            log.append({"step": "scan_up_error", "i": i, "error": str(e)})
            break

    # If not found going up, try scanning DOWN from start
    if not found:
        # Return to start position
        ui.navigateBrowser(1, MAX_SCAN)
        for i in range(MAX_SCAN):
            try:
                cap = ui.getFocusedNodeCaption()
                if fst_name.lower() in cap.lower():
                    found = True
                    log.append({"step": "found_down", "caption": cap, "steps": i})
                    break
                ui.navigateBrowser(1, 1)
            except Exception as e:
                log.append({"step": "scan_down_error", "i": i, "error": str(e)})
                break

    if not found:
        return {"ok": False, "log": log,
                "error": "_MCP.fst not found in browser within %d steps" % MAX_SCAN}

    # Step 4 — load the focused FST onto the active track
    try:
        ui.selectBrowserMenuItem()
        log.append({"step": "selectBrowserMenuItem", "ok": True})
    except Exception as e:
        return {"ok": False, "log": log, "error": str(e)}

    # Step 5 — verify slots filled
    slots = []
    for slot in range(10):
        try:
            valid = bool(plugins.isValid(track, slot, False))
            name = plugins.getPluginName(track, slot, 0, False) if valid else None
            slots.append({"slot": slot, "valid": valid, "name": name})
        except Exception:
            slots.append({"slot": slot, "valid": False, "name": None})

    log.append({"step": "slots_after", "slots": slots})
    loaded = [s for s in slots if s["valid"]]
    return {"ok": True, "log": log, "loaded_plugins": loaded}


def h_plugins_load_via_ui(p):
    """Load a plugin into a mixer FX slot using FL Studio UI browser navigation.

    Strategy v3 — based on confirmed evidence:
    - navigateBrowser(direction, step) WORKS: direction 1=down, -1=up
    - selectBrowserMenuItem() LOADS the focused item into active track FX chain
    - showWindow(4) opens a plugin window, NOT the browser panel
    - We must NOT call selectBrowserMenuItem if plugin was not found

    p: {"track": int, "plugin_name": str, "max_steps": int (default 300)}
    Returns step-by-step log with found/not-found status.
    """
    track = int(p["track"])
    plugin_name = str(p.get("plugin_name", "Fruity Parametric EQ 2"))
    max_steps = int(p.get("max_steps", 150))
    log = []

    # Step 1 — set active track (determines which track receives the plugin)
    try:
        mixer.setActiveTrack(track)
        log.append({"step": "setActiveTrack", "track": track, "ok": True})
    except Exception as e:
        log.append({"step": "setActiveTrack", "ok": False, "error": str(e)})
        return {"log": log, "found": False, "error": str(e)}

    # Step 2 — read current browser position
    try:
        start_caption = ui.getFocusedNodeCaption()
        log.append({"step": "start_caption", "caption": start_caption})
    except Exception as e:
        start_caption = ""
        log.append({"step": "start_caption_error", "error": str(e)})

    # Step 3 — choose direction: compare target vs. current alphabetically
    # strip "Fruity Wrapper - " prefix for fair alphabetical comparison
    def _clean(s):
        return s.lower().replace("fruity wrapper - ", "").strip()

    target_key = _clean(plugin_name)
    current_key = _clean(start_caption)
    # direction: -1 = up (go earlier in alphabet), 1 = down (go later)
    direction = -1 if target_key < current_key else 1
    log.append({"step": "direction_chosen", "direction": direction,
                "target_key": target_key, "current_key": current_key})

    # Step 4 — fast search: big jump in chosen direction, then fine scan back
    # Strategy: jump JUMP_SIZE items at once (1 call), then scan fine (1-by-1)
    # This keeps total Python calls low (~2 + JUMP_SIZE) to avoid MCP timeout.
    JUMP_SIZE = 80
    found_plugin = False
    found_caption = None

    # Big jump in primary direction (1 call)
    try:
        ui.navigateBrowser(direction, JUMP_SIZE)
        cap_after_jump = ui.getFocusedNodeCaption()
        log.append({"step": "big_jump", "direction": direction,
                    "size": JUMP_SIZE, "caption": cap_after_jump})
    except Exception as e:
        log.append({"step": "big_jump_error", "error": str(e)})

    # Fine scan in opposite direction (up to JUMP_SIZE*2 steps)
    scan_dir = -direction  # scan back toward original position and beyond
    for i in range(JUMP_SIZE * 2):
        try:
            cap = ui.getFocusedNodeCaption()
            if plugin_name.lower() in cap.lower():
                found_plugin = True
                found_caption = cap
                log.append({"step": "plugin_found", "steps": i, "caption": cap})
                break
            ui.navigateBrowser(scan_dir, 1)
        except Exception as e:
            log.append({"step": "scan_error", "i": i, "error": str(e)})
            break

    if not found_plugin:
        log.append({"step": "not_found_after", "steps": JUMP_SIZE * 2})

    if not found_plugin:
        log.append({"step": "plugin_not_found", "max_steps": max_steps})
        return {"log": log, "found": False}

    # Step 5 — load: only reached if plugin was found
    try:
        ui.selectBrowserMenuItem()
        log.append({"step": "selectBrowserMenuItem", "ok": True, "loaded": found_caption})
    except Exception as e:
        log.append({"step": "selectBrowserMenuItem", "ok": False, "error": str(e)})
        return {"log": log, "found": True, "loaded": False, "error": str(e)}

    # Step 6 — verify all slots on target track
    slots_after = []
    for slot in range(10):
        try:
            valid = bool(plugins.isValid(track, slot, False))
            name = plugins.getPluginName(track, slot, 0, False) if valid else None
            slots_after.append({"slot": slot, "valid": valid, "name": name})
        except Exception:
            slots_after.append({"slot": slot, "valid": False, "name": None})
    log.append({"step": "slots_after", "slots": slots_after})

    return {"log": log, "found": True, "loaded": True,
            "loaded_plugin": found_caption, "slots": slots_after}


def h_plugins_set_slot_enabled(p):
    """Enable (True) or bypass (False) one FX slot green button.

    Strategy 1 — plugins.isEnabled / setEnabled (FL 2025 may expose this).
    Strategy 2 — mixer slot param index 0 controls bypass in some builds.
    Returns {"ok": bool, "enabled": bool, "strategy": str}.
    """
    idx, slot, ug = _resolve_plugin_loc(p)
    enabled = bool(p.get("enabled", True))

    # Strategy 1: explicit setEnabled API (not always present)
    if hasattr(plugins, "setEnabled"):
        try:
            plugins.setEnabled(idx, slot, 1 if enabled else 0, ug)
            actual = bool(plugins.isEnabled(idx, slot, ug)) if hasattr(plugins, "isEnabled") else enabled
            return {"ok": True, "enabled": actual, "strategy": "plugins.setEnabled"}
        except Exception as e:
            pass  # fall through

    # Strategy 2: FL stores bypass state as a special param at index -1 or 0
    # Some builds expose it via setParamValue with pid=-1
    for pid in (-1, 0):
        try:
            plugins.setParamValue(1.0 if enabled else 0.0, pid, idx, slot, ug)
            return {"ok": True, "enabled": enabled, "strategy": "setParamValue(pid=%d)" % pid}
        except Exception:
            pass

    return {"ok": False, "enabled": None,
            "error": "no enable/disable API found — check plugins.probeApi"}


def h_plugins_remove_from_slot(p):
    """Remove the plugin loaded in a mixer FX slot.

    Strategy 1 — mixer.removeTrackPlugin (FL 2025).
    Strategy 2 — set plugin ID to 0 via mixer internals.
    Returns {"ok": bool, "strategy": str}.
    """
    track = int(p["index"])
    slot = int(p.get("slot", 0))

    # Strategy 1: dedicated remove function
    if hasattr(mixer, "removeTrackPlugin"):
        try:
            mixer.removeTrackPlugin(track, slot)
            return {"ok": True, "strategy": "mixer.removeTrackPlugin"}
        except Exception as e:
            pass

    # Strategy 2: set slot plugin ID to 0 — clears the slot in some builds
    if hasattr(mixer, "setTrackPluginId"):
        try:
            mixer.setTrackPluginId(track, slot, 0)
            return {"ok": True, "strategy": "mixer.setTrackPluginId(0)"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    return {"ok": False, "error": "no plugin removal API found"}


# ---- sidechain / send routing ----------------------------------------------

def h_mixer_sidechain(p):
    """Configure a send/sidechain route between two mixer tracks.

    Sets the route from src_track → dst_track enabled, optionally
    controlling the send level (0.0 = -INF, 1.0 = 0 dB / unity).

    Args:
        src_track: source track index
        dst_track: destination track index
        enabled: True (default) to activate route
        level: send level 0.0..1.0 (default 1.0)
    """
    src = int(p["src_track"])
    dst = int(p["dst_track"])
    enabled = bool(p.get("enabled", True))
    level = float(p.get("level", 1.0))

    mixer.setRouteTo(src, dst, enabled, False)
    mixer.afterRoutingChanged()

    if enabled and hasattr(mixer, "setRouteToLevel"):
        try:
            mixer.setRouteToLevel(src, dst, level)
        except Exception:
            pass

    active = None
    if hasattr(mixer, "getRouteSendActive"):
        try:
            active = bool(mixer.getRouteSendActive(src, dst))
        except Exception:
            pass

    actual_level = level
    if enabled and hasattr(mixer, "getRouteToLevel"):
        try:
            actual_level = mixer.getRouteToLevel(src, dst)
        except Exception:
            pass

    return {"src": src, "dst": dst, "enabled": enabled,
            "active": active, "level": actual_level}


def h_mixer_get_route_info(p):
    """Read the routing / send state between two mixer tracks.

    Returns whether the route is active and its current send level.
    """
    src = int(p["src_track"])
    dst = int(p["dst_track"])
    active = None
    level = None
    if hasattr(mixer, "getRouteSendActive"):
        try:
            active = bool(mixer.getRouteSendActive(src, dst))
        except Exception:
            pass
    if hasattr(mixer, "getRouteToLevel"):
        try:
            level = mixer.getRouteToLevel(src, dst)
        except Exception:
            pass
    return {"src": src, "dst": dst, "active": active, "level": level}


def h_plugins_get_slot_info(p):
    """Return enabled state + name for one FX slot (single round-trip).

    Combines plugins.isValid, plugins.isEnabled and plugins.getPluginName.
    """
    track = int(p["index"])
    slot = int(p.get("slot", 0))
    valid = bool(plugins.isValid(track, slot, False) == 1)
    name = plugins.getPluginName(track, slot, 0, False) if valid else None
    enabled = None
    if valid:
        if hasattr(plugins, "isEnabled"):
            try:
                enabled = bool(plugins.isEnabled(track, slot, False))
            except Exception:
                pass
        if enabled is None:
            enabled = True  # assume enabled if API doesn't expose it
    return {"track": track, "slot": slot, "valid": valid,
            "name": name, "enabled": enabled}


def h_mixer_get_peaks(p):
    """Read audio peak levels for a mixer track (left + right channels).

    Returns normalised 0.0..1.0 values. Only available in FL builds that
    expose mixer.getTrackPeaks; returns null when not supported.
    """
    track = int(p["track"])
    mode = int(p.get("mode", 0))  # 0=peak, 1=RMS (if supported)
    if hasattr(mixer, "getTrackPeaks"):
        try:
            left = mixer.getTrackPeaks(track, 0)
            right = mixer.getTrackPeaks(track, 1)
            return {"track": track, "left": left, "right": right, "supported": True}
        except Exception as e:
            return {"track": track, "left": None, "right": None,
                    "supported": False, "error": str(e)}
    return {"track": track, "left": None, "right": None, "supported": False,
            "error": "mixer.getTrackPeaks not available in this FL build"}


def h_mixer_full_track_info(p):
    """Extended track info: volume, pan, mute, solo, FX slots with enabled
    state, and current peak levels — all in one round-trip."""
    track = int(p["track"])
    name = mixer.getTrackName(track)
    volume = mixer.getTrackVolume(track)
    pan = mixer.getTrackPan(track)
    muted = bool(mixer.isTrackMuted(track))
    solo = bool(mixer.isTrackSolo(track)) if hasattr(mixer, "isTrackSolo") else False

    slots = []
    for s in range(10):
        try:
            valid = bool(plugins.isValid(track, s, False) == 1)
            name_s = plugins.getPluginName(track, s, 0, False) if valid else None
            enabled = None
            if valid and hasattr(plugins, "isEnabled"):
                try:
                    enabled = bool(plugins.isEnabled(track, s, False))
                except Exception:
                    enabled = True
            slots.append({"slot": s, "valid": valid, "name": name_s, "enabled": enabled})
        except Exception:
            slots.append({"slot": s, "valid": False, "name": None, "enabled": None})

    peaks = {}
    if hasattr(mixer, "getTrackPeaks"):
        try:
            peaks = {"left": mixer.getTrackPeaks(track, 0),
                     "right": mixer.getTrackPeaks(track, 1)}
        except Exception:
            pass

    return {"track": track, "name": name, "volume": volume, "pan": pan,
            "muted": muted, "solo": solo, "fx_slots": slots, "peaks": peaks}


# ---- export ----------------------------------------------------------------

def h_export_capabilities(_):
    """Probe runtime API for render/export and disk-recording entry points.

    project render is not scriptable in FL's public API; per-mixer-track disk
    recording (armTrack + getTrackRecordingFileName) is the primary strategy."""
    report = {}
    for mod, fn in ((transport, "render"), (general, "renderProject"),
                    (mixer, "saveAudio"), (ui, "exportAudio"),
                    (mixer, "armTrack"), (mixer, "isTrackArmed"),
                    (mixer, "getTrackRecordingFileName"),
                    (mixer, "getTrackPeaks"),
                    (channels, "getChannelSamplePath")):
        report["%s.%s" % (mod.__name__, fn)] = hasattr(mod, fn)
    return {"strategies": report}


# ---- playlist --------------------------------------------------------------

def _pl_info(i):
    return {
        "index": i,
        "name": _safe(playlist.getTrackName, i) or "",
        "color": _int_to_color_hex(_safe(playlist.getTrackColor, i) or 0),
        "is_muted": _safe(playlist.isTrackMuted, i) == 1,
        "is_solo": _safe(playlist.isTrackSolo, i) == 1,
        "height": _safe(playlist.getTrackHeight, i),
    }


def h_playlist_count(_):
    return {"count": playlist.trackCount()}


def h_playlist_track_info(p):
    return _pl_info(int(p["track"]))


def h_playlist_all_tracks(p):
    include_empty = bool(p.get("include_empty", False))
    out = []
    for i in range(playlist.trackCount()):
        info = _pl_info(i)
        if not include_empty and not info["name"]:
            continue
        out.append(info)
    return {"tracks": out}


def h_playlist_set_track_name(p):
    tr = int(p["track"]); name = p.get("name", "")
    playlist.setTrackName(tr, name)
    return _pl_info(tr)


def h_playlist_set_track_color(p):
    tr = int(p["track"])
    playlist.setTrackColor(tr, _color_to_int(p["color"]))
    return _pl_info(tr)


def h_playlist_mute_track(p):
    tr = int(p["track"])
    playlist.muteTrack(tr)
    return _pl_info(tr)


def h_playlist_solo_track(p):
    tr = int(p["track"])
    playlist.soloTrack(tr)
    return _pl_info(tr)


def h_playlist_list_clips(p):
    track = p.get("track")
    clips = []
    # FL API: no direct clip enumeration for playlist exists; best effort via liveRange
    try:
        for t in (range(playlist.trackCount()) if track is None else [int(track)]):
            # we cannot enumerate clips on a playlist track via the public Python API
            # so expose the track info only and mark this limitation
            pass
    except Exception:
        pass
    return {"clips": clips, "note": "Playlist clip enumeration is not exposed by the FL Python API. Use resource fl://project for pattern usage."}


def h_playlist_place_pattern(p):
    # There is no direct "place a pattern on a playlist track" API in FL.
    # Workaround: use the channel rack's paint on playlist via keystroke,
    # or expose via launchMapPages — not reliable. We document the limitation.
    return {"ok": False, "error": "playlist.placePattern is not yet supported by FL's Python API; use ui.showWindow('playlist') + manual placement or arrangement jumps."}


def h_playlist_delete_clip(p):
    return {"ok": False, "error": "playlist.deleteClip is not exposed by FL's Python API."}


def h_playlist_refresh(_):
    playlist.refresh()
    return {"ok": True}


def h_playlist_list_markers(_):
    """FL's public API cannot enumerate existing markers — only jumpToMarker steps through them."""
    return {"markers": [],
            "ok": False,
            "note": "arrangement.* does not expose marker enumeration; use playlist_jump_marker instead."}


def h_playlist_add_marker(p):
    """Add an auto-time marker at `position_bars`."""
    pos_bars = float(p.get("position_bars", 0))
    name = p.get("name", "")
    try:
        ppq = general.getRecPPQ()
        ticks = int(round(pos_bars * ppq * 4))
        if hasattr(arrangement, "addAutoTimeMarker"):
            arrangement.addAutoTimeMarker(ticks, name)
            return {"ok": True, "position_bars": pos_bars, "name": name}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": False, "error": "arrangement.addAutoTimeMarker not available"}


def h_playlist_delete_marker(p):
    return {"ok": False, "error": "arrangement.* does not expose deleteMarker."}


# ---- arrangement -----------------------------------------------------------

def h_arr_current(_):
    """FL's public API doesn't enumerate arrangements; return what we can."""
    return {"index": 0, "name": "current",
            "note": "FL's Python API doesn't expose arrangement switching."}


def h_arr_list(_):
    return {"arrangements": [{"index": 0, "name": "current"}],
            "note": "FL's Python API doesn't expose arrangement enumeration."}


def h_arr_select(p):
    return {"ok": False, "error": "arrangement switching is not exposed by FL's Python API."}


def h_arr_jump_marker(p):
    direction = int(p.get("direction", 1))
    if hasattr(arrangement, "jumpToMarker"):
        arrangement.jumpToMarker(direction, False)
        return {"direction": direction}
    return {"ok": False, "error": "arrangement.jumpToMarker not available"}


def h_arr_play_time(_):
    try:
        return {
            "position_ticks": transport.getSongPos(2),
            "position_bars": transport.getSongPos(3),
            "position_seconds": transport.getSongPos(1),
        }
    except Exception:
        return {}


# ---- automation -----------------------------------------------------------

def _sleep_bars(bars):
    # bars to seconds using current tempo
    bpm = mixer.getCurrentTempo() / 1000.0
    seconds_per_beat = 60.0 / max(1e-6, bpm)
    time.sleep(bars * 4 * seconds_per_beat)


def _rec_tempo(bpm):
    general.processRECEvent(
        midi.REC_Tempo,
        int(round(bpm * 1000)),
        midi.REC_Control | midi.REC_UpdateControl,
    )


def h_automation_record_tempo(p):
    pts = p.get("points", [])
    if not pts:
        return {"ok": False, "error": "no points"}
    transport.record()  # arm
    transport.start()
    last_t = 0.0
    for pt in pts:
        t = float(pt["time_bars"])
        _sleep_bars(max(0.0, t - last_t))
        _rec_tempo(float(pt["bpm"]))
        last_t = t
    transport.stop()
    transport.record()  # disarm
    return {"ok": True, "points": len(pts)}


def h_automation_record_channel_volume(p):
    ch = int(p["channel"]); pts = p.get("points", [])
    transport.record(); transport.start()
    last_t = 0.0
    for pt in pts:
        t = float(pt["time_bars"])
        _sleep_bars(max(0.0, t - last_t))
        channels.setChannelVolume(ch, float(pt["value"]), True)
        last_t = t
    transport.stop(); transport.record()
    return {"ok": True, "points": len(pts)}


def h_automation_record_channel_pan(p):
    ch = int(p["channel"]); pts = p.get("points", [])
    transport.record(); transport.start()
    last_t = 0.0
    for pt in pts:
        t = float(pt["time_bars"])
        _sleep_bars(max(0.0, t - last_t))
        channels.setChannelPan(ch, float(pt["value"]), True)
        last_t = t
    transport.stop(); transport.record()
    return {"ok": True, "points": len(pts)}


def h_automation_record_mixer_volume(p):
    tr = int(p["track"]); pts = p.get("points", [])
    transport.record(); transport.start()
    last_t = 0.0
    for pt in pts:
        t = float(pt["time_bars"])
        _sleep_bars(max(0.0, t - last_t))
        mixer.setTrackVolume(tr, float(pt["value"]))
        last_t = t
    transport.stop(); transport.record()
    return {"ok": True, "points": len(pts)}


def h_automation_record_plugin_param(p):
    idx = int(p["channel"]); slot = int(p.get("slot", -1))
    ug = (p.get("location", "channel") == "channel")
    param = int(p["param"]); pts = p.get("points", [])
    transport.record(); transport.start()
    last_t = 0.0
    for pt in pts:
        t = float(pt["time_bars"])
        _sleep_bars(max(0.0, t - last_t))
        plugins.setParamValue(float(pt["value"]), param, idx, slot, ug)
        last_t = t
    transport.stop(); transport.record()
    return {"ok": True, "points": len(pts)}


# ---- project ---------------------------------------------------------------

def h_project_metadata(_):
    return {
        "version": _safe(general.getVersion),
        "tempo": mixer.getCurrentTempo() / 1000.0,
        "ppq": _safe(general.getRecPPQ),
        "ppb": _safe(general.getRecPPB) if hasattr(general, "getRecPPB") else None,
        "channel_count": channels.channelCount(True),
        "mixer_tracks": mixer.trackCount(),
        "pattern_count": patterns.patternCount(),
        "selected_pattern": patterns.patternNumber(),
        "selected_channel": channels.selectedChannel(canBeNone=True, indexGlobal=True),
        "is_playing": transport.isPlaying() == 1,
        "is_recording": transport.isRecording() == 1,
        "loop_mode": "song" if transport.getLoopMode() == 1 else "pattern",
        "metronome": _safe(general.getUseMetronome) if hasattr(general, "getUseMetronome") else None,
        "has_unsaved_changes": bool(_safe(general.getChangedFlag)) if hasattr(general, "getChangedFlag") else None,
    }


def h_project_new(p):
    return {"ok": False, "error": "project.new requires UI interaction (File > New); not exposed by the Python API."}


def h_project_open(p):
    return {"ok": False, "error": "opening files requires UI interaction; not supported via API."}


def h_project_save(_):
    fpt = _fpt("FPT_Save")
    if fpt is None:
        return {"ok": False, "error": "midi.FPT_Save not available — user must press Ctrl+S."}
    transport.globalTransport(fpt, 1)
    return {"ok": True}


def h_project_save_as(p):
    fpt = _fpt("FPT_SaveNew")
    if fpt is None:
        return {"ok": False, "error": "midi.FPT_SaveNew not available."}
    transport.globalTransport(fpt, 1)
    return {"ok": True, "note": "FL will prompt for a filename"}


def h_project_undo(_):
    general.undoUp()
    return {"ok": True}


def h_project_redo(_):
    general.undoDown()
    return {"ok": True}


def h_project_undo_history(_):
    """FL's API exposes count + current position + a hint for the topmost entry,
    but NOT per-index names. Return what we can."""
    try:
        count = general.getUndoHistoryCount()
        pos = general.getUndoHistoryPos() if hasattr(general, "getUndoHistoryPos") else None
        last = general.getUndoHistoryLast() if hasattr(general, "getUndoHistoryLast") else None
        hint = general.getUndoLevelHint() if hasattr(general, "getUndoLevelHint") else None
        return {"count": count, "position": pos, "last": last, "hint": hint}
    except Exception as e:
        return {"count": 0, "error": str(e)}


def h_project_save_undo(p):
    general.saveUndo(p.get("name", "fLMCP edit"), int(p.get("flags", 0)))
    return {"ok": True}


def h_project_render(p):
    return {"ok": False, "error": "Rendering requires FL's render dialog; call ui.showWindow('playlist') then user triggers Ctrl+R."}


def h_project_version(_):
    """FL's getVersion() returns an int; convert to x.y.z string for convenience."""
    v = _safe(general.getVersion)
    if isinstance(v, int):
        return {"version_int": v,
                "version": "%d.%d.%d" % ((v >> 24) & 0xFF, (v >> 16) & 0xFF, v & 0xFFFF)}
    return {"version": v or "unknown"}


# ---- ui --------------------------------------------------------------------

_WIN_IDS = {
    "mixer": midi.widMixer if hasattr(midi, "widMixer") else 0,
    "channel_rack": midi.widChannelRack if hasattr(midi, "widChannelRack") else 1,
    "playlist": midi.widPlaylist if hasattr(midi, "widPlaylist") else 2,
    "piano_roll": midi.widPianoRoll if hasattr(midi, "widPianoRoll") else 3,
    "browser": midi.widBrowser if hasattr(midi, "widBrowser") else 4,
    "plugin": midi.widPlugin if hasattr(midi, "widPlugin") else 6,
}


def h_ui_focused(_):
    try:
        return {
            "window_id": ui.getFocused(-1),
            "visible": bool(ui.isInPopupMenu() == 0),
        }
    except Exception:
        return {}


def h_ui_show_window(p):
    wid = _WIN_IDS.get(p.get("name", "channel_rack"), 1)
    ui.showWindow(wid)
    if p.get("focus", True):
        try:
            ui.setFocused(wid)
        except Exception:
            pass
    return {"shown": p.get("name")}


def h_ui_hide_window(p):
    wid = _WIN_IDS.get(p.get("name", "channel_rack"), 1)
    try:
        ui.hideWindow(wid)
    except Exception:
        pass
    return {"hidden": p.get("name")}


def h_ui_hint(p):
    ui.setHintMsg(p.get("message", ""))
    return {"ok": True}


def h_ui_open_piano_roll(p):
    ch = int(p["channel"])
    if p.get("pattern") is not None:
        patterns.jumpToPattern(int(p["pattern"]))
    channels.selectOneChannel(ch, True)
    ui.showWindow(_WIN_IDS["piano_roll"])
    try:
        ui.setFocused(_WIN_IDS["piano_roll"])
    except Exception:
        pass
    return {"ok": True, "channel": ch}


def h_ui_selected_channel(_):
    idx = channels.selectedChannel(canBeNone=True, indexGlobal=True)
    if idx is None or idx < 0:
        return {"channel": None}
    return {"channel": _ch_info(idx)}


def h_ui_scroll_to_channel(p):
    # Best effort — there's no direct 'scrollTo' API for channel rack.
    channels.selectOneChannel(int(p["channel"]), True)
    return {"ok": True}


def h_ui_show_notification(p):
    """Display a notification bubble in FL Studio's UI."""
    msg = str(p.get("message", ""))
    try:
        ui.showNotification(msg)
        return {"ok": True, "message": msg}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ---- piano roll (staging only — real edit happens in pyscript via keystroke) ----

def _stage_piano_roll_request(request):
    PR_REQUEST.parent.mkdir(parents=True, exist_ok=True)
    existing = []
    if PR_REQUEST.exists():
        try:
            data = json.loads(PR_REQUEST.read_text(encoding="utf-8"))
            if isinstance(data, list):
                existing = data
        except Exception:
            existing = []
    existing.append(request)
    PR_REQUEST.write_text(json.dumps(existing, indent=2), encoding="utf-8")


def _prepare_piano_roll(channel, pattern):
    """Make sure the right channel's piano roll is open before keystroke is sent."""
    if pattern is not None:
        patterns.jumpToPattern(int(pattern))
    channels.selectOneChannel(int(channel), True)
    ui.showWindow(_WIN_IDS["piano_roll"])
    try:
        ui.setFocused(_WIN_IDS["piano_roll"])
    except Exception:
        pass


def _read_piano_roll_state():
    if not PR_STATE.exists():
        return None
    try:
        return json.loads(PR_STATE.read_text(encoding="utf-8"))
    except Exception:
        return None


def h_pianoroll_add_notes(p):
    _prepare_piano_roll(p["channel"], p.get("pattern"))
    if p.get("clear_first"):
        _stage_piano_roll_request({"action": "clear"})
    _stage_piano_roll_request({"action": "add_notes", "notes": p.get("notes", [])})
    return {"staged": True, "needs_keystroke": True, "request_file": str(PR_REQUEST)}


def h_pianoroll_add_chord(p):
    _prepare_piano_roll(p["channel"], p.get("pattern"))
    _stage_piano_roll_request({
        "action": "add_chord",
        "time": float(p.get("time_bars", 0.0)) * 4,
        "duration": float(p.get("duration_bars", 1.0)) * 4,
        "notes": [{"midi": n, "velocity": float(p.get("velocity", 0.8))} for n in p["midi_notes"]],
    })
    return {"staged": True, "needs_keystroke": True, "request_file": str(PR_REQUEST)}


def h_pianoroll_add_arpeggio(p):
    """Expand arpeggio to linear notes before staging."""
    notes_midi = list(p["midi_notes"])
    direction = p.get("direction", "up")
    if direction == "down":
        notes_midi.reverse()
    elif direction == "updown":
        notes_midi = notes_midi + notes_midi[-2:0:-1]
    elif direction == "random":
        import random
        random.shuffle(notes_midi)

    step_bars = float(p.get("step_bars", 0.25))
    dur_bars = float(p.get("note_duration_bars", 0.25))
    start_bars = float(p.get("time_bars", 0.0))
    repeats = int(p.get("repeats", 1))

    total_notes = len(notes_midi) * repeats
    out = []
    for i in range(total_notes):
        out.append({
            "midi": notes_midi[i % len(notes_midi)],
            "time": (start_bars + i * step_bars) * 4,  # quarter-notes for pyscript
            "duration": dur_bars * 4,
            "velocity": float(p.get("velocity", 0.8)),
        })
    _prepare_piano_roll(p["channel"], p.get("pattern"))
    _stage_piano_roll_request({"action": "add_notes", "notes": out})
    return {"staged": True, "needs_keystroke": True, "notes": len(out)}


def h_pianoroll_delete_notes(p):
    _prepare_piano_roll(p["channel"], p.get("pattern"))
    # pyscript expects time in quarter notes
    norm = [{"midi": n["midi"], "time": float(n["time_bars"]) * 4} for n in p.get("notes", [])]
    _stage_piano_roll_request({"action": "delete_notes", "notes": norm})
    return {"staged": True, "needs_keystroke": True}


def h_pianoroll_clear(p):
    _prepare_piano_roll(p["channel"], p.get("pattern"))
    _stage_piano_roll_request({"action": "clear"})
    return {"staged": True, "needs_keystroke": True}


def h_pianoroll_read(p):
    """The pyscript writes the current state file on every run. We return the last known state."""
    _prepare_piano_roll(p["channel"], p.get("pattern"))
    # Staging a no-op action so the pyscript refreshes the state file
    _stage_piano_roll_request({"action": "export_only"})
    state = _read_piano_roll_state()
    return {"staged": True, "needs_keystroke": True, "last_state": state}


def h_pianoroll_quantize(p):
    _prepare_piano_roll(p["channel"], p.get("pattern"))
    _stage_piano_roll_request({
        "action": "quantize",
        "grid": float(p.get("grid_bars", 0.25)) * 4,
        "strength": float(p.get("strength", 1.0)),
    })
    return {"staged": True, "needs_keystroke": True}


def h_pianoroll_transpose(p):
    _prepare_piano_roll(p["channel"], p.get("pattern"))
    _stage_piano_roll_request({"action": "transpose", "semitones": int(p.get("semitones", 0))})
    return {"staged": True, "needs_keystroke": True}


def h_pianoroll_humanize(p):
    _prepare_piano_roll(p["channel"], p.get("pattern"))
    _stage_piano_roll_request({
        "action": "humanize",
        "timing_jitter": float(p.get("timing_jitter_bars", 0.02)) * 4,
        "velocity_jitter": float(p.get("velocity_jitter", 0.1)),
    })
    return {"staged": True, "needs_keystroke": True}


def h_pianoroll_duplicate(p):
    _prepare_piano_roll(p["channel"], p.get("pattern"))
    _stage_piano_roll_request({
        "action": "duplicate",
        "source_time": float(p["source_time_bars"]) * 4,
        "length": float(p["length_bars"]) * 4,
        "dest_time": float(p["dest_time_bars"]) * 4,
    })
    return {"staged": True, "needs_keystroke": True}


# ----------------------------------------------------------------------------
# Handler table
# ----------------------------------------------------------------------------

_HANDLERS = {
    # meta
    "meta.ping": h_meta_ping,
    "meta.info": h_meta_info,
    # transport
    "transport.start": h_transport_start,
    "transport.stop": h_transport_stop,
    "transport.record": h_transport_record,
    "transport.status": h_transport_status,
    "transport.setPosition": h_transport_set_position,
    "transport.length": h_transport_length,
    "transport.setLoopMode": h_transport_set_loop_mode,
    "transport.setPlaybackSpeed": h_transport_set_playback_speed,
    "transport.setTempo": h_transport_set_tempo,
    "transport.tapTempo": h_transport_tap_tempo,
    "transport.setTimeSignature": h_transport_set_time_signature,
    "transport.toggleMetronome": h_transport_toggle_metronome,
    "transport.toggleCountdownBeforeRec": h_transport_toggle_countdown,
    "transport.jog": h_transport_jog,
    # patterns
    "patterns.count": h_patterns_count,
    "patterns.current": h_patterns_current,
    "patterns.list": h_patterns_list,
    "patterns.select": h_patterns_select,
    "patterns.create": h_patterns_create,
    "patterns.rename": h_patterns_rename,
    "patterns.setColor": h_patterns_set_color,
    "patterns.delete": h_patterns_delete,
    "patterns.clone": h_patterns_clone,
    "patterns.setLength": h_patterns_set_length,
    "patterns.findByName": h_patterns_find_by_name,
    "patterns.jumpNext": h_patterns_jump_next,
    "patterns.jumpPrev": h_patterns_jump_prev,
    # channels
    "channels.count": h_channels_count,
    "channels.info": h_channels_info,
    "channels.all": h_channels_all,
    "channels.selected": h_channels_selected,
    "channels.select": h_channels_select,
    "channels.setVolume": h_channels_set_volume,
    "channels.setPan": h_channels_set_pan,
    "channels.setPitch": h_channels_set_pitch,
    "channels.mute": h_channels_mute,
    "channels.solo": h_channels_solo,
    "channels.setName": h_channels_set_name,
    "channels.setColor": h_channels_set_color,
    "channels.routeToMixer": h_channels_route_to_mixer,
    "channels.triggerNote": h_channels_trigger_note,
    "channels.getGridBit": h_channels_get_grid_bit,
    "channels.setGridBit": h_channels_set_grid_bit,
    "channels.getStepSequence": h_channels_get_step_sequence,
    "channels.setStepSequence": h_channels_set_step_sequence,
    "channels.clearStepSequence": h_channels_clear_step_sequence,
    "channels.quickQuantize": h_channels_quick_quantize,
    "channels.sampleInfo": h_channels_sample_info,
    # mixer
    "mixer.count": h_mixer_count,
    "mixer.trackInfo": h_mixer_track_info,
    "mixer.allTracks": h_mixer_all_tracks,
    "mixer.setVolume": h_mixer_set_volume,
    "mixer.setPan": h_mixer_set_pan,
    "mixer.mute": h_mixer_mute,
    "mixer.solo": h_mixer_solo,
    "mixer.arm": h_mixer_arm,
    "mixer.recordArm": h_mixer_record_arm,
    "mixer.setName": h_mixer_set_name,
    "mixer.setColor": h_mixer_set_color,
    "mixer.setStereoSep": h_mixer_set_stereo_sep,
    "mixer.setSendLevel": h_mixer_set_send_level,
    "mixer.route": h_mixer_route,
    "mixer.fxSlots": h_mixer_fx_slots,
    "mixer.select": h_mixer_select,
    "mixer.getEQ": h_mixer_get_eq,
    "mixer.setEQBand": h_mixer_set_eq_band,
    "mixer.linkChannelToTrack": h_mixer_link_channel,
    "mixer.pluginMixLevel": h_mixer_plugin_mix_level,
    "mixer.trackSlotsEnabled": h_mixer_track_slots_enabled,
    "mixer.stereoAdvanced": h_mixer_stereo_advanced,
    # plugins
    "plugins.isValid": h_plugins_is_valid,
    "plugins.name": h_plugins_name,
    "plugins.paramCount": h_plugins_param_count,
    "plugins.params": h_plugins_params,
    "plugins.getParam": h_plugins_get_param,
    "plugins.setParam": h_plugins_set_param,
    "plugins.setParams": h_plugins_set_params,
    "plugins.findParam": h_plugins_find_param,
    "plugins.presetCount": h_plugins_preset_count,
    "plugins.nextPreset": h_plugins_next_preset,
    "plugins.prevPreset": h_plugins_prev_preset,
    "plugins.setPreset": h_plugins_set_preset,
    "plugins.setParamREC": h_plugins_set_param_rec,
    "plugins.showEditor": h_plugins_show_editor,
    "plugins.listMixerTrack": h_plugins_list_mixer_track,
    "plugins.loadAttempt": h_plugins_load_attempt,
    "meta.sandboxProbe": h_meta_sandbox_probe,
    "meta.probeWindows": h_meta_sandbox_probe,  # legacy alias (no-restart diag)
    "plugins.probeApi": h_plugins_probe_api,
    "browser.probeNav": h_browser_probe_nav,
    "plugins.probeBrowserNav": h_plugins_probe_browser_nav,
    "plugins.loadViaUI": h_plugins_load_via_ui,
    "mixer.loadFST": h_mixer_load_fst,
    "plugins.setSlotEnabled": h_plugins_set_slot_enabled,
    "plugins.removeFromSlot": h_plugins_remove_from_slot,
    "plugins.getSlotInfo": h_plugins_get_slot_info,
    # sidechain / routing
    "mixer.sidechain": h_mixer_sidechain,
    "mixer.getRouteInfo": h_mixer_get_route_info,
    "mixer.getPeaks": h_mixer_get_peaks,
    "mixer.fullTrackInfo": h_mixer_full_track_info,
    # export
    "export.capabilities": h_export_capabilities,
    # playlist
    "playlist.trackCount": h_playlist_count,
    "playlist.trackInfo": h_playlist_track_info,
    "playlist.allTracks": h_playlist_all_tracks,
    "playlist.setTrackName": h_playlist_set_track_name,
    "playlist.setTrackColor": h_playlist_set_track_color,
    "playlist.muteTrack": h_playlist_mute_track,
    "playlist.soloTrack": h_playlist_solo_track,
    "playlist.listClips": h_playlist_list_clips,
    "playlist.placePattern": h_playlist_place_pattern,
    "playlist.deleteClip": h_playlist_delete_clip,
    "playlist.refresh": h_playlist_refresh,
    "playlist.listMarkers": h_playlist_list_markers,
    "playlist.addMarker": h_playlist_add_marker,
    "playlist.deleteMarker": h_playlist_delete_marker,
    # arrangement
    "arrangement.current": h_arr_current,
    "arrangement.list": h_arr_list,
    "arrangement.select": h_arr_select,
    "arrangement.jumpMarker": h_arr_jump_marker,
    "arrangement.playTime": h_arr_play_time,
    # automation
    "automation.recordTempo": h_automation_record_tempo,
    "automation.recordChannelVolume": h_automation_record_channel_volume,
    "automation.recordChannelPan": h_automation_record_channel_pan,
    "automation.recordMixerVolume": h_automation_record_mixer_volume,
    "automation.recordPluginParam": h_automation_record_plugin_param,
    # project
    "project.metadata": h_project_metadata,
    "project.new": h_project_new,
    "project.open": h_project_open,
    "project.save": h_project_save,
    "project.saveAs": h_project_save_as,
    "project.undo": h_project_undo,
    "project.redo": h_project_redo,
    "project.undoHistory": h_project_undo_history,
    "project.saveUndo": h_project_save_undo,
    "project.render": h_project_render,
    "project.version": h_project_version,
    # ui
    "ui.focusedWindow": h_ui_focused,
    "ui.showWindow": h_ui_show_window,
    "ui.hideWindow": h_ui_hide_window,
    "ui.hint": h_ui_hint,
    "ui.openPianoRoll": h_ui_open_piano_roll,
    "ui.selectedChannel": h_ui_selected_channel,
    "ui.scrollToChannel": h_ui_scroll_to_channel,
    "ui.showNotification": h_ui_show_notification,
    # piano roll (stage)
    "pianoroll.addNotes": h_pianoroll_add_notes,
    "pianoroll.addChord": h_pianoroll_add_chord,
    "pianoroll.addArpeggio": h_pianoroll_add_arpeggio,
    "pianoroll.deleteNotes": h_pianoroll_delete_notes,
    "pianoroll.clear": h_pianoroll_clear,
    "pianoroll.read": h_pianoroll_read,
    "pianoroll.quantize": h_pianoroll_quantize,
    "pianoroll.transpose": h_pianoroll_transpose,
    "pianoroll.humanize": h_pianoroll_humanize,
    "pianoroll.duplicate": h_pianoroll_duplicate,
}


# ----------------------------------------------------------------------------
# FL Studio callbacks
# ----------------------------------------------------------------------------

def OnInit():
    global _shutting_down
    _log("initializing — script dir: %s" % SCRIPT_DIR)
    _log("FL version: %s" % _safe(general.getVersion))
    _probe_sandbox()
    _shutting_down = False
    if _start_listening():
        _log("bridge ready on tcp://%s:%d" % (BRIDGE_HOST, BRIDGE_PORT))
    else:
        _log("TCP unavailable (FL 2025 sandbox) — MIDI SysEx transport active. "
             "Route a loopMIDI port to this controller's input AND set the "
             "same port number on a loopMIDI output device.")


def OnDeInit():
    global _accept_socket, _shutting_down
    _log("deinit")
    _shutting_down = True
    if _accept_socket is not None:
        try:
            _accept_socket.close()
        except Exception:
            pass
        _accept_socket = None
    for c in list(_known_clients):
        try:
            c.close()
        except Exception:
            pass
    _known_clients.clear()
    _clients.clear()


def OnIdle():
    """Pump sockets then drain up to N requests, all on the FL main thread."""
    global _idle_tick, _last_refresh_push
    _idle_tick += 1
    if (_accept_socket is None and not _shutting_down
            and _bind_attempts < 3 and _idle_tick % 100 == 0):
        _start_listening()  # retry bind if the port was busy at OnInit
    _pump_network()
    drained = 0
    while drained < 32:
        try:
            client, req = _inbox.get_nowait()
        except queue.Empty:
            break
        drained += 1
        req_id = req.get("id", 0)
        action = req.get("action", "")
        params = req.get("params", {}) or {}
        try:
            result = _execute(action, params)
            resp = {"id": req_id, "ok": True, "result": result}
        except Exception as e:
            tb = traceback.format_exc(limit=3)
            resp = {"id": req_id, "ok": False, "error": "%s: %s" % (type(e).__name__, e), "traceback": tb}
            _log("action %s error: %s" % (action, e))
        if client is None:  # request arrived over MIDI SysEx
            _midi_send_message(resp)
        else:
            _send_frame(client, _pack_frame(resp))

    # push transport notifications every ~0.5s when playing
    now = time.monotonic()
    if (_known_clients or _midi_active) and (now - _last_refresh_push) > 0.5:
        _last_refresh_push = now
        try:
            snap = h_transport_status({})
            event = {"event": "transport.tick", "data": snap}
            if _known_clients:
                frame = _pack_frame(event)
                for c in list(_known_clients):
                    _send_frame(c, frame)
            if _midi_active:
                _midi_send_message(event)
        except Exception:
            pass


def OnSysEx(event):
    """SysEx from the MCP server (via loopMIDI)."""
    try:
        if _on_sysex_bytes(bytes(event.sysex)):
            event.handled = True
            return
    except Exception as e:
        _log("OnSysEx error: %s" % e)
    event.handled = False


def OnMidiIn(event):
    # Some FL builds route SysEx through OnMidiIn instead of OnSysEx.
    try:
        sysex = getattr(event, "sysex", None)
        if sysex and _on_sysex_bytes(bytes(sysex)):
            event.handled = True
            return
    except Exception as e:
        _log("OnMidiIn sysex error: %s" % e)
    event.handled = False


def OnMidiMsg(event):
    event.handled = False


def OnRefresh(flags):
    # push a refresh event to connected clients (so MCP server can invalidate cache)
    try:
        event = {"event": "refresh", "data": {"flags": int(flags)}}
        frame = _pack_frame(event)
        for c in list(_known_clients):
            _send_frame(c, frame)
        if _midi_active:
            _midi_send_message(event)
    except Exception:
        pass


def OnProjectLoad(status):
    try:
        event = {"event": "projectLoad", "data": {"status": status}}
        frame = _pack_frame(event)
        for c in list(_known_clients):
            _send_frame(c, frame)
        if _midi_active:
            _midi_send_message(event)
    except Exception:
        pass
