import socket
import threading

import pytest

from fl_studio_mcp import protocol
from fl_studio_mcp.client import BridgeClient, BridgeUnavailable


class FakeBridge:
    """Minimal TCP server that imitates the FL Studio bridge.

    The *handler* callable receives a decoded request dict and should return a
    response dict, or None to signal that the connection should be closed
    immediately (simulates a peer reset).
    """

    def __init__(self, handler):
        self.handler = handler
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.sock.listen(5)
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        # M1: loop over accept() so reconnects after a dropped connection work.
        try:
            while True:
                conn, _ = self.sock.accept()
                try:
                    while True:
                        req = protocol.read_frame(conn)
                        reply = self.handler(req)
                        if reply is None:
                            # handler signals: close this connection now
                            conn.close()
                            break
                        conn.sendall(protocol.pack(reply))
                except (ConnectionError, OSError):
                    pass
                finally:
                    try:
                        conn.close()
                    except OSError:
                        pass
        except (ConnectionError, OSError):
            pass

    def close(self):
        self.sock.close()


# ---------------------------------------------------------------------------
# Existing tests (unchanged behaviour)
# ---------------------------------------------------------------------------

def test_call_returns_result():
    bridge = FakeBridge(lambda req: {"id": req["id"], "ok": True,
                                     "result": {"pong": True}, "error": None})
    client = BridgeClient(port=bridge.port)
    assert client.call("ping") == {"pong": True}
    client.close()
    bridge.close()


def test_call_raises_on_bridge_error():
    bridge = FakeBridge(lambda req: {"id": req["id"], "ok": False,
                                     "result": None, "error": "slot 2 is empty"})
    client = BridgeClient(port=bridge.port)
    with pytest.raises(RuntimeError, match="slot 2 is empty"):
        client.call("plugin_get_param", {"track": 1, "slot": 2})
    client.close()
    bridge.close()


def test_unreachable_bridge_raises_bridge_unavailable():
    client = BridgeClient(port=1)  # port 1: never open
    with pytest.raises(BridgeUnavailable):
        client.call("ping")


# ---------------------------------------------------------------------------
# M2 — new reconnect and timeout tests
# ---------------------------------------------------------------------------

def test_reconnects_after_connection_drop():
    """After the bridge closes the connection on attempt 1, call() reconnects
    and succeeds on attempt 2.  handler returns None → connection is dropped."""
    call_count = {"n": 0}

    def handler(req):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # Signal FakeBridge to close this connection immediately.
            return None
        # Second connection: answer normally.
        return {"id": req["id"], "ok": True, "result": {"pong": True}, "error": None}

    bridge = FakeBridge(handler)
    client = BridgeClient(port=bridge.port)
    result = client.call("ping")
    assert result == {"pong": True}
    client.close()
    bridge.close()


def test_timeout_raises_without_retry():
    """A bridge that never replies must raise BridgeUnavailable (not hang or
    retry), and the request must have been sent exactly once — no duplicate."""
    request_count = {"n": 0}
    stop_event = threading.Event()

    def handler(req):
        request_count["n"] += 1
        # Block until the test is over — never send a reply.
        stop_event.wait(timeout=5)
        return None  # close connection after unblocking

    bridge = FakeBridge(handler)
    client = BridgeClient(port=bridge.port, timeout=0.2)
    try:
        with pytest.raises(BridgeUnavailable, match="did not respond"):
            client.call("ping")
        # The request must have arrived at the bridge exactly once — no retry.
        assert request_count["n"] == 1
    finally:
        stop_event.set()
        client.close()
        bridge.close()
