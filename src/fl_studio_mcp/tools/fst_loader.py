"""FST mixer preset selection and loading.

Workflow:
1. load_catalog()      — reads mixer_preset_catalog.json
2. select_preset()     — picks best FST for a plugin list
3. deploy_preset()     — copies chosen FST to _MCP.fst (fixed first-position path)
4. load_via_browser()  — navigates browser to _MCP.fst (always first = ~4 steps)
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

# Catalog lives next to this package's project root
_CATALOG_PATH = Path(__file__).parents[3] / "mixer_preset_catalog.json"
_MCP_PRESET_NAME = "_MCP.fst"


def _catalog_path() -> Path:
    return _CATALOG_PATH


def load_catalog() -> dict:
    p = _catalog_path()
    if not p.exists():
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def select_preset(wanted_plugins: list[str], catalog: dict | None = None) -> dict | None:
    """Return the catalog entry whose plugin list best matches wanted_plugins.

    Scoring: number of wanted plugins present in the preset's plugin list.
    Ties broken by fewest extra unwanted plugins (smaller chain = more precise).
    Returns None if catalog is empty.
    """
    if catalog is None:
        catalog = load_catalog()
    if not catalog:
        return None

    wanted_lower = {p.lower() for p in wanted_plugins}
    best = None
    best_score = (-1, 999)

    for rel, entry in catalog.items():
        preset_plugins = {p.lower() for p in entry.get("plugins", [])}
        # How many wanted plugins does this preset cover?
        hits = len(wanted_lower & preset_plugins)
        extras = len(preset_plugins - wanted_lower)
        score = (hits, -extras)
        if score > best_score:
            best_score = score
            best = {"rel": rel, "path": entry["path"],
                    "plugins": entry["plugins"], "hits": hits, "extras": extras}

    return best


def deploy_preset(src_path: str) -> str:
    """Copy src_path FST to the Mixer presets folder as _MCP.fst.

    Returns the destination path (always the same fixed path).
    """
    src = Path(src_path)
    dest_dir = src.parent if src.parent.name != "Mixer presets" else src.parent
    # Always place alongside existing presets so the browser can find it
    dest = dest_dir / _MCP_PRESET_NAME
    shutil.copy2(src, dest)
    return str(dest)


def list_presets(catalog: dict | None = None) -> list[dict]:
    """Return all catalog entries as a flat list for LLM inspection."""
    if catalog is None:
        catalog = load_catalog()
    return [
        {"name": rel, "path": entry["path"], "plugins": entry["plugins"]}
        for rel, entry in catalog.items()
    ]
