"""Preference observation (Autonomy 1.0).

Counts repeated identical low-risk choices (format picks, approved
safe defaults). At >=3 repetitions a preference belief is recorded
(confidence capped, provenance-marked, user-overridable). Preferences
are suggestions: they NEVER touch permissions, grants, policy, or
authorization state — enforced structurally (this module has no
imports from policy packages and no write path to them).
"""

from __future__ import annotations

import time
from typing import Any

PREFERENCE_THRESHOLD = 3
PREFERENCE_CONFIDENCE = 0.6


def observe_choice(store: Any, action_key: str, choice: str, *,
                   at: float = 0.0) -> dict[str, Any]:
    """Record one observed choice. Returns status, not authority."""
    action_key = str(action_key or "")[:120]
    choice = str(choice or "")[:200]
    if not action_key or not choice:
        return {"recorded": False, "reason": "empty"}
    counts = getattr(store, "_preference_counts", None)
    if counts is None:
        counts = {}
        try:
            store._preference_counts = counts
        except Exception:
            pass
    key = f"{action_key}={choice}"
    counts[key] = counts.get(key, 0) + 1
    if counts[key] < PREFERENCE_THRESHOLD:
        return {"recorded": True, "preference": False,
                "count": counts[key]}
    statement = f"prefers {choice} for {action_key}"
    try:
        from ..cognition.beliefs import BeliefStore
        beliefs = store if isinstance(store, BeliefStore) else None
        if beliefs is None:
            return {"recorded": True, "preference": False,
                    "reason": "no belief store"}
        existing = [b for b in beliefs.find(limit=1000)
                    if b.statement == statement]
        if not existing:
            beliefs.upsert(statement, PREFERENCE_CONFIDENCE,
                           provenance={"origin": "autonomy-preferences",
                                       "count": counts[key]},
                           privacy_class="local")
        return {"recorded": True, "preference": True,
                "statement": statement}
    except Exception as exc:
        return {"recorded": False,
                "reason": f"{type(exc).__name__}"}


def set_preference(store: Any, statement: str,
                   confidence: float = 0.8) -> bool:
    """Explicit user override. Returns stored or not."""
    try:
        from ..cognition.beliefs import BeliefStore
        if not isinstance(store, BeliefStore):
            return False
        store.upsert(str(statement or "")[:200],
                     max(0.05, min(0.95, float(confidence or 0.8))),
                     provenance={"origin": "user-override"},
                     privacy_class="local")
        return True
    except Exception:
        return False


__all__ = ["observe_choice", "set_preference", "PREFERENCE_THRESHOLD"]
