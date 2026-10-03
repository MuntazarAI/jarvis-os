"""Currentness routing (World Intelligence 1.0).

Decides BEFORE retrieval whether a question needs the live web at all:

- STATIC: timeless knowledge (no retrieval).
- CURRENT: needs fresh external information.
- HISTORICAL: needs dated/past information (retrieval allowed, but
  scoped to archives, not "latest").
- LOCAL: answered from authorized local state (computer, devices).
- MIXED: local context + current retrieval (project-aware questions).
- RESEARCH: open-ended investigation (bounded research pipeline).
- CLARIFY: underspecified; ask instead of browsing blindly.

Routing is keyword + structural heuristics, deterministic, and
conservative: ambiguous defaults to STATIC (never browse without a
reason). It plugs into the CognitiveSupervisor path — it never
bypasses it.
"""

from __future__ import annotations

import re
from typing import Any

CURRENT_MARKERS = (
    "right now", "today", "latest", "newest", "breaking", "current",
    "this week", "this morning", "tonight", "yesterday", "recently",
    "happening", "news", "update", "release", "announced",
)

HISTORICAL_MARKERS = (
    "history of", "in 19", "in 20", "last year", "decade", "origin of",
    "when did", "used to", "back then", "historical",
)

LOCAL_MARKERS = (
    "my computer", "my laptop", "my projects", "my home", "my files",
    "running on", "disk", "battery", "my devices",
)

RESEARCH_MARKERS = (
    "research", "investigate", "deep dive", "compare", "briefing",
    "brief me", "report on",
)


def route(query: str, *, active_project: str = "",
          topics: list[str] | None = None) -> dict[str, Any]:
    """Classify one question. Returns route + reasons + retrieval
    hints (domains, time scope). Pure function, no I/O."""
    text = (query or "").strip()
    lowered = text.lower()
    reasons: list[str] = []
    if len(text.split()) < 3 and not any(
            marker in lowered for marker in CURRENT_MARKERS):
        return {"route": "CLARIFY", "reasons": ["too short to route"],
                "domains": [], "time_scope": "none"}
    local = any(marker in lowered for marker in LOCAL_MARKERS)
    current = any(marker in lowered for marker in CURRENT_MARKERS)
    historical = any(marker in lowered for marker in HISTORICAL_MARKERS)
    research = any(marker in lowered for marker in RESEARCH_MARKERS)
    year_refs = re.findall(r"\b(19|20)\d{2}\b", text)
    if research or ("compare" in lowered and current):
        reasons.append("open investigation requested")
        return {"route": "RESEARCH", "reasons": reasons,
                "domains": ["news", "reference"],
                "time_scope": "recent"}
    if local and current:
        reasons.append("local state + current context")
        return {"route": "MIXED", "reasons": reasons,
                "domains": ["local", "news"], "time_scope": "recent",
                "project": active_project[:120]}
    if local:
        reasons.append("authorized local state suffices")
        return {"route": "LOCAL", "reasons": reasons,
                "domains": ["local"], "time_scope": "now"}
    if historical or (year_refs and not current):
        reasons.append("dated scope requested")
        return {"route": "HISTORICAL", "reasons": reasons,
                "domains": ["reference"], "time_scope": "past"}
    if current:
        reasons.append("freshness-sensitive wording")
        domains = ["news"]
        if "linux" in lowered or "release" in lowered:
            domains.append("software-release")
        return {"route": "CURRENT", "reasons": reasons,
                "domains": domains, "time_scope": "recent"}
    matched_topics = [t for t in (topics or [])
                      if t.lower() in lowered]
    if matched_topics:
        reasons.append(f"subscribed topic: {matched_topics[0]}")
        return {"route": "MIXED", "reasons": reasons,
                "domains": ["news", "local"],
                "time_scope": "recent",
                "project": active_project[:120]}
    return {"route": "STATIC", "reasons": ["no freshness signal"],
            "domains": [], "time_scope": "none"}


__all__ = ["route", "CURRENT_MARKERS", "HISTORICAL_MARKERS",
           "LOCAL_MARKERS", "RESEARCH_MARKERS"]
