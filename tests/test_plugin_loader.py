"""Tests for plugin_loader: capability probe + assisted-insertion fallback.

TDD: tests written before implementation.
"""

from __future__ import annotations

import pytest

from fl_studio_mcp.client import BridgeUnavailable
from fl_studio_mcp.tools.plugin_loader import probe_capabilities, wait_for_plugin


class FakeClient:
    """Records calls and returns pre-configured responses.

    Each value in *responses* may be:
    - a plain dict  → returned as-is every time
    - a callable    → called with the params dict; its return value is used
    - a list        → items consumed in order (one per call); last item raises
                      IndexError if exhausted
    - an Exception instance → raised on every call
    """

    def __init__(self, responses: dict):
        self.responses = responses
        self.calls: list[tuple[str, dict]] = []

    def call(self, action: str, params: dict) -> object:
        self.calls.append((action, params))
        if action not in self.responses:
            raise KeyError(f"FakeClient: no response configured for action {action!r}")
        handler = self.responses[action]
        if isinstance(handler, Exception):
            raise handler
        if callable(handler):
            return handler(params)
        if isinstance(handler, list):
            if not handler:
                raise IndexError(
                    f"FakeClient: response list for {action!r} is exhausted"
                )
            item = handler.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        return handler


# ---------------------------------------------------------------------------
# Test 1: wait_for_plugin detects plugin on 2nd poll (1st raises RuntimeError)
# ---------------------------------------------------------------------------

def test_wait_for_plugin_detects_on_second_poll():
    """1st call raises RuntimeError (empty slot); 2nd returns the plugin name."""
    responses_seq = [
        RuntimeError("plugins.name: no plugin in slot"),
        {"name": "FabFilter Pro-Q 3"},
    ]
    client = FakeClient({
        "plugins.name": responses_seq,
    })

    result = wait_for_plugin(
        client,
        track=1,
        slot=0,
        expected="FabFilter Pro-Q 3",
        timeout=10.0,
        poll_interval=0.001,  # tiny to keep test fast
        location="mixer",
    )

    assert result["loaded"] is True
    assert result["plugin"] == "FabFilter Pro-Q 3"

    # Verify the correct action and params were sent
    assert len(client.calls) == 2
    for action, params in client.calls:
        assert action == "plugins.name"
        assert params["index"] == 1
        assert params["slot"] == 0
        assert params["location"] == "mixer"


# ---------------------------------------------------------------------------
# Test 2: wait_for_plugin times out when slot is always empty
# ---------------------------------------------------------------------------

def test_wait_for_plugin_timeout():
    """When the slot is always empty, loaded=False with a hint."""
    client = FakeClient({
        "plugins.name": RuntimeError("plugins.name: no plugin in slot"),
    })

    result = wait_for_plugin(
        client,
        track=2,
        slot=3,
        expected="Serum",
        timeout=0.05,
        poll_interval=0.01,
        location="channel",
    )

    assert result["loaded"] is False
    assert result["plugin"] is None
    assert "hint" in result
    assert "Serum" in result["hint"]
    assert "2" in result["hint"]   # track number
    assert "3" in result["hint"]   # slot number


# ---------------------------------------------------------------------------
# Test 3: probe_capabilities passes the report through unchanged
# ---------------------------------------------------------------------------

def test_probe_capabilities_passes_report_through():
    """probe_capabilities must call 'plugins.loadAttempt' and return its result."""
    fake_report = {
        "strategies": {
            "mixer.loadPlugin": False,
            "plugins.load": False,
            "channels.addChannel": False,
            "mixer.trackPluginLoad": False,
            "ui.navigateBrowser": True,
        }
    }
    client = FakeClient({
        "plugins.loadAttempt": fake_report,
    })

    result = probe_capabilities(client)

    assert result == fake_report
    assert len(client.calls) == 1
    action, params = client.calls[0]
    assert action == "plugins.loadAttempt"


# ---------------------------------------------------------------------------
# Test 4: BridgeUnavailable propagates out of wait_for_plugin
# ---------------------------------------------------------------------------

def test_wait_for_plugin_propagates_bridge_unavailable():
    """BridgeUnavailable (ConnectionError subclass) must NOT be swallowed."""
    client = FakeClient({
        "plugins.name": BridgeUnavailable("FL Studio is not running"),
    })

    with pytest.raises(BridgeUnavailable):
        wait_for_plugin(
            client,
            track=0,
            slot=0,
            expected="anything",
            timeout=10.0,
            poll_interval=0.001,
        )
