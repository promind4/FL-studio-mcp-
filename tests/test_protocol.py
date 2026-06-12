import socket

import pytest

from fl_studio_mcp import protocol


def test_pack_roundtrip_over_socketpair():
    a, b = socket.socketpair()
    try:
        payload = {"id": 1, "action": "ping", "params": {"x": "é"}}
        a.sendall(protocol.pack(payload))
        result = protocol.read_frame(b)
        assert result == payload
    finally:
        a.close()
        b.close()


def test_pack_rejects_oversized_frame():
    big = {"data": "x" * (protocol.MAX_FRAME + 1)}
    with pytest.raises(ValueError):
        protocol.pack(big)


def test_read_frame_raises_on_closed_socket():
    a, b = socket.socketpair()
    a.close()
    with pytest.raises(ConnectionError):
        protocol.read_frame(b)
    b.close()
