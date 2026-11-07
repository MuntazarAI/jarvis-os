"""Temporal Knowledge - M29.

Temporal knowledge base built on Memory Palace and World Model.
Provides:
- Temporal databases with valid_from/valid_until windows
- Entity tracking across time (state changes)
- Contradiction detection between temporal claims
- Time-aware queries (what was true at time T)
- Temporal reasoning (before/after/during relationships)
- Memory consolidation for temporal data
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any

from ..memory.palace import MemoryPalace, Memory, cosine, tokenize
from ..memory.persistent import PersistentMemory, MemorySearchResult


@dataclass
class TemporalFact:
    """A fact with temporal validity."""
    fact_id: str
    entity: str
    attribute: str
    value: str
    valid_from: float
    valid_until: float | None
    confidence: float
    source: str
    provenance: str = "observed"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "entity": self.entity,
            "attribute": self.attribute,
            "value": self.value,
            "valid_from": self.valid_from,
            "valid_until": self.valid_until,
            "confidence": self.confidence,
            "source": self.source,
            "provenance": self.provenance,
            "metadata": self.metadata,
        }

    def is_valid_at(self, timestamp: float) -> bool:
        """Check if this fact was valid at the given timestamp."""
        if self.valid_from > timestamp:
            return False
        if self.valid_until is not None and timestamp > self.valid_until:
            return False
        return True

    def overlaps(self, other: "TemporalFact") -> bool:
        """Check if two facts overlap in time."""
        a_start = self.valid_from
        a_end = self.valid_until or float("inf")
        b_start = other.valid_from
        b_end = other.valid_until or float("inf")
        return a_start <= b_end and b_start <= a_end


@dataclass
class TemporalContradiction:
    """A detected contradiction between temporal facts."""
    contradiction_id: str
    entity: str
    attribute: str
    fact_1: TemporalFact
    fact_2: TemporalFact
    overlap_start: float
    overlap_end: float
    confidence: float
    resolution: str | None = None  # "fact_1_wins", "fact_2_wins", "merge", "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "contradiction_id": self.contradiction_id,
            "entity": self.entity,
            "attribute": self.attribute,
            "fact_1": self.fact_1.to_dict(),
            "fact_2": self.fact_2.to_dict(),
            "overlap_start": self.overlap_start,
            "overlap_end": self.overlap_end,
            "confidence": self.confidence,
            "resolution": self.resolution,
        }


@dataclass
class TemporalKnowledgeStats:
    total_facts: int
    by_entity: dict[str, int]
    contradictions: int
    time_range: dict[str, float]  # earliest, latest
    created_at: float


class TemporalKnowledge:
    """Temporal knowledge base.

    Stores facts with temporal validity windows and provides:
    - Time-aware queries (what was true at time T)
    - Entity state tracking across time
    - Contradiction detection between overlapping facts
    - Temporal reasoning (before/after/during)
    - Integration with PersistentMemory (M28)
    """

    def __init__(
        self,
        persistent_memory: PersistentMemory | None = None,
        palace: MemoryPalace | None = None,
    ):
        self.pm = persistent_memory or PersistentMemory(palace=palace)
        self.palace = palace or self.pm.palace

        # Fact store: fact_id -> TemporalFact
        self.facts: dict[str, TemporalFact] = {}

        # Entity index: entity -> list of fact_ids
        self.entity_index: dict[str, list[str]] = {}

        # Attribute index: (entity, attribute) -> list of fact_ids
        self.attribute_index: dict[tuple[str, str], list[str]] = {}

        # Statistics
        self.stats = {
            "facts_added": 0,
            "contradictions_detected": 0,
            "temporal_queries": 0,
        }
        self.created_at = time.time()

    def add_fact(
        self,
        entity: str,
        attribute: str,
        value: str,
        valid_from: float,
        valid_until: float | None = None,
        confidence: float = 0.6,
        source: str = "",
        provenance: str = "observed",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Add a temporal fact.

        Args:
            entity: Entity the fact is about
            attribute: Attribute being described
            value: Attribute value
            valid_from: Start of validity window
            valid_until: End of validity window (None = ongoing)
            confidence: Confidence score (0-1)
            source: Source of the fact
            provenance: Provenance (told, inferred, observed, hypothesis, system)
            metadata: Additional metadata

        Returns:
            Fact ID
        """
        import hashlib
        fact_id = f"tf-{hashlib.sha256(f'{entity}|{attribute}|{value}|{valid_from}'.encode()).hexdigest()[:12]}"

        fact = TemporalFact(
            fact_id=fact_id,
            entity=entity,
            attribute=attribute,
            value=value,
            valid_from=valid_from,
            valid_until=valid_until,
            confidence=confidence,
            source=source,
            provenance=provenance,
            metadata=metadata or {},
        )

        self.facts[fact_id] = fact

        # Index by entity
        self.entity_index.setdefault(entity, []).append(fact_id)

        # Index by (entity, attribute)
        self.attribute_index.setdefault((entity, attribute), []).append(fact_id)

        self.stats["facts_added"] += 1

        # Also store in persistent memory
        self.pm.store(
            content=f"{entity} {attribute} is {value} (valid from {valid_from})",
            tier="semantic",
            room="Temporal Knowledge",
            kind="temporal_fact",
            source=source,
            origin=provenance,
            confidence=confidence,
            related_entities=[entity],
            valid_from=valid_from,
            valid_until=valid_until,
            metadata={"fact_id": fact_id, "attribute": attribute, "value": value},
        )

        return fact_id

    def get_fact(self, fact_id: str) -> TemporalFact | None:
        """Get a fact by ID."""
        return self.facts.get(fact_id)

    def query_at_time(
        self,
        timestamp: float,
        entity: str | None = None,
        attribute: str | None = None,
    ) -> list[TemporalFact]:
        """Get all facts valid at a given timestamp.

        Args:
            timestamp: Time to query
            entity: Optional entity filter
            attribute: Optional attribute filter

        Returns:
            List of TemporalFact valid at timestamp
        """
        self.stats["temporal_queries"] += 1

        results = []

        if entity and attribute:
            fact_ids = self.attribute_index.get((entity, attribute), [])
        elif entity:
            fact_ids = self.entity_index.get(entity, [])
        else:
            fact_ids = list(self.facts.keys())

        for fid in fact_ids:
            fact = self.facts[fid]
            if fact.is_valid_at(timestamp):
                results.append(fact)

        return results

    def get_entity_state(
        self,
        entity: str,
        timestamp: float,
    ) -> dict[str, str]:
        """Get the complete state of an entity at a given timestamp.

        Returns a dict of attribute -> value for all attributes
        that have a valid fact at the timestamp. If multiple facts
        exist for the same attribute at the timestamp, the highest
        confidence one wins.
        """
        facts = self.query_at_time(timestamp, entity=entity)
        state: dict[str, str] = {}
        state_conf: dict[str, float] = {}

        for fact in facts:
            if fact.attribute not in state_conf or fact.confidence > state_conf[fact.attribute]:
                state[fact.attribute] = fact.value
                state_conf[fact.attribute] = fact.confidence

        return state

    def detect_contradictions(
        self,
        entity: str | None = None,
    ) -> list[TemporalContradiction]:
        """Detect contradictions between overlapping facts.

        A contradiction occurs when two facts about the same entity
        and attribute have different values and overlap in time.

        Args:
            entity: Optional entity filter

        Returns:
            List of TemporalContradiction
        """
        contradictions = []

        fact_ids = (
            self.entity_index.get(entity, [])
            if entity else list(self.facts.keys())
        )

        # Group by (entity, attribute)
        attr_groups: dict[tuple[str, str], list[str]] = {}
        for fid in fact_ids:
            fact = self.facts[fid]
            attr_groups.setdefault((fact.entity, fact.attribute), []).append(fid)

        for (ent, attr), ids in attr_groups.items():
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    f1 = self.facts[ids[i]]
                    f2 = self.facts[ids[j]]

                    if f1.value == f2.value:
                        continue  # Same value, no contradiction

                    if not f1.overlaps(f2):
                        continue  # No time overlap, no contradiction

                    # Calculate overlap window
                    overlap_start = max(f1.valid_from, f2.valid_from)
                    overlap_end = min(
                        f1.valid_until or float("inf"),
                        f2.valid_until or float("inf"),
                    )

                    conf = min(f1.confidence, f2.confidence)

                    contradiction = TemporalContradiction(
                        contradiction_id=f"tc-{len(contradictions):06d}",
                        entity=ent,
                        attribute=attr,
                        fact_1=f1,
                        fact_2=f2,
                        overlap_start=overlap_start,
                        overlap_end=overlap_end,
                        confidence=conf,
                    )
                    contradictions.append(contradiction)

        self.stats["contradictions_detected"] += len(contradictions)
        return contradictions

    def resolve_contradiction(
        self,
        contradiction_id: str,
        resolution: str,  # "fact_1_wins", "fact_2_wins", "merge"
    ) -> bool:
        """Resolve a detected contradiction.

        Args:
            contradiction_id: ID of the contradiction
            resolution: How to resolve

        Returns:
            True if resolved
        """
        # Find the contradiction
        contra = None
        for cid, fact_id in self.entity_index.items():
            pass  # Contradictions aren't stored separately; re-detect

        # Re-detect and find the matching one
        all_contras = self.detect_contradictions()
        for c in all_contras:
            if c.contradiction_id == contradiction_id:
                contra = c
                break

        if not contra:
            return False

        if resolution == "fact_1_wins":
            # Mark fact_2 as less confident or invalidate
            contra.fact_2.valid_until = contra.overlap_start
        elif resolution == "fact_2_wins":
            contra.fact_1.valid_until = contra.overlap_start
        elif resolution == "merge":
            # Keep both but mark as conflicting
            pass

        return True

    def get_timeline(
        self,
        entity: str,
        attribute: str | None = None,
        start_time: float | None = None,
        end_time: float | None = None,
    ) -> list[TemporalFact]:
        """Get a timeline of facts for an entity.

        Args:
            entity: Entity to query
            attribute: Optional attribute filter
            start_time: Start of query window
            end_time: End of query window

        Returns:
            List of TemporalFact sorted by valid_from
        """
        fact_ids = self.entity_index.get(entity, [])
        results = []

        for fid in fact_ids:
            fact = self.facts[fid]
            if attribute and fact.attribute != attribute:
                continue
            if start_time is not None and fact.valid_from < start_time:
                continue
            if end_time is not None and fact.valid_from > end_time:
                continue
            results.append(fact)

        results.sort(key=lambda f: f.valid_from)
        return results

    def get_stats(self) -> TemporalKnowledgeStats:
        """Get temporal knowledge statistics."""
        all_timestamps = []
        for fact in self.facts.values():
            all_timestamps.append(fact.valid_from)
            if fact.valid_until:
                all_timestamps.append(fact.valid_until)

        by_entity: dict[str, int] = {}
        for fact in self.facts.values():
            by_entity[fact.entity] = by_entity.get(fact.entity, 0) + 1

        return TemporalKnowledgeStats(
            total_facts=len(self.facts),
            by_entity=by_entity,
            contradictions=self.stats["contradictions_detected"],
            time_range={
                "earliest": min(all_timestamps) if all_timestamps else 0,
                "latest": max(all_timestamps) if all_timestamps else 0,
            },
            created_at=self.created_at,
        )


# Global instance
_temporal_knowledge: TemporalKnowledge | None = None


def get_temporal_knowledge(
    persistent_memory: PersistentMemory | None = None,
    palace: MemoryPalace | None = None,
) -> TemporalKnowledge:
    """Get or create the global TemporalKnowledge instance."""
    global _temporal_knowledge
    if _temporal_knowledge is None:
        _temporal_knowledge = TemporalKnowledge(
            persistent_memory=persistent_memory,
            palace=palace,
        )
    return _temporal_knowledge


__all__ = [
    "TemporalFact",
    "TemporalContradiction",
    "TemporalKnowledge",
    "TemporalKnowledgeStats",
    "get_temporal_knowledge",
]
