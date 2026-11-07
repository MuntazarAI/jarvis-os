"""Global Knowledge Graph (M8).

Extends the existing Memory Palace (jarvis/memory/palace.py) and
World Model (jarvis/world/model.py) with a persistent knowledge graph
of concepts, software, organizations, research papers, vulnerabilities,
publications, datasets, websites, and events.

Stores:
- Source URL, retrieval timestamp, publication date
- Content hash, extracted information, evidence, confidence
- Verification status, relationships, historical changes

Lightweight file-based graph store (no external infrastructure required).
Builds on jarvis/worldintel/ (claims, sources, evidence).
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..core.logging import get_module_logger
from ..core.types import now

log = get_module_logger(__name__)


@dataclass
class Entity:
    """A node in the knowledge graph."""
    entity_id: str
    name: str
    type: str  # concept | organization | paper | vulnerability | dataset | website | event | software | person
    description: str = ""
    properties: dict[str, Any] = field(default_factory=dict)
    source_url: str = ""
    retrieval_timestamp: float = field(default_factory=now)
    publication_date: float | None = None
    content_hash: str = ""
    confidence: float = 0.5
    verification_status: str = "unverified"  # unverified | verified | disputed | refuted
    created_at: float = field(default_factory=now)
    updated_at: float = field(default_factory=now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Entity":
        return cls(**data)


@dataclass
class Relationship:
    """An edge in the knowledge graph."""
    relationship_id: str
    source_entity_id: str
    target_entity_id: str
    relation_type: str  # mentions | cites | exploits | fixes | depends_on | located_in | created_by | part_of
    properties: dict[str, Any] = field(default_factory=dict)
    source_url: str = ""
    retrieval_timestamp: float = field(default_factory=now)
    confidence: float = 0.5
    created_at: float = field(default_factory=now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Relationship":
        return cls(**data)


@dataclass
class EvidenceRecord:
    """Evidence supporting a claim or entity."""
    evidence_id: str
    entity_id: str | None = None
    relationship_id: str | None = None
    source_url: str = ""
    retrieved_at: float = field(default_factory=now)
    content_hash: str = ""
    extracted_text: str = ""
    confidence: float = 0.5
    verification_status: str = "unverified"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class KnowledgeGraphStore:
    """Lightweight, file-based knowledge graph store.

    Entities and relationships are persisted as JSON. No external
    database required — suitable for the i3-1215U / 8GB RAM target.
    """

    def __init__(self, home: str | Path | None = None) -> None:
        self.home = Path(home) if home else Path.home() / ".jarvis-os"
        self.entities_file = self.home / "knowledge_graph_entities.json"
        self.relationships_file = self.home / "knowledge_graph_relationships.json"
        self.evidence_file = self.home / "knowledge_graph_evidence.json"
        self._entities: dict[str, Entity] = {}
        self._relationships: dict[str, Relationship] = {}
        self._evidence: dict[str, EvidenceRecord] = {}
        self._index_by_name: dict[str, str] = {}  # lowercase name -> entity_id
        self._index_by_type: dict[str, set[str]] = {}  # type -> set of entity_ids
        self._adjacency: dict[str, list[str]] = {}  # entity_id -> list of relationship_ids
        self.load()

    # -- persistence -----------------------------------------------------

    def load(self) -> None:
        """Load graph from disk."""
        self.home.mkdir(parents=True, exist_ok=True)
        for path, target, cls in (
            (self.entities_file, self._entities, Entity),
            (self.relationships_file, self._relationships, Relationship),
            (self.evidence_file, self._evidence, EvidenceRecord),
        ):
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    for item in data:
                        obj = cls.from_dict(item)
                        target[obj.entity_id if hasattr(obj, "entity_id") else obj.evidence_id] = obj
                except (json.JSONDecodeError, OSError) as exc:
                    log.warning("Failed to load graph data", path=str(path), error=str(exc)[:120])
        self._rebuild_indexes()

    def save(self) -> None:
        """Save graph to disk atomically."""
        self.home.mkdir(parents=True, exist_ok=True)
        for path, collection in (
            (self.entities_file, self._entities),
            (self.relationships_file, self._relationships),
            (self.evidence_file, self._evidence),
        ):
            try:
                data = [obj.to_dict() for obj in collection.values()]
                tmp = path.with_suffix(".tmp")
                tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
                tmp.replace(path)
            except OSError as exc:
                log.warning("Failed to save graph data", path=str(path), error=str(exc)[:120])

    def _rebuild_indexes(self) -> None:
        """Rebuild name/type/adjacency indexes from loaded data."""
        self._index_by_name.clear()
        self._index_by_type.clear()
        self._adjacency.clear()
        for entity in self._entities.values():
            self._index_by_name[entity.name.lower()] = entity.entity_id
            self._index_by_type.setdefault(entity.type, set()).add(entity.entity_id)
        for rel in self._relationships.values():
            self._adjacency.setdefault(rel.source_entity_id, []).append(rel.relationship_id)
            self._adjacency.setdefault(rel.target_entity_id, []).append(rel.relationship_id)

    # -- entities --------------------------------------------------------

    def add_entity(
        self,
        name: str,
        type: str,
        description: str = "",
        properties: dict[str, Any] | None = None,
        source_url: str = "",
        publication_date: float | None = None,
        content_hash: str = "",
        confidence: float = 0.5,
        verification_status: str = "unverified",
        entity_id: str | None = None,
    ) -> Entity:
        """Add or update an entity. Returns the entity."""
        eid = entity_id or f"ent-{uuid.uuid4().hex[:12]}"
        now_ts = now()

        if eid in self._entities:
            # Update existing
            ent = self._entities[eid]
            ent.name = name
            ent.description = description
            ent.properties = properties or {}
            ent.source_url = source_url
            ent.retrieval_timestamp = now_ts
            if publication_date is not None:
                ent.publication_date = publication_date
            if content_hash:
                ent.content_hash = content_hash
            ent.confidence = confidence
            ent.verification_status = verification_status
            ent.updated_at = now_ts
        else:
            ent = Entity(
                entity_id=eid, name=name, type=type,
                description=description, properties=properties or {},
                source_url=source_url,
                publication_date=publication_date,
                content_hash=content_hash,
                confidence=confidence,
                verification_status=verification_status,
            )
            self._entities[eid] = ent
            self._index_by_name[name.lower()] = eid
            self._index_by_type.setdefault(type, set()).add(eid)

        self.save()
        return ent

    def get_entity(self, entity_id: str) -> Entity | None:
        return self._entities.get(entity_id)

    def find_entity_by_name(self, name: str) -> Entity | None:
        return self._entities.get(self._index_by_name.get(name.lower(), ""))

    def entities_by_type(self, type: str) -> list[Entity]:
        return [self._entities[eid] for eid in self._index_by_type.get(type, set())]

    def list_entities(self, limit: int = 100) -> list[Entity]:
        return list(self._entities.values())[:limit]

    # -- relationships ---------------------------------------------------

    def add_relationship(
        self,
        source_entity_id: str,
        target_entity_id: str,
        relation_type: str,
        properties: dict[str, Any] | None = None,
        source_url: str = "",
        confidence: float = 0.5,
        relationship_id: str | None = None,
    ) -> Relationship:
        """Add a relationship between two entities."""
        rid = relationship_id or f"rel-{uuid.uuid4().hex[:12]}"
        rel = Relationship(
            relationship_id=rid,
            source_entity_id=source_entity_id,
            target_entity_id=target_entity_id,
            relation_type=relation_type,
            properties=properties or {},
            source_url=source_url,
            confidence=confidence,
        )
        self._relationships[rid] = rel
        self._adjacency.setdefault(source_entity_id, []).append(rid)
        self._adjacency.setdefault(target_entity_id, []).append(rid)
        self.save()
        return rel

    def get_relationship(self, relationship_id: str) -> Relationship | None:
        return self._relationships.get(relationship_id)

    def relationships_for_entity(self, entity_id: str) -> list[Relationship]:
        """Get all relationships involving an entity (incoming + outgoing)."""
        rel_ids = self._adjacency.get(entity_id, [])
        return [self._relationships[rid] for rid in rel_ids if rid in self._relationships]

    def find_relationships(
        self,
        source_entity_id: str | None = None,
        target_entity_id: str | None = None,
        relation_type: str | None = None,
    ) -> list[Relationship]:
        """Find relationships by source, target, and/or type."""
        results = []
        for rel in self._relationships.values():
            if source_entity_id is not None and rel.source_entity_id != source_entity_id:
                continue
            if target_entity_id is not None and rel.target_entity_id != target_entity_id:
                continue
            if relation_type is not None and rel.relation_type != relation_type:
                continue
            results.append(rel)
        return results

    # -- evidence --------------------------------------------------------

    def add_evidence(
        self,
        entity_id: str | None = None,
        relationship_id: str | None = None,
        source_url: str = "",
        extracted_text: str = "",
        confidence: float = 0.5,
        verification_status: str = "unverified",
        evidence_id: str | None = None,
    ) -> EvidenceRecord:
        """Add an evidence record."""
        eid = evidence_id or f"ev-{uuid.uuid4().hex[:12]}"
        content_hash = hashlib.sha256(extracted_text.encode("utf-8")).hexdigest()[:16] if extracted_text else ""
        ev = EvidenceRecord(
            evidence_id=eid, entity_id=entity_id,
            relationship_id=relationship_id,
            source_url=source_url,
            content_hash=content_hash,
            extracted_text=extracted_text[:5000],
            confidence=confidence,
            verification_status=verification_status,
        )
        self._evidence[eid] = ev
        self.save()
        return ev

    def evidence_for_entity(self, entity_id: str) -> list[EvidenceRecord]:
        return [ev for ev in self._evidence.values() if ev.entity_id == entity_id]

    # -- queries ---------------------------------------------------------

    def search_entities(self, query: str, limit: int = 20) -> list[Entity]:
        """Search entities by name or description (case-insensitive substring)."""
        q = query.lower()
        results = []
        for ent in self._entities.values():
            if q in ent.name.lower() or q in ent.description.lower():
                results.append(ent)
                if len(results) >= limit:
                    break
        return results

    def get_neighborhood(
        self,
        entity_id: str,
        max_hops: int = 1,
    ) -> dict[str, Any]:
        """Get the neighborhood of an entity (entities + relationships within max_hops)."""
        if entity_id not in self._entities:
            return {"entity": None, "neighbors": [], "relationships": []}

        entity = self._entities[entity_id]
        visited = {entity_id}
        current_level = {entity_id}
        neighbors: dict[str, Entity] = {}
        rels: list[Relationship] = []

        for hop in range(max_hops):
            next_level: set[str] = set()
            for eid in current_level:
                for rel in self.relationships_for_entity(eid):
                    rels.append(rel)
                    for other_id in (rel.source_entity_id, rel.target_entity_id):
                        if other_id not in visited and other_id in self._entities:
                            visited.add(other_id)
                            next_level.add(other_id)
                            neighbors[other_id] = self._entities[other_id]
            current_level = next_level
            if not current_level:
                break

        return {
            "entity": entity,
            "neighbors": list(neighbors.values()),
            "relationships": rels,
        }

    def stats(self) -> dict[str, Any]:
        return {
            "entities": len(self._entities),
            "relationships": len(self._relationships),
            "evidence_records": len(self._evidence),
            "types": {t: len(ids) for t, ids in self._index_by_type.items()},
        }


__all__ = [
    "Entity",
    "Relationship",
    "EvidenceRecord",
    "KnowledgeGraphStore",
]
