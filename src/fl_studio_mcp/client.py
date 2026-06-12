"""TCP client to the FL Studio bridge. Thread-safe, lazy connect, one retry."""

from __future__ import annotations

import itertools
import socket
import threading
from typing import Any

from . import protocol

_MAX_NOTIFICATIONS = 64


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
            # M4: create_connection already sets the timeout; no need for a
            # second sock.settimeout() call afterwards.
            sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as exc:
            raise BridgeUnavailable(
                f"Cannot reach FL Studio bridge on {self.host}:{self.port}. "
                "Is FL Studio running with the fLMCP Bridge script loaded?"
            ) from exc
        return sock

    def call(self, action: str, params: dict | None = None) -> Any:
        with self._lock:
            request = {"id": next(self._ids), "action": action, "params": params or {}}
            # C1 / I1: only retry on hard connection errors; a timeout means the
            # bridge is alive-but-slow — raise immediately without retrying to
            # avoid duplicate execution of non-idempotent commands.
            for attempt in (1, 2):
                if self._sock is None:
                    self._sock = self._connect()
                try:
                    self._sock.sendall(protocol.pack(request))
                    response = self._read_response(request["id"])
                    # C1: return inside the loop — `response` is always bound here.
                    if not response.get("ok"):
                        raise RuntimeError(f"{action}: {response.get('error')}")
                    return response.get("result")
                except socket.timeout as exc:
                    # I1: slow/silent bridge — drop the socket, do NOT retry.
                    self._drop()
                    raise BridgeUnavailable(
                        f"bridge did not respond within {self.timeout}s"
                    ) from exc
                except (ConnectionError, OSError):
                    self._drop()
                    if attempt == 2:
                        raise BridgeUnavailable(
                            "connection lost and reconnect failed"
                        )
            # Unreachable — the loop always returns or raises, but satisfies
            # type-checkers that don't recognise the exhaustive loop above.
            raise BridgeUnavailable("unexpected call() exit")  # pragma: no cover

    def _read_response(self, request_id: int) -> dict:
        # I3: bounded notification skip; wrong id is a protocol error.
        skipped = 0
        while True:
            frame = protocol.read_frame(self._sock)
            if "event" in frame:  # notification push — ignored in v0
                skipped += 1
                if skipped > _MAX_NOTIFICATIONS:
                    raise OSError("too many notifications before response")
                continue
            if frame.get("id") == request_id:
                return frame
            # I3: a non-notification frame with the wrong id is a protocol error.
            raise OSError(
                f"protocol error: expected response id {request_id}, "
                f"got {frame.get('id')!r}"
            )

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
