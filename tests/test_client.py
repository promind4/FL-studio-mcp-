import socket
import threading

import pytest

from fl_studio_mcp import protocol
from fl_studio_mcp.client import BridgeClient, BridgeUnavailable


class FakeBridge:
    """Serveur TCP minimal imitant le bridge FL Studio."""

    def __init__(self, handler):
        self.handler = handler
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.sock.listen(1)
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        try:
            conn, _ = self.sock.accept()
            while True:
                req = protocol.read_frame(conn)
                conn.sendall(protocol.pack(self.handler(req)))
        except (ConnectionError, OSError):
            pass

    def close(self):
        self.sock.close()


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
    client = BridgeClient(port=1)  # port 1: jamais ouvert
    with pytest.raises(BridgeUnavailable):
        client.call("ping")
