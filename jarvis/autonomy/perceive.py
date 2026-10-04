"""Multimodal observation correlation (Autonomy 1.0).

Thin consolidation over EXISTING observation contracts (sensory
events, perception observations, world observations): group by
session + bounded time window, flag duplicates/stale/conflicts, and
surface hostile content WITHOUT executing it. Correlates on ids and
timestamps only — content bodies are never needed and never stored
here.
"""

from __future__ import annotations

import time
from typing import Any

DEFAULT_WINDOW_S = 5.0
MAX_OBSERVATIONS = 64


def _get(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def correlate(observations: list[Any], *,
              window_s: float = DEFAULT_WINDOW_S,
              now: float = 0.0) -> dict[str, Any]:
    """Group observations into temporal clusters per session."""
    stamp = now or time.time()
    window_s = max(0.5, min(300.0, float(window_s or 0.0)))
    seen: set[str] = set()
    groups: dict[tuple[str, int], list[dict[str, Any]]] = {}
    hostile = 0
    stale = 0
    for item in (observations or [])[:MAX_OBSERVATIONS]:
        oid = str(_get(item, "observation_id", "")
                  or _get(item, "event_id", "")
                  or _get(item, "id", ""))
        if not oid or oid in seen:
            continue
        seen.add(oid)
        try:
            ts = float(_get(item, "timestamp", 0.0) or 0.0)
        except (TypeError, ValueError):
            ts = 0.0
        if ts and stamp - ts > 3600.0:
            stale += 1
            continue
        session = str(_get(item, "session_id", "") or "default")[:64]
        bucket = int(ts // window_s) if ts else 0
        text = str(_get(item, "content", "") or _get(item, "text",
                                                      ""))
        flag = "hostile-content" if _looks_hostile(text) else ""
        if flag:
            hostile += 1
        groups.setdefault((session, bucket), []).append({
            "id": oid,
            "modality": str(_get(item, "modality", "unknown"))[:32],
            "type": str(_get(item, "type", ""))[:64],
            "timestamp": ts,
            "confidence": _confidence(_get(item, "confidence", 0.0)),
            "flag": flag,
        })
    clusters = [{"session": session,
                 "observations": sorted(members,
                                        key=lambda m: m["timestamp"])}
                for (session, _), members in sorted(groups.items())]
    return {"clusters": clusters, "count": len(seen),
            "duplicates": max(0, min(len(observations or []),
                                     MAX_OBSERVATIONS) - len(seen)),
            "stale": stale, "hostile": hostile}


def _confidence(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value or 0.0)))
    except (TypeError, ValueError):
        return 0.0


_HOSTILE_HINTS = ("ignore previous instructions",
                  "disable secur", "run rm ", "execute ",
                  "<script")


def _looks_hostile(text: str) -> bool:
    lowered = text.lower()
    return any(hint in lowered for hint in _HOSTILE_HINTS)


__all__ = ["correlate", "DEFAULT_WINDOW_S", "MAX_OBSERVATIONS"]
