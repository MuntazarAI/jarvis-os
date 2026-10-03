"""Freshness engine (World Intelligence 1.0).

Freshness is contextual: news decays in hours, reference material in
months. Domain policies are explicit data (not magic globals), and
every assessment reports the policy used. Unknown stays unknown —
missing timestamps never become FRESH.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class FreshnessState(str, Enum):
    FRESH = "fresh"
    RECENT = "recent"
    AGING = "aging"
    STALE = "stale"
    EXPIRED = "expired"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class FreshnessPolicy:
    domain: str = "general"
    fresh_s: float = 6 * 3600.0
    recent_s: float = 24 * 3600.0
    aging_s: float = 7 * 24 * 3600.0
    expire_s: float = 30 * 24 * 3600.0


DOMAIN_POLICIES: dict[str, FreshnessPolicy] = {
    "news": FreshnessPolicy("news", fresh_s=3 * 3600.0,
                            recent_s=12 * 3600.0,
                            aging_s=3 * 24 * 3600.0,
                            expire_s=14 * 24 * 3600.0),
    "tech-news": FreshnessPolicy("tech-news", fresh_s=6 * 3600.0,
                                 recent_s=24 * 3600.0,
                                 aging_s=7 * 24 * 3600.0,
                                 expire_s=30 * 24 * 3600.0),
    "software-release": FreshnessPolicy(
        "software-release", fresh_s=7 * 24 * 3600.0,
        recent_s=30 * 24 * 3600.0, aging_s=90 * 24 * 3600.0,
        expire_s=365 * 24 * 3600.0),
    "reference": FreshnessPolicy(
        "reference", fresh_s=30 * 24 * 3600.0,
        recent_s=90 * 24 * 3600.0, aging_s=365 * 24 * 3600.0,
        expire_s=3 * 365 * 24 * 3600.0),
    "weather": FreshnessPolicy("weather", fresh_s=1 * 3600.0,
                               recent_s=3 * 3600.0,
                               aging_s=12 * 3600.0,
                               expire_s=24 * 3600.0),
    "general": FreshnessPolicy("general"),
}


def assess(published_at: float = 0.0, retrieved_at: float = 0.0,
           *, domain: str = "general",
           now: float = 0.0) -> dict[str, Any]:
    """Freshness from the best available timestamp. Published beats
    retrieved; neither present (or future-dated) means UNKNOWN."""
    stamp = now or time.time()
    policy = DOMAIN_POLICIES.get(domain, DOMAIN_POLICIES["general"])
    anchor = float(published_at or 0.0) or float(retrieved_at or 0.0)
    if anchor <= 0.0 or anchor > stamp + 60.0:
        return {"state": FreshnessState.UNKNOWN.value, "age_s": -1.0,
                "domain": policy.domain, "anchor": "none"}
    age = stamp - anchor
    anchor_kind = ("published" if published_at else "retrieved")
    if age <= policy.fresh_s:
        state = FreshnessState.FRESH
    elif age <= policy.recent_s:
        state = FreshnessState.RECENT
    elif age <= policy.aging_s:
        state = FreshnessState.AGING
    elif age <= policy.expire_s:
        state = FreshnessState.STALE
    else:
        state = FreshnessState.EXPIRED
    return {"state": state.value, "age_s": round(age, 1),
            "domain": policy.domain, "anchor": anchor_kind}


__all__ = ["FreshnessState", "FreshnessPolicy", "DOMAIN_POLICIES",
           "assess"]
