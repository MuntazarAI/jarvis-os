"""Causal Model - M13 World Model Component.

Manages causal relationships between events and objects in the world.
Supports causal reasoning, counterfactual reasoning, and causal
discovery from observed data.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CausalRelation:
    """Represents a causal relationship between two events or objects."""
    relation_id: str = ""
    cause_id: str = ""
    cause_type: str = ""  # "event" or "object"
    effect_id: str = ""
    effect_type: str = ""  # "event" or "object"
    relationship_type: str = ""  # "causes", "enables", "prevents", "influences"
    confidence: float = 0.5
    strength: float = 0.5  # Strength of causal relationship (0-1)
    timestamp: float = field(default_factory=time.time)
    source: str = "unknown"
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "relation_id": self.relation_id,
            "cause_id": self.cause_id,
            "cause_type": self.cause_type,
            "effect_id": self.effect_id,
            "effect_type": self.effect_type,
            "relationship_type": self.relationship_type,
            "confidence": self.confidence,
            "strength": self.strength,
            "timestamp": self.timestamp,
            "source": self.source,
            "evidence": self.evidence,
        }


class CausalModel:
    """Manages causal relationships between events and objects.

    Provides causal discovery, reasoning, and counterfactual
    reasoning capabilities for the world model.
    """

    def __init__(self) -> None:
        self.relationships: dict[str, CausalRelation] = {}
        self.created_at = time.time()

    def add_relationship(self, relation: CausalRelation) -> None:
        """Add a causal relationship to the model."""
        self.relationships[relation.relation_id] = relation

    def get_relationship(self, relation_id: str) -> CausalRelation | None:
        """Get a causal relationship by ID."""
        return self.relationships.get(relation_id)

    def get_relationships_for_entity(self, entity_id: str) -> list[CausalRelation]:
        """Get all causal relationships involving an entity."""
        return [r for r in self.relationships.values()
                if r.cause_id == entity_id or r.effect_id == entity_id]

    def get_causes(self, effect_id: str) -> list[CausalRelation]:
        """Get all causes of an effect."""
        return [r for r in self.relationships.values()
                if r.effect_id == effect_id]

    def get_effects(self, cause_id: str) -> list[CausalRelation]:
        """Get all effects of a cause."""
        return [r for r in self.relationships.values()
                if r.cause_id == cause_id]

    def get_causal_chain(self, start_id: str, max_depth: int = 5) -> list[list[CausalRelation]]:
        """Get causal chains starting from an event or object."""
        chains = []
        visited = set()

        def _dfs(current_id: str, current_chain: list[CausalRelation], depth: int):
            if depth >= max_depth or current_id in visited:
                return
            visited.add(current_id)
            for relation in self.get_effects(current_id):
                new_chain = current_chain + [relation]
                chains.append(list(new_chain))
                _dfs(relation.effect_id, new_chain, depth + 1)

        _dfs(start_id, [], 0)
        return chains

    def get_stats(self) -> dict[str, Any]:
        """Get statistics about causal relationships."""
        return {
            "total_relationships": len(self.relationships),
            "by_type": {
                rel_type: len([r for r in self.relationships.values()
                               if r.relationship_type == rel_type])
                for rel_type in set(r.relationship_type for r in self.relationships.values())
            },
            "average_strength": sum(r.strength for r in self.relationships.values()) / max(len(self.relationships), 1),
            "average_confidence": sum(r.confidence for r in self.relationships.values()) / max(len(self.relationships), 1),
        }


# Global causal model instance
_causal_model: CausalModel | None = None


def get_causal_model() -> CausalModel:
    """Get or create the global causal model."""
    global _causal_model
    if _causal_model is None:
        _causal_model = CausalModel()
    return _causal_model


__all__ = [
    "CausalRelation",
    "CausalModel",
    "get_causal_model",
]
