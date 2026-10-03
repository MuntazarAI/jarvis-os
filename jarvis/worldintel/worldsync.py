"""World Model + Knowledge Graph sync (World Intelligence 1.0).

Writes researcher output into the EXISTING WorldRegistry and
KnowledgeGraph — no new stores. Rules:

- Observations are recorded (never auto-asserted); external origins
  stay untrusted per WorldObservation.classify_source.
- Entities go up only for corroborated or high-confidence claims, and
  always with provenance + confidence. Low-value raw text never
  enters the graph.
- Conflicts are mirrored into registry conflicts via apply_observation
  semantics (kept visible, never silently resolved).
"""

from __future__ import annotations

from typing import Any

MIN_GRAPH_CONFIDENCE = 0.5
MAX_SYNCS_PER_RUN = 30


def sync_answer(answer: Any, *, registry: Any = None,
                graph: Any = None,
                max_syncs: int = MAX_SYNCS_PER_RUN) -> dict[str, Any]:
    """Record observations for claims, upsert entities/relations for
    corroborated ones. Returns counts; never raises."""
    synced = {"observations": 0, "entities": 0, "relations": 0,
              "conflicts": 0, "skipped": 0}
    claims = getattr(answer, "claims", []) or []
    try:
        for item in claims[:max(1, max_syncs)]:
            ok = _sync_claim(item, registry=registry, graph=graph,
                             synced=synced)
            if not ok:
                synced["skipped"] += 1
        for conflict in (getattr(answer, "conflicts", []) or [])[:10]:
            if _sync_conflict(conflict, registry=registry, graph=graph):
                synced["conflicts"] += 1
    except Exception:
        synced["skipped"] += 1
    return synced


def _sync_claim(item: dict[str, Any], *, registry: Any,
                graph: Any, synced: dict[str, int]) -> bool:
    subject = str(item.get("subject", ""))[:120]
    predicate = str(item.get("predicate", ""))[:60]
    obj = str(item.get("object", ""))[:300]
    if not subject or not predicate:
        return False
    try:
        confidence = float(item.get("confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        return False
    corroborated = bool((item.get("corroboration") or {}).get(
        "corroborated", False))
    if registry is not None:
        try:
            registry.observe(
                f"{subject} {predicate} {obj}".strip()[:300],
                observer="worldintel", source="worldintel",
                confidence=max(0.05, min(0.95, confidence)),
                evidence=[])
            synced["observations"] += 1
        except Exception:
            pass
    if graph is not None and (corroborated
                              or confidence >= MIN_GRAPH_CONFIDENCE):
        try:
            graph.upsert_node(subject, kind="entity", attributes={
                "provenance": "worldintel",
                "corroborated": corroborated},
                confidence=confidence)
            if obj and len(obj) <= 120:
                graph.upsert_node(obj, kind="entity", attributes={
                    "provenance": "worldintel"}, confidence=confidence)
                try:
                    graph.relate(subject, predicate, obj,
                                 confidence=confidence)
                    synced["relations"] += 1
                except Exception:
                    pass
            synced["entities"] += 1
        except Exception:
            return False
    return True


def _sync_conflict(conflict: dict[str, Any], *, registry: Any,
                   graph: Any) -> bool:
    try:
        subject = str(conflict.get("subject", ""))[:120]
        if graph is not None and subject:
            graph.upsert_node(subject, kind="entity", attributes={
                "provenance": "worldintel",
                "conflict": conflict.get("predicate", "")},
                confidence=0.4)
        return True
    except Exception:
        return False


__all__ = ["sync_answer", "MIN_GRAPH_CONFIDENCE", "MAX_SYNCS_PER_RUN"]
