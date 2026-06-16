"""Lightweight session journal — JSON Lines, one file per mixing session.

Not a learning system. Just a durable trace of (state + actions + scores)
so a future session (or a future analysis) can answer "what did we already
try on this track, and what did fl_evaluate_mix_quality/fl_detect_masking
say about it" without relying on conversation memory.

One line per event, append-only — safe to write incrementally during a
long mixing session without re-reading/rewriting the whole file.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

_SESSIONS_DIR = Path(__file__).resolve().parents[3] / "sessions"


def _session_path(session: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in session)
    return _SESSIONS_DIR / f"{safe}.jsonl"


def log_event(session: str, event_type: str, data: dict) -> dict:
    """Append one event to the session journal.

    event_type: free-form label (e.g. "plugin_change", "mix_score",
    "masking_report", "note") — kept open-ended so the caller doesn't need
    a fixed taxonomy upfront.
    data: arbitrary JSON-serializable payload (track, plugin, params changed,
    scores, conflicts, etc).
    """
    _SESSIONS_DIR.mkdir(exist_ok=True)
    path = _session_path(session)
    entry = {"ts": round(time.time(), 1), "type": event_type, "data": data}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    count = sum(1 for _ in path.open("r", encoding="utf-8"))
    return {"logged": True, "session": session, "event_count": count}


def get_history(session: str, limit: int | None = None,
                event_type: str | None = None) -> dict:
    """Read back the journal for one session, oldest first.

    limit: only return the last N events (None = all).
    event_type: filter to one event type (None = all types).
    """
    path = _session_path(session)
    if not path.exists():
        return {"session": session, "events": [],
                "note": "No journal yet for this session."}

    events = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            if event_type is not None and entry["type"] != event_type:
                continue
            events.append(entry)

    if limit is not None:
        events = events[-limit:]

    return {"session": session, "event_count": len(events), "events": events}


def list_sessions() -> dict:
    """List all known sessions with their event count and last activity."""
    if not _SESSIONS_DIR.exists():
        return {"sessions": []}

    sessions = []
    for path in sorted(_SESSIONS_DIR.glob("*.jsonl")):
        count = sum(1 for _ in path.open("r", encoding="utf-8"))
        sessions.append({
            "session": path.stem,
            "event_count": count,
            "last_modified": time.strftime(
                "%Y-%m-%d %H:%M", time.localtime(path.stat().st_mtime)),
        })
    return {"sessions": sessions}
