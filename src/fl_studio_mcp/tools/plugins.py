"""Plugin parameter tools: discovery with cache, batched writes.

Bridge handler facts (device_FLStudioMCP.py, _resolve_plugin_loc):
  Required params:  index (channel/mixer track index)
  Optional params:  slot (default -1), location ("channel" | "mixer", default "channel")

  plugins.name      → {"name": str}
  plugins.params    → {"total": int, "params": [{"idx", "name", "value", "value_string"}, ...]}
  plugins.getParam  uses p["param"] for the param index  → {"value": float, "value_string": str}
  plugins.setParam  uses p["param"] + p["value"]         → {"value": float, "value_string": str}
  plugins.setParams (Task 6, not in bridge yet)          → implementation calls it; tests use fakes
"""

from __future__ import annotations

import json
import re
from pathlib import Path

DEFAULT_CACHE = Path(__file__).resolve().parents[3] / "schemas" / "generated"


def _safe_filename(name: str) -> str:
    """Replace Windows/POSIX path-illegal characters with underscores."""
    return re.sub(r'[<>:"/\\|?*]', "_", name)


def discover_params(
    client,
    track: int,
    slot: int,
    cache_dir: Path = DEFAULT_CACHE,
    location: str = "channel",
) -> dict:
    """Return the full parameter map of the plugin at (track, slot).

    Uses a per-plugin-name JSON cache: discovery over TCP is slow
    (1000+ params on big plugins), so it runs once per plugin name.

    Returns:
        {"plugin": str, "params": {"total": int, "params": [...]}}
    """
    # Always call plugins.name to obtain the cache key.
    name_response = client.call("plugins.name", {
        "index": track,
        "slot": slot,
        "location": location,
    })
    plugin_name: str = name_response["name"]

    cache_file = Path(cache_dir) / f"{_safe_filename(plugin_name)}.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))

    params = client.call("plugins.params", {
        "index": track,
        "slot": slot,
        "location": location,
    })
    schema = {"plugin": plugin_name, "params": params}

    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(
        json.dumps(schema, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return schema


def set_params(
    client,
    track: int,
    slot: int,
    changes: list[dict],
    location: str = "channel",
) -> dict:
    """Apply several parameter changes in one TCP round-trip.

    Args:
        changes: [{"index": int, "value": float 0..1}, ...]

    Note: plugins.setParams is not in the bridge yet (Task 6).
          This function already calls it; tests use a FakeClient.
    """
    return client.call("plugins.setParams", {
        "index": track,
        "slot": slot,
        "location": location,
        "changes": changes,
    })


def get_param(
    client,
    track: int,
    slot: int,
    index: int,
    location: str = "channel",
) -> dict:
    """Fetch the current value of a single plugin parameter.

    Args:
        index: param index (passed as p["param"] to the bridge)

    Returns:
        {"value": float, "value_string": str}
    """
    return client.call("plugins.getParam", {
        "index": track,
        "slot": slot,
        "location": location,
        "param": index,
    })
