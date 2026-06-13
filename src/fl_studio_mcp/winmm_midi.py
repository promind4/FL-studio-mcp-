"""Dependency-free MIDI I/O on Windows via the WinMM API (ctypes).

Fallback backend for the SysEx transport when python-rtmidi has no wheel for
the running interpreter (e.g. CPython 3.13). Only what the bridge needs:
device enumeration by name, SysEx send, SysEx receive.

Receive design: midiInOpen with a callback; a pool of pre-registered buffers
captures incoming long messages (MIM_LONGDATA). The callback only copies the
bytes into a queue — exhausted buffers are re-registered from poll(), because
MSDN forbids calling midiInAddBuffer from inside the callback. The pool is
sized well above the transport's chunk size so bursts of response chunks
don't drop frames between two polls.
"""

from __future__ import annotations

import ctypes
import queue
from ctypes import wintypes

winmm = ctypes.windll.winmm

CALLBACK_FUNCTION = 0x00030000
MIM_LONGDATA = 0x3C4
MHDR_DONE = 0x00000001

_BUFFER_COUNT = 32
_BUFFER_SIZE = 2048  # transport frames are ~520 bytes

DWORD_PTR = ctypes.c_size_t


class MIDIHDR(ctypes.Structure):
    pass


MIDIHDR._fields_ = [
    ("lpData", ctypes.POINTER(ctypes.c_char)),
    ("dwBufferLength", wintypes.DWORD),
    ("dwBytesRecorded", wintypes.DWORD),
    ("dwUser", DWORD_PTR),
    ("dwFlags", wintypes.DWORD),
    ("lpNext", ctypes.POINTER(MIDIHDR)),
    ("reserved", DWORD_PTR),
    ("dwOffset", wintypes.DWORD),
    ("dwReserved", DWORD_PTR * 8),
]


class _MIDIINCAPSW(ctypes.Structure):
    _fields_ = [("wMid", wintypes.WORD), ("wPid", wintypes.WORD),
                ("vDriverVersion", wintypes.UINT),
                ("szPname", wintypes.WCHAR * 32),
                ("dwSupport", wintypes.DWORD)]


class _MIDIOUTCAPSW(ctypes.Structure):
    _fields_ = [("wMid", wintypes.WORD), ("wPid", wintypes.WORD),
                ("vDriverVersion", wintypes.UINT),
                ("szPname", wintypes.WCHAR * 32),
                ("wTechnology", wintypes.WORD), ("wVoices", wintypes.WORD),
                ("wNotes", wintypes.WORD), ("wChannelMask", wintypes.WORD),
                ("dwSupport", wintypes.DWORD)]


_MidiInProc = ctypes.WINFUNCTYPE(None, ctypes.c_void_p, ctypes.c_uint,
                                 DWORD_PTR, DWORD_PTR, DWORD_PTR)


def _check(result, what):
    if result != 0:
        raise OSError(f"{what} failed with MMRESULT {result}")


def get_input_names() -> list[str]:
    names = []
    for i in range(winmm.midiInGetNumDevs()):
        caps = _MIDIINCAPSW()
        if winmm.midiInGetDevCapsW(i, ctypes.byref(caps),
                                   ctypes.sizeof(caps)) == 0:
            names.append(caps.szPname)
    return names


def get_output_names() -> list[str]:
    names = []
    for i in range(winmm.midiOutGetNumDevs()):
        caps = _MIDIOUTCAPSW()
        if winmm.midiOutGetDevCapsW(i, ctypes.byref(caps),
                                    ctypes.sizeof(caps)) == 0:
            names.append(caps.szPname)
    return names


class _SysexMessage:
    def __init__(self, data):
        self.type = "sysex"
        self.data = list(data)


