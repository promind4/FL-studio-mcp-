"""Plugin loading: capability probe + assisted-insertion fallback.

The public FL API does not expose plugin loading. Strategy:
1. probe_capabilities() asks the bridge what the runtime API actually has
2. wait_for_plugin() implements the assisted fallback: the LLM asks the
   user to insert the plugin, then polls until it appears in the slot.
"""

from __future__ import annotations

import time


def probe_capabilities(client) -> dict:
    """One-time runtime probe. Result tells which strategies are viable."""
    return client.call("plugins.loadAttempt", {})


def wait_for_plugin(client, track: int, slot: int, expected: str,
                    timeout: float = 60.0, poll_interval: float = 1.0,
                    location: str = "mixer") -> dict:
    """Poll (track, slot) until a plugin whose name contains `expected`
    appears, or timeout. Used after asking the user to insert it manually."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = client.call("plugins.name",
                                 {"index": track, "slot": slot, "location": location})
            name = (result or {}).get("name", "") or ""
        except RuntimeError:
            name = ""  # empty slot -> bridge error -> keep polling
        if expected.lower() in name.lower():
            return {"loaded": True, "plugin": name}
        time.sleep(poll_interval)
    return {"loaded": False, "plugin": None,
            "hint": "No plugin matching '%s' appeared in track %s slot %s within %ss"
                    % (expected, track, slot, timeout)}
