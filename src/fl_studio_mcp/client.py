"""TCP client to the FL Studio bridge. Thread-safe, lazy connect, one retry."""

from __future__ import annotations

import itertools
import socket
import threading
from typing import Any

from . import protocol


class BridgeUnavailable(ConnectionError):
    """FL Studio is not running or the bridge script is not loaded."""


class BridgeClient:
    def __init__(self, host: str = protocol.HOST, port: int = protocol.PORT,
                 timeout: float = 10.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock: socket.socket | None = None
        self._lock = threading.Lock()
        self._ids = itertools.count(1)

    def _connect(self) -> socket.socket:
        try:
            sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as exc:
            raise BridgeUnavailable(
                f"Cannot reach FL Studio bridge on {self.host}:{self.port}. "
                "Is FL Studio running with the fLMCP Bridge script loaded?"
            ) from exc
        sock.settimeout(self.timeout)
        return sock

    def call(self, action: str, params: dict | None = None) -> Any:
        with self._lock:
            request = {"id": next(self._ids), "action": action, "params": params or {}}
            for attempt in (1, 2):
                if self._sock is None:
                    self._sock = self._connect()
                try:
                    self._sock.sendall(protocol.pack(request))
                    response = self._read_response(request["id"])
                    break
                except (ConnectionError, OSError):
                    self._drop()
                    if attempt == 2:
                        raise BridgeUnavailable("connection lost and reconnect failed")
            if not response.get("ok"):
                raise RuntimeError(f"{action}: {response.get('error')}")
            return response.get("result")

    def _read_response(self, request_id: int) -> dict:
        while True:
            frame = protocol.read_frame(self._sock)
            if "event" in frame:  # notification push — ignorée en v0
                continue
            if frame.get("id") == request_id:
                return frame

    def _drop(self):
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def close(self):
        with self._lock:
            self._drop()
