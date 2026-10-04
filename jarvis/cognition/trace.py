"""Unified interaction trace (Experience & Integration 1.0).

Assembles one interaction's footprint across the subsystems that
already record it — EventBus (sqlite), conversation + episodic memory
(metadata session/correlation), World Model events — keyed by the
cycle correlation id (and optional caller session id). Read-only;
never mutates stores. Unknown ids yield an explicit empty trace, not
an invented one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def trace_cycle(home: str | Path, correlation_id: str,
                session_id: str = "") -> dict[str, Any]:
    """Build the trace for one cycle correlation id."""
    home = Path(home)
    trace: dict[str, Any] = {
        "correlation_id": correlation_id,
        "session_id": session_id,
        "events": [], "conversation": [], "episodes": [],
        "world": [], "gaps": [],
    }
    if not correlation_id:
        trace["gaps"].append("no correlation id given")
        return trace
    try:
        from ..events.store import EventStore
        from ..core.config import PathsConfig
        events_path = home / PathsConfig().events
        if events_path.exists():
            store = EventStore(str(events_path))
            try:
                trace["events"] = [
                    {"type": e.type, "at": e.timestamp,
                     "payload": _summarize(e.payload)}
                    for e in store.by_correlation(correlation_id)]
            finally:
                store.close()
        else:
            trace["gaps"].append("no event store at home")
    except Exception as exc:
        trace["gaps"].append(f"events unreadable: {type(exc).__name__}")
    try:
        from ..memory.palace import MemoryPalace
        from ..core.config import PathsConfig
        db_path = home / PathsConfig().db
        if db_path.exists():
            palace = MemoryPalace(str(db_path))
            try:
                wanted = {correlation_id}
                if session_id:
                    wanted.add(session_id)
                for memory in palace.all(tier="conversation",
                                         limit=50):
                    sid = (memory.metadata or {}).get("session_id",
                                                       "")
                    if sid in wanted:
                        trace["conversation"].append({
                            "content": memory.content[:200],
                            "at": memory.created_at,
                            "session_id": sid})
                for memory in palace.all(tier="episodic", limit=50):
                    meta = memory.metadata or {}
                    if meta.get("correlation") in wanted:
                        trace["episodes"].append({
                            "content": memory.content[:200],
                            "at": memory.created_at})
            finally:
                palace.close()
        else:
            trace["gaps"].append("no memory db at home")
    except Exception as exc:
        trace["gaps"].append(f"memory unreadable: {type(exc).__name__}")
    return trace


def _summarize(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"value": str(payload)[:200]}
    out: dict[str, Any] = {}
    for key in ("input", "intent", "text", "source", "kind"):
        if key in payload:
            out[key] = str(payload[key])[:200]
    return out


__all__ = ["trace_cycle"]
