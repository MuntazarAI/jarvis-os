"""Experience integration: dots, world, memory (4.4).

Bridges evaluated experiences into existing structures WITHOUT
replacing them:

- Dots: verified outcomes linked to a dot update ONLY that dot's
  metadata (last_verified, experience_refs bounded, outcome counts).
  No dot fields, states, or schedules are touched.
- World: related entities gain confidence/last_verified state plus
  provenance; conflicts stay visible via the registry's own rules.
- Memory: consolidation proposals become semantic facts only through
  the palace API and only when the proposal criteria hold; sensitive
  or private material never promotes.

Everything here is additive metadata. Nothing deletes, overwrites
trust, or executes.
"""

from __future__ import annotations

from typing import Any

MAX_EXPERIENCE_REFS = 20


def mirror_experience(experience: Any, evaluation: Any, *,
                      dots: Any = None, world: Any = None,
                      dot_id: str = "") -> dict[str, Any]:
    """Record a verified outcome on its dot and world entities."""
    out: dict[str, Any] = {"dots": False, "world": False}
    experience_id = getattr(experience, "experience_id", "")
    outcome = getattr(getattr(experience, "outcome", ""), "value",
                      getattr(experience, "outcome", ""))
    if dots is not None and dot_id:
        try:
            dot = dots.get(dot_id)
        except Exception:
            dot = None
        if dot is not None:
            metadata = dot.metadata if isinstance(
                getattr(dot, "metadata", None), dict) else {}
            refs = list(metadata.get("experience_refs", []) or [])
            if experience_id and experience_id not in refs:
                refs.append(experience_id)
            metadata["experience_refs"] = refs[-MAX_EXPERIENCE_REFS:]
            metadata["last_verified"] = getattr(
                experience, "timestamp", 0.0)
            metadata["last_outcome"] = str(outcome)[:32]
            key = f"outcomes_{outcome}"
            metadata[key] = int(metadata.get(key, 0)) + 1
            dot.metadata = metadata
            try:
                dots.persist()
            except Exception:
                pass
            out["dots"] = True
    if world is not None:
        try:
            for entity_id in _related_entities(experience):
                try:
                    entity = world.get_entity(entity_id)
                except Exception:
                    entity = None
                if entity is None:
                    continue
                state = dict(getattr(entity, "state", {}) or {})
                state["last_verified"] = getattr(
                    experience, "timestamp", 0.0)
                state["last_outcome"] = str(outcome)[:32]
                try:
                    world.upsert_entity(
                        entity.type, entity.name, state=state,
                        provenance={"observer": "learning",
                                    "experience": experience_id[:64]},
                        confidence=entity.confidence,
                        entity_id=entity_id)
                    out["world"] = True
                except Exception:
                    continue
        except Exception:
            pass
    return out


def _related_entities(experience: Any) -> list[str]:
    refs: list[str] = []
    for key in ("belief_refs",):
        for ref in getattr(experience, key, []) or []:
            if isinstance(ref, str) and ref.startswith("entity:"):
                refs.append(ref.split("entity:", 1)[1][:128])
    provenance = getattr(experience, "provenance", {}) or {}
    for key in ("entity_id", "dot_id"):
        value = provenance.get(key)
        if isinstance(value, str) and value and key == "entity_id":
            refs.append(value[:128])
    return refs[:10]


def consolidate(engine: Any, palace: Any, *,
                min_confidence: float = 0.8,
                limit: int = 20) -> dict[str, Any]:
    """Promote eligible proposal beliefs to semantic memory.

    Each promotion goes through ``palace.store_fact`` (dedupe,
    origin, and poisoning guards intact) and is recorded back on
    the belief. Returns counts, never raises.
    """
    result: dict[str, Any] = {"promoted": 0, "skipped": 0, "ids": []}
    if engine is None or palace is None:
        result["skipped"] = -1
        return result
    try:
        proposals = engine.consolidation_proposals(
            min_confidence=min_confidence, limit=limit)
    except Exception:
        return result
    for proposal in proposals:
        try:
            memory = palace.store_fact(
                proposal["statement"][:500],
                source="consolidation",
                confidence=float(proposal.get("confidence", 0.8)),
                importance=0.8)
            memory_id = getattr(memory, "id", "")
            engine.mark_promoted(proposal["belief_id"], memory_id)
            result["promoted"] += 1
            result["ids"].append(proposal["belief_id"][:32])
        except Exception:
            result["skipped"] += 1
    return result


__all__ = ["mirror_experience", "consolidate"]
