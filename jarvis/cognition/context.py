"""Context engine (5.0): bounded relevance assembly.

Gathers CURRENT / RECENT / RELEVANT / HISTORICAL context from world,
memory, spatial, missions, devices, and experiences — scored and
filtered, never dumped whole. Every fact carries source + confidence;
missing information is listed as gaps, never invented.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

MAX_FACTS = 24
MAX_TEXT = 300


@dataclass
class ContextFact:
    content: str
    source: str  # world|memory|spatial|mission|device|experience|event
    confidence: float = 0.5
    recency_s: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AssembledContext:
    facts: list[ContextFact] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    budgets_used: dict[str, int] = field(default_factory=dict)


def _score(fact: ContextFact, query_terms: set[str]) -> float:
    text = fact.content.lower()
    overlap = sum(1 for term in query_terms if term in text)
    recency = 1.0 / (1.0 + fact.recency_s / 3600.0)
    return overlap * 2.0 + fact.confidence + recency * 0.5


class ContextEngine:
    """Deterministic bounded context assembly."""

    def __init__(self, *, world: Any = None, palace: Any = None,
                 spatial: Any = None, missions: Any = None,
                 max_facts: int = MAX_FACTS) -> None:
        self.world = world
        self.palace = palace
        self.spatial = spatial
        self.missions = missions
        self.max_facts = max(1, max_facts)
        self.metrics: dict[str, int] = {"assembled": 0, "facts": 0,
                                        "gaps": 0}

    def assemble(self, query: str = "",
                 event: dict[str, Any] | None = None,
                 goal: str = "") -> AssembledContext:
        """Collect, score, and cut context. Never raises for missing
        subsystems (records gaps instead)."""
        terms = {t.lower() for t in
                 f"{query} {goal} {(event or {}).get('type', '')}".split()
                 if len(t) > 2}
        facts: list[ContextFact] = []
        gaps: list[str] = []
        facts.extend(self._world_facts(terms, gaps))
        facts.extend(self._memory_facts(query or goal, gaps))
        facts.extend(self._mission_facts(gaps))
        facts.extend(self._event_facts(event, gaps))
        scored = sorted((( _score(f, terms), f) for f in facts),
                        key=lambda pair: pair[0], reverse=True)
        kept = [fact for _, fact in scored[:self.max_facts]]
        context = AssembledContext(facts=kept, gaps=gaps[:10],
                                   budgets_used={"candidates": len(facts),
                                                 "kept": len(kept)})
        self.metrics["assembled"] += 1
        self.metrics["facts"] += len(kept)
        self.metrics["gaps"] += len(context.gaps)
        return context

    # -- sources (each isolated; absence becomes a gap) --------------------

    def _world_facts(self, terms: set[str], gaps: list[str]):
        if self.world is None:
            gaps.append("no world state available")
            return []
        try:
            state = self.world.get_current_state()
        except Exception:
            gaps.append("world state unreadable")
            return []
        facts = []
        items = list(state.items())[:50]
        for entity_id, info in items:
            if not isinstance(info, dict):
                continue
            text = f"{info.get('type', '')} {info.get('name', '')} " \
                f"{info.get('state', '')}"[:MAX_TEXT]
            facts.append(ContextFact(
                content=text, source="world",
                confidence=float(info.get("confidence", 0.5) or 0.0),
                metadata={"entity_id": str(entity_id)[:64]}))
        if not facts:
            gaps.append("world has no entities")
        return facts

    def _memory_facts(self, query: str, gaps: list[str]):
        if self.palace is None:
            gaps.append("no memory available")
            return []
        if not query.strip():
            return []
        try:
            hits = self.palace.search(query[:200], limit=5)
        except Exception:
            gaps.append("memory search failed")
            return []
        facts = []
        for memory, score in hits:
            facts.append(ContextFact(
                content=str(getattr(memory, "content", ""))[:MAX_TEXT],
                source="memory", confidence=float(score or 0.0),
                metadata={"memory_id": str(getattr(memory, "id", ""))[:64]}))
        return facts

    def _mission_facts(self, gaps: list[str]):
        if self.missions is None:
            return []
        try:
            missions = self.missions.list() if hasattr(
                self.missions, "list") else []
        except Exception:
            gaps.append("missions unreadable")
            return []
        facts = []
        for mission in missions[:5]:
            if isinstance(mission, dict):
                name = str(mission.get("name", ""))[:80]
                status = str(mission.get("status", ""))[:32]
            else:
                name = str(getattr(mission, "name", ""))[:80]
                status = str(getattr(mission, "status", ""))[:32]
            facts.append(ContextFact(
                content=f"mission {name} [{status}]", source="mission",
                confidence=0.6))
        return facts

    def _event_facts(self, event: dict[str, Any] | None,
                     gaps: list[str]):
        if not event:
            gaps.append("no triggering event provided")
            return []
        payload = event.get("payload", {}) if isinstance(event, dict) \
            else {}
        text = str(payload.get("text", payload.get("summary", "")))[:MAX_TEXT]
        return [ContextFact(content=f"event: {text}" or "event received",
                            source="event", confidence=0.9,
                            metadata={"event_id": str(event.get(
                                "event_id", ""))[:64]})]


__all__ = ["ContextEngine", "ContextFact", "AssembledContext"]