class MidiOut:
    """SysEx-capable output. send() takes a message-like object whose .data
    is the SysEx payload WITHOUT the F0/F7 framing (mido convention)."""

    def __init__(self, name: str):
        self._handle = ctypes.c_void_p()
        dev_id = get_output_names().index(name)
        _check(winmm.midiOutOpen(ctypes.byref(self._handle), dev_id,
                                 0, 0, 0), "midiOutOpen")

    def send(self, message):
        raw = bytes([0xF0] + list(message.data) + [0xF7])
        buf = ctypes.create_string_buffer(raw, len(raw))
        hdr = MIDIHDR()
        hdr.lpData = ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))
        hdr.dwBufferLength = len(raw)
        hdr.dwBytesRecorded = len(raw)
        _check(winmm.midiOutPrepareHeader(self._handle, ctypes.byref(hdr),
                                          ctypes.sizeof(hdr)),
               "midiOutPrepareHeader")
        try:
            _check(winmm.midiOutLongMsg(self._handle, ctypes.byref(hdr),
                                        ctypes.sizeof(hdr)), "midiOutLongMsg")
            # MHDR_DONE is set by the driver once the buffer was consumed;
            # loopMIDI does this near-instantly.
            for _ in range(1000):
                if hdr.dwFlags & MHDR_DONE:
                    break
                winmm.midiOutGetNumDevs()  # cheap call as a tiny delay
        finally:
            winmm.midiOutUnprepareHeader(self._handle, ctypes.byref(hdr),
                                         ctypes.sizeof(hdr))

    def close(self):
        if self._handle:
            winmm.midiOutReset(self._handle)
            winmm.midiOutClose(self._handle)
            self._handle = None


class MidiIn:
    """SysEx-capable input. poll() returns a message-like object with .type
    'sysex' and .data (payload without F0/F7), or None."""

    def __init__(self, name: str):
        self._handle = ctypes.c_void_p()
        self._queue: "queue.Queue[bytes]" = queue.Queue()
        self._pending_headers: "queue.Queue[int]" = queue.Queue()
        self._closing = False
        # keep strong refs: buffers, headers and the callback thunk
        self._buffers = []
        self._headers = []
        self._callback = _MidiInProc(self._on_message)
        dev_id = get_input_names().index(name)
        _check(winmm.midiInOpen(ctypes.byref(self._handle), dev_id,
                                self._callback, 0, CALLBACK_FUNCTION),
               "midiInOpen")
        for i in range(_BUFFER_COUNT):
            buf = ctypes.create_string_buffer(_BUFFER_SIZE)
            hdr = MIDIHDR()
            hdr.lpData = ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))
            hdr.dwBufferLength = _BUFFER_SIZE
            hdr.dwUser = i
            self._buffers.append(buf)
            self._headers.append(hdr)
            _check(winmm.midiInPrepareHeader(self._handle,
                                             ctypes.byref(hdr),
                                             ctypes.sizeof(hdr)),
                   "midiInPrepareHeader")
            _check(winmm.midiInAddBuffer(self._handle, ctypes.byref(hdr),
                                         ctypes.sizeof(hdr)),
                   "midiInAddBuffer")
        _check(winmm.midiInStart(self._handle), "midiInStart")

    def _on_message(self, _h, msg, _inst, param1, _param2):
        if msg != MIM_LONGDATA or self._closing:
            return
        hdr = ctypes.cast(param1, ctypes.POINTER(MIDIHDR)).contents
        n = hdr.dwBytesRecorded
        if n:
            self._queue.put(ctypes.string_at(hdr.lpData, n))
        # midiInAddBuffer must not be called from the callback (MSDN);
        # poll() re-registers it.
        self._pending_headers.put(int(hdr.dwUser))

    def poll(self):
        # re-register consumed buffers first so bursts keep flowing
        while True:
            try:
                idx = self._pending_headers.get_nowait()
            except queue.Empty:
                break
            if not self._closing:
                winmm.midiInAddBuffer(self._handle,
                                      ctypes.byref(self._headers[idx]),
                                      ctypes.sizeof(MIDIHDR))
        try:
            raw = self._queue.get_nowait()
        except queue.Empty:
            return None
        data = raw[1:-1] if raw[:1] == b"\xf0" and raw[-1:] == b"\xf7" else raw
        return _SysexMessage(data)

    def close(self):
        if self._handle:
            self._closing = True
            winmm.midiInStop(self._handle)
            winmm.midiInReset(self._handle)  # returns all buffers via callback
            for hdr in self._headers:
                winmm.midiInUnprepareHeader(self._handle, ctypes.byref(hdr),
                                            ctypes.sizeof(hdr))
            winmm.midiInClose(self._handle)
            self._handle = None
