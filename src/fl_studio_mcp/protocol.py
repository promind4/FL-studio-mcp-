"""
Shared wire protocol for fLMCP <-> FL Studio bridge.

Length-prefixed JSON framing over TCP:
    [4 bytes big-endian uint32 length][payload = utf-8 JSON]

Request envelope:
    {"id": int, "action": str, "params": {..}}

Response envelope:
    {"id": int, "ok": bool, "result": <any>, "error": str|None}

Server-push notification (no id):
    {"event": str, "data": <any>}
"""

from __future__ import annotations

import json
import socket
import struct
import threading
import time
from dataclasses import dataclass
from typing import Any

HOST = "127.0.0.1"
PORT = 9876
HEADER = struct.Struct(">I")
MAX_FRAME = 16 * 1024 * 1024  # 16 MiB


def pack(obj: Any) -> bytes:
    body = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(body) > MAX_FRAME:
        raise ValueError(f"frame too large: {len(body)} bytes")
    return HEADER.pack(len(body)) + body


def recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("socket closed while reading frame")
        buf.extend(chunk)
    return bytes(buf)


def read_frame(sock: socket.socket) -> dict:
    head = recv_exact(sock, HEADER.size)
    (length,) = HEADER.unpack(head)
    if length > MAX_FRAME:
        raise ValueError(f"frame length out of bounds: {length}")
    body = recv_exact(sock, length)
    return json.loads(body.decode("utf-8"))


@dataclass
class RPCError(RuntimeError):
    action: str
    message: str

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.action}: {self.message}"
