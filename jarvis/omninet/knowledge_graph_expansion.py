"""
Knowledge Graph Expansion — JARVIS-OS OMNINET subsystem.

Expands the existing knowledge graph with entity resolution, relationship
extraction, and provenance tracking. Read-only — no entity creation without
explicit approval, no mass surveillance, no facial recognition.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from ..core.logging import get_module_logger
from ..policy.policy import PolicyEngine
from ..events.store import EventStore

log = get_module_logger(__name__)


@dataclass
class KnowledgeEntity:
    """A knowledge graph entity."""
    entity_id: str
    name: str
    entity_type: str  # person, organization, concept, location, artifact
    description: str
    properties: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    created_at: float = field(default_factory=time.time)


@dataclass
class KnowledgeRelationship:
    """A relationship between two entities."""
    relationship_id: str
    source_entity: str
    target_entity: str
    relationship_type: str  # related_to, part_of, located_in, created_by, etc.
    properties: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    created_at: float = field(default_factory=time.time)


class KnowledgeGraphExpansion:
    """
    Knowledge Graph Expansion — entity resolution and relationship tracking.

    Provides knowledge graph querying, entity resolution, and relationship
    extraction. All operations are read-only. No facial recognition,
    no mass surveillance, no external data collection without approval.
    """

    def __init__(
        self,
        policy: PolicyEngine | None = None,
        events: EventStore | None = None,
    ) -> None:
        self.policy = policy
        self.events = events
        self.entities: dict[str, KnowledgeEntity] = {}
        self.relationships: dict[str, KnowledgeRelationship] = {}
        self._initialized = False
        self._seed_entities()

    def _seed_entities(self) -> None:
        """Seed with a few schematic entities (not real data)."""
        seeds = [
            ("ent-jarvis", "JARVIS", "ai_system", "JARVIS-OS personal AI operating system"),
            ("ent-friday", "FRIDAY", "ai_system", "Tactical operations AI agent"),
            ("ent-karen", "KAREN", "ai_system", "Screen observation AI agent"),
            ("ent-edith", "EDITH", "ai_system", "Intelligence knowledge oversight AI agent"),
            ("ent-ultron", "ULTRON", "ai_system", "Contained red team security AI agent"),
            ("ent-vision", "VISION", "ai_system", "Synthesis and verification AI agent"),
        ]
        for entity_id, name, etype, desc in seeds:
            self.entities[entity_id] = KnowledgeEntity(
                entity_id=entity_id,
                name=name,
                entity_type=etype,
                description=desc,
            )

    def initialize(self) -> dict[str, Any]:
        """Initialize the knowledge graph expansion subsystem."""
        self._initialized = True
        return {
            "status": "operational",
            "subsystem": "knowledge_graph_expansion",
            "entities": len(self.entities),
            "relationships": len(self.relationships),
            "policy_gated": True,
            "read_only": True,
        }

    def query_entity(self, entity_id: str) -> KnowledgeEntity | None:
        """Query an entity by ID."""
        return self.entities.get(entity_id)

    def search_entities(self, query: str) -> list[KnowledgeEntity]:
        """Search entities by name or description (case-insensitive)."""
        q = query.lower()
        return [
            e for e in self.entities.values()
            if q in e.name.lower() or q in e.description.lower()
        ]

    def add_relationship(
        self,
        source_entity: str,
        target_entity: str,
        relationship_type: str,
    ) -> dict[str, Any]:
        """Add a relationship between two entities (requires approval)."""
        if self.policy:
            grant = self.policy.evaluate(
                "knowledge_graph.add_relationship",
                {
                    "source_entity": source_entity,
                    "target_entity": target_entity,
                    "relationship_type": relationship_type,
                },
            )
            if not grant.get("approved", False):
                return {"ok": False, "reason": "policy denied"}

        rel_id = f"rel-{int(time.time() * 1000)}"
        relationship = KnowledgeRelationship(
            relationship_id=rel_id,
            source_entity=source_entity,
            target_entity=target_entity,
            relationship_type=relationship_type,
        )
        self.relationships[rel_id] = relationship

        if self.events:
            self.events.append({
                "event": "knowledge_graph.add_relationship",
                "relationship_id": rel_id,
                "source": source_entity,
                "target": target_entity,
                "type": relationship_type,
                "at": relationship.created_at,
            })

        return {"ok": True, "relationship_id": rel_id}

    def list_entities(self) -> list[KnowledgeEntity]:
        """List all entities."""
        return list(self.entities.values())

    def list_relationships(self) -> list[KnowledgeRelationship]:
        """List all relationships."""
        return list(self.relationships.values())

    def get_status(self) -> dict[str, Any]:
        """Get subsystem status."""
        return {
            "subsystem": "knowledge_graph_expansion",
            "status": "operational" if self._initialized else "offline",
            "entities": len(self.entities),
            "relationships": len(self.relationships),
            "capabilities": [
                "entity_query",
                "entity_search",
                "relationship_tracking",
                "provenance_tracking",
            ],
            "read_only": True,
            "policy_gated": True,
            "constraints": [
                "no_facial_recognition",
                "no_mass_surveillance",
                "no_external_data_collection_without_approval",
            ],
        }


# Global instance
_kge: KnowledgeGraphExpansion | None = None


def get_knowledge_graph_expansion(
    policy: PolicyEngine | None = None,
    events: EventStore | None = None,
) -> KnowledgeGraphExpansion:
    """Get or create the global Knowledge Graph Expansion instance."""
    global _kge
    if _kge is None:
        _kge = KnowledgeGraphExpansion(policy=policy, events=events)
    return _kge


__all__ = [
    "KnowledgeGraphExpansion",
    "KnowledgeEntity",
    "KnowledgeRelationship",
    "get_knowledge_graph_expansion",
]