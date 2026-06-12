"""Tests for plugin parameter discovery with cache and batched writes.

Bridge handler formats (from device_FLStudioMCP.py):
  _resolve_plugin_loc reads: index (required), slot (default -1), location (default "channel")
  plugins.name    → {"name": str}
  plugins.params  → {"total": int, "params": [{"idx": int, "name": str, "value": float, "value_string": str}, ...]}
  plugins.getParam uses p["param"] → {"value": float, "value_string": str}
  plugins.setParam uses p["param"] + p["value"] → {"value": float, "value_string": str}
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fl_studio_mcp.tools.plugins import discover_params, set_params, get_param


class FakeClient:
    """Records calls and returns pre-configured responses."""

    def __init__(self, responses: dict):
        self.responses = responses
        self.calls: list[tuple[str, dict]] = []

    def call(self, action: str, params: dict) -> object:
        self.calls.append((action, params))
        if action not in self.responses:
            raise KeyError(f"FakeClient: no response configured for action {action!r}")
        return self.responses[action]


# ---------------------------------------------------------------------------
# Test 1: discover_params builds the schema and writes cache
# ---------------------------------------------------------------------------

def test_discover_params_builds_schema(tmp_path):
    fake_params = [
        {"idx": 0, "name": "Cutoff", "value": 0.5, "value_string": "50%"},
        {"idx": 1, "name": "Resonance", "value": 0.3, "value_string": "30%"},
    ]
    client = FakeClient({
        "plugins.name": {"name": "Serum"},
        "plugins.params": {"total": 2, "params": fake_params},
    })

    schema = discover_params(client, track=1, slot=0, cache_dir=tmp_path)

    assert schema["plugin"] == "Serum"
    assert schema["params"] == {"total": 2, "params": fake_params}

    # Verify calls were made with correct bridge param names
    actions = [c[0] for c in client.calls]
    assert "plugins.name" in actions
    assert "plugins.params" in actions

    name_params = next(p for a, p in client.calls if a == "plugins.name")
    assert name_params["index"] == 1
    assert name_params["slot"] == 0

    # Cache file must exist and contain the schema
    cache_file = tmp_path / "Serum.json"
    assert cache_file.exists()
    cached = json.loads(cache_file.read_text(encoding="utf-8"))
    assert cached == schema


# ---------------------------------------------------------------------------
# Test 2: discover_params uses cache and does NOT call plugins.params again
# ---------------------------------------------------------------------------

def test_discover_params_uses_cache(tmp_path):
    cached_schema = {
        "plugin": "Vital",
        "params": {
            "total": 1,
            "params": [{"idx": 0, "name": "Volume", "value": 1.0, "value_string": "100%"}],
        },
    }
    cache_file = tmp_path / "Vital.json"
    cache_file.write_text(json.dumps(cached_schema), encoding="utf-8")

    # name is still called to look up the cache key; params must NOT be called
    client = FakeClient({
        "plugins.name": {"name": "Vital"},
    })

    schema = discover_params(client, track=0, slot=2, cache_dir=tmp_path)

    assert schema == cached_schema

    actions = [c[0] for c in client.calls]
    assert "plugins.params" not in actions, (
        "plugins.params must not be called when a valid cache file exists"
    )


# ---------------------------------------------------------------------------
# Test 3: set_params batches multiple changes in one call
# ---------------------------------------------------------------------------

def test_set_params_batches_changes():
    changes = [
        {"index": 0, "value": 0.75},
        {"index": 5, "value": 0.1},
    ]
    expected_response = {"applied": 2}
    client = FakeClient({
        "plugins.setParams": expected_response,
    })

    result = set_params(client, track=2, slot=1, changes=changes)

    assert result == expected_response

    # Exactly one call
    assert len(client.calls) == 1
    action, params = client.calls[0]
    assert action == "plugins.setParams"

    # Both changes must be present in a single call
    assert params["changes"] == changes
    assert params["index"] == 2
    assert params["slot"] == 1


# ---------------------------------------------------------------------------
# Test 4: get_param returns bridge response
# ---------------------------------------------------------------------------

def test_get_param_returns_value():
    client = FakeClient({
        "plugins.getParam": {"value": 0.42, "value_string": "42%"},
    })

    result = get_param(client, track=3, slot=0, index=7)

    assert result == {"value": 0.42, "value_string": "42%"}
    assert len(client.calls) == 1
    action, params = client.calls[0]
    assert action == "plugins.getParam"
    assert params["index"] == 3
    assert params["slot"] == 0
    assert params["param"] == 7


# ---------------------------------------------------------------------------
# Test 5: cache filename sanitises special characters
# ---------------------------------------------------------------------------

def test_discover_params_sanitises_plugin_name(tmp_path):
    """Plugin names containing path-illegal chars must not crash on Windows."""
    fake_params: list = []
    client = FakeClient({
        "plugins.name": {"name": 'Vst<Plugin>: "Weird/Name"'},
        "plugins.params": {"total": 0, "params": fake_params},
    })

    schema = discover_params(client, track=0, slot=0, cache_dir=tmp_path)

    assert schema["plugin"] == 'Vst<Plugin>: "Weird/Name"'
    # The cache file must exist (name sanitised) — just one file created
    cache_files = list(tmp_path.iterdir())
    assert len(cache_files) == 1
