"""Briefings from structured evidence (World Intelligence 1.0).

A briefing is generated from Answer objects — claims, conflicts,
freshness, provenance — never from a blind prompt over raw scraped
content. Kinds: morning, evening, topic, project, change. Stale or
missing evidence is labeled, never presented as current.
"""

from __future__ import annotations

from typing import Any

MAX_ITEMS = 8


def build_briefing(kind: str, answers: list[Any], *,
                   title: str = "") -> dict[str, Any]:
    """Assemble one briefing dict from researcher answers."""
    kind = str(kind or "morning")[:20]
    items: list[dict[str, Any]] = []
    conflicts = 0
    uncertain: list[str] = []
    for answer in answers:
        to_dict = getattr(answer, "to_dict", None)
        data = to_dict() if callable(to_dict) else (
            answer if isinstance(answer, dict) else {})
        for claim in (data.get("claims") or [])[:MAX_ITEMS]:
            items.append({
                "subject": claim.get("subject", ""),
                "predicate": claim.get("predicate", ""),
                "object": claim.get("object", ""),
                "corroborated": bool(
                    (claim.get("corroboration") or {}).get(
                        "corroborated", False)),
                "freshness": (data.get("freshness") or {}).get(
                    "states", ["unknown"])[0]
                if isinstance((data.get("freshness") or {}).get(
                        "states"), list) else "unknown"})
        if not data.get("claims") and data.get("evidence"):
            for entry in data["evidence"][:MAX_ITEMS - len(items)]:
                title = str(entry.get("title", ""))[:100]
                if title:
                    items.append({
                        "subject": "Reported",
                        "predicate": "in",
                        "object": f"{title} "
                                  f"[{entry.get('source_id', '?')}]",
                        "corroborated": False,
                        "freshness": "unknown"})
            uncertain.append("headlines only: claims not extracted, "
                             "treat as unverified leads")
        conflicts += len(data.get("conflicts", []) or [])
        uncertain.extend(data.get("uncertainty", []) or [])
        if len(items) >= MAX_ITEMS:
            break
    lines = [f"{it['subject']} {it['predicate']} {it['object']}"
             f"{'' if it['corroborated'] else ' (unverified)'}"
             for it in items[:MAX_ITEMS]]
    if not lines:
        lines = ["No verified current evidence available."]
        uncertain.append("briefing has no evidence; do not treat "
                         "as current")
    return {"kind": kind, "title": title[:120] or kind.title(),
            "lines": lines, "conflicts": conflicts,
            "uncertainty": sorted(set(uncertain))[:10],
            "items": len(items)}


__all__ = ["build_briefing", "MAX_ITEMS"]
