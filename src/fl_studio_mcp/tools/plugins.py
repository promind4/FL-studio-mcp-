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
import os
import re
import struct
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

    PAGE_SIZE = 128
    all_params: list = []
    total: int | None = None
    offset = 0

    while True:
        page = client.call("plugins.params", {
            "index": track,
            "slot": slot,
            "location": location,
            "limit": PAGE_SIZE,
            "offset": offset,
        })
        if total is None:
            total = page["total"]
        all_params.extend(page["params"])

        if len(all_params) >= total:
            break

        if len(page["params"]) == 0:
            raise RuntimeError(
                f"plugins.params pagination stalled: collected {len(all_params)}/{total} "
                f"params but the bridge returned an empty page at offset {offset}."
            )

        offset += len(page["params"])

    params = {"total": total, "params": all_params}
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


def get_params(
    client,
    track: int,
    slot: int,
    indices: list[int],
    location: str = "channel",
) -> dict:
    """Read several plugin parameters in one round-trip.

    Args:
        indices: [int, ...] param indices to read.

    Returns:
        {"params": [{"index": int, "value": float, "value_string": str}, ...]}
        Mirrors set_params; turns N single reads into one ~150ms round-trip.
    """
    return client.call("plugins.getParams", {
        "index": track,
        "slot": slot,
        "location": location,
        "indices": indices,
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


# ---------------------------------------------------------------------------
# Plugin database scanner (disk-side, no bridge call required)
# ---------------------------------------------------------------------------

_DEFAULT_PLUGIN_DB = (
    Path(os.environ.get("FLSTUDIO_INSTALL", r"D:\Image-Line\FL Studio"))
    / "Presets" / "Plugin database" / "Installed"
)


def _fst_plugin_name(path: Path) -> str | None:
    """Extract the plugin display name from an FL Studio .fst database file.

    FST files embed strings as null-terminated UTF-16 LE sequences.
    The layout is typically: [wrapper-type-name, plugin-display-name, ...].
    """
    try:
        data = path.read_bytes()
    except OSError:
        return None
    # Find all UTF-16 LE string runs (at least 3 chars = 6 bytes)
    matches = re.findall(rb"(?:[\x20-\x7e]\x00){3,}", data)
    strings = [m.decode("utf-16-le").rstrip("\x00") for m in matches]
    if len(strings) >= 2:
        return strings[1]
    if strings:
        return strings[0]
    return None


def list_available_plugins(
    plugin_db: Path = _DEFAULT_PLUGIN_DB,
) -> dict:
    """Scan the FL Studio plugin database and return all installed plugins.

    Returns:
        {
          "total": int,
          "plugins": [
            {
              "name": str,
              "type": "effect" | "generator",
              "format": "fruity" | "vst" | "vst3" | "unknown",
            },
            ...
          ]
        }
    """
    if not plugin_db.is_dir():
        return {
            "total": 0,
            "plugins": [],
            "error": f"Plugin database not found: {plugin_db}",
        }

    results: list[dict] = []
    seen: set[tuple[str, str, str]] = set()

    for fst_path in sorted(plugin_db.rglob("*.fst")):
        rel = fst_path.relative_to(plugin_db)
        parts = rel.parts

        # parts[0] = "Effects" | "Generators", parts[1] = "VST" | "VST3" | "Fruity" | ...
        raw_type = parts[0].lower() if len(parts) >= 1 else "unknown"
        raw_fmt = parts[1].lower() if len(parts) >= 2 else "unknown"

        plugin_type = "effect" if "effect" in raw_type else "generator" if "generator" in raw_type else raw_type
        fmt = "fruity" if raw_fmt == "fruity" else "vst3" if raw_fmt == "vst3" else "vst" if raw_fmt == "vst" else "unknown"

        name = _fst_plugin_name(fst_path) or fst_path.stem
        key = (name, plugin_type, fmt)
        if key in seen:
            continue
        seen.add(key)
        results.append({"name": name, "type": plugin_type, "format": fmt})

    results.sort(key=lambda p: (p["type"], p["format"], p["name"].lower()))
    return {"total": len(results), "plugins": results}
