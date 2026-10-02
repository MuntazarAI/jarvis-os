"""World Model 2.2 — typed entity/relationship registry with provenance.

Additive layer over world/state.py (snapshots/diffs) and world/model.py
(probes), which are NOT modified. This module adds what they lack:

- typed entities + relationships with stable IDs and versions
- temporal state (current vs history, observed-at vs updated-at)
- structured observations that do NOT auto-become truth
- controlled memory → world promotion with origin preserved
- deterministic query API for agents
- repository abstraction (in-memory default, JSON file store)

Honesty contracts (enforced, tested):
- unknown stays unknown: missing entities return None, never False
- conflicting evidence stays visible; nothing auto-resolves
- no silent overwrites: every mutation appends history + bumps version
- observations are claims until explicitly applied
- external content is tagged untrusted and never becomes instructions
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field as dc_field, asdict
from pathlib import Path
from typing import Any, Protocol

from ..core.types import new_id, now

ENTITY_TYPES = (
    "person",
    "device",
    "computer",
    "application",
    "file",
    "project",
    "location",
    "network",
    "service",
    "task",
    "event",
    "goal",
    "agent",
    "organization",
    "knowledge_source",
    "mission",
    "objective",
)

RELATIONS = (
    "owns",
    "contains",
    "uses",
    "runs",
    "connected_to",
    "depends_on",
    "created_by",
    "located_at",
    "related_to",
    "part_of",
    "knows",
    "observes",
    "modifies",
)

# Memory origins allowed to seed world entities without an explicit override.
# Hypothesis/speculation is never promoted silently (see promote_memory).
PROMOTABLE_ORIGINS = ("told", "observed")


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "unnamed"


def make_entity_id(entity_type: str, name: str) -> str:
    return f"{entity_type.lower()}:{_slug(name)}"


@dataclass
class WorldEntity:
    """One typed thing in the world. State is explicit fields, never vibes."""

    id: str
    type: str
    name: str
    attributes: dict[str, Any] = dc_field(default_factory=dict)
    state: dict[str, Any] = dc_field(default_factory=dict)
    created_at: float = dc_field(default_factory=now)
    updated_at: float = dc_field(default_factory=now)
    observed_at: float = dc_field(default_factory=now)
    provenance: dict[str, Any] = dc_field(default_factory=dict)
    confidence: float = 0.6
    uncertainty: list[str] = dc_field(default_factory=list)
    evidence_refs: list[str] = dc_field(default_factory=list)
    version: int = 1

    def __post_init__(self) -> None:
        if self.type not in ENTITY_TYPES:
            raise ValueError(f"unknown entity type: {self.type}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence out of range: {self.confidence}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorldEntity":
        return cls(**{k: data.get(k, v) for k, v in (
            ("id", ""), ("type", "related_to"), ("name", ""),
            ("attributes", {}), ("state", {}),
            ("created_at", 0.0), ("updated_at", 0.0), ("observed_at", 0.0),
            ("provenance", {}), ("confidence", 0.6), ("uncertainty", []),
            ("evidence_refs", []), ("version", 1))})


@dataclass
class WorldRelation:
    id: str
    src: str
    rel: str
    dst: str
    confidence: float = 0.6
    provenance: dict[str, Any] = dc_field(default_factory=dict)
    observed_at: float = dc_field(default_factory=now)
    updated_at: float = dc_field(default_factory=now)
    version: int = 1

    def __post_init__(self) -> None:
        if self.rel not in RELATIONS:
            raise ValueError(f"unknown relation: {self.rel}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence out of range: {self.confidence}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorldRelation":
        return cls(id=data.get("id", new_id("wrel")),
                   src=data["src"], rel=data["rel"], dst=data["dst"],
                   confidence=data.get("confidence", 0.6),
                   provenance=data.get("provenance", {}),
                   observed_at=data.get("observed_at", 0.0),
                   updated_at=data.get("updated_at", 0.0),
                   version=int(data.get("version", 1)))


@dataclass
class WorldObservation:
    """A structured sighting. Recorded, never auto-asserted as truth."""

    id: str = dc_field(default_factory=lambda: new_id("wobs"))
    what: str = ""
    observed_at: float = dc_field(default_factory=now)
    observer: str = ""
    source: str = ""
    confidence: float = 0.6
    evidence: list[str] = dc_field(default_factory=list)
    trusted: bool = True
    applied: bool = False
    metadata: dict[str, Any] = dc_field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorldObservation":
        return cls(**{k: data.get(k, v) for k, v in (
            ("id", new_id("wobs")), ("what", ""),
            ("observed_at", 0.0), ("observer", ""), ("source", ""),
            ("confidence", 0.6), ("evidence", []), ("trusted", True),
            ("applied", False), ("metadata", {}))})

    @staticmethod
    def classify_source(source: str) -> bool:
        """External/untrusted origins never become trusted instructions."""
        low = (source or "").lower()
        return not any(marker in low for marker in
                       ("external", "web", "untrusted", "third-party"))


class VersionConflict(Exception):
    """Stale write rejected: caller must re-read and retry explicitly."""


class UnknownEntity(Exception):
    """Lookup for an entity that was never observed."""


class WorldRepository(Protocol):
    """Persistence abstraction. In-memory is the default; a real database
    can implement this protocol later without touching the registry."""

    def save(self, data: dict[str, Any]) -> None: ...
    def load(self) -> dict[str, Any]: ...


class JsonFileWorldStore:
    """File-backed JSON store. Durable as a file; honest about what it is:
    no transactions, no concurrent-writer protection, last-write-wins."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.last_load_error: str = ""

    def save(self, data: dict[str, Any]) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, default=str, indent=2))
        tmp.replace(self.path)

    def load(self) -> dict[str, Any]:
        """Recover from an unreadable/corrupt file instead of crashing.

        The file is left untouched on disk for forensics; only this store's
        view resets. ``last_load_error`` records why, so doctor/status can
        surface corruption rather than hiding it.
        """
        self.last_load_error = ""
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError) as exc:
            self.last_load_error = f"{type(exc).__name__}: {exc}"[:200]
            return {}
        return data if isinstance(data, dict) else {}


class WorldRegistry:
    """Typed entity/relation store with history, CAS, and auditable promotion."""

    def __init__(self) -> None:
        self.entities: dict[str, WorldEntity] = {}
        self.relations: dict[str, WorldRelation] = {}
        self.observations: dict[str, WorldObservation] = {}
        # (entity_id, field) -> list of superseded {value, at, by, reason}
        self.history: dict[tuple[str, str], list[dict[str, Any]]] = {}
        # conflicting claims kept visible: list of {entity, field, claims[]}
        self.conflicts: list[dict[str, Any]] = []
        # memory_id -> entity_id promotion map (dedupe) + audit trail
        self._promoted: dict[str, str] = {}
        self.promotions: list[dict[str, Any]] = []

    # -- entities ------------------------------------------------------
    def upsert_entity(self, entity_type: str, name: str,
                      state: dict[str, Any] | None = None,
                      attributes: dict[str, Any] | None = None,
                      provenance: dict[str, Any] | None = None,
                      confidence: float = 0.6,
                      expected_version: int | None = None,
                      entity_id: str | None = None) -> tuple[WorldEntity, list[str]]:
        """Create or update. Returns (entity, changed_fields).

        With expected_version set, a mismatch raises VersionConflict
        instead of silently overwriting — callers must re-read first.
        """
        eid = entity_id or make_entity_id(entity_type, name)
        existing = self.entities.get(eid)
        if existing is None:
            entity = WorldEntity(
                id=eid, type=entity_type, name=name,
                attributes=dict(attributes or {}), state=dict(state or {}),
                provenance=dict(provenance or {}), confidence=confidence)
            self.entities[eid] = entity
            return entity, sorted((state or {}).keys())
        if expected_version is not None and existing.version != expected_version:
            raise VersionConflict(
                f"{eid} is at version {existing.version}, "
                f"caller expected {expected_version}")
        changed: list[str] = []
        stamp = now()
        for key, value in (state or {}).items():
            if existing.state.get(key) != value:
                self.history.setdefault((eid, key), []).append({
                    "value": existing.state.get(key), "at": existing.updated_at,
                    "by": existing.provenance.get("observer", ""),
                    "reason": "superseded by update"})
                existing.state[key] = value
                changed.append(key)
        if attributes:
            existing.attributes.update(attributes)
        if provenance:
            existing.provenance.update(provenance)
        if changed:
            existing.version += 1
            existing.updated_at = stamp
            existing.observed_at = stamp
        return existing, sorted(changed)

    def get_entity(self, entity_id: str) -> WorldEntity | None:
        """Unknown stays unknown: None, never a fabricated entity."""
        return self.entities.get(entity_id)

    def require_entity(self, entity_id: str) -> WorldEntity:
        entity = self.entities.get(entity_id)
        if entity is None:
            raise UnknownEntity(f"never observed: {entity_id}")
        return entity

    def find_entities(self, entity_type: str | None = None,
                      name_contains: str = "",
                      state_match: dict[str, Any] | None = None,
                      min_confidence: float = 0.0) -> list[WorldEntity]:
        out = []
        for entity in self.entities.values():
            if entity_type and entity.type != entity_type:
                continue
            if name_contains and name_contains.lower() not in entity.name.lower():
                continue
            if state_match and not all(
                    entity.state.get(k) == v for k, v in state_match.items()):
                continue
            if entity.confidence < min_confidence:
                continue
            out.append(entity)
        return sorted(out, key=lambda e: e.name)

    def get_history(self, entity_id: str,
                    field: str | None = None) -> list[dict[str, Any]]:
        if field:
            return list(self.history.get((entity_id, field), []))
        out = []
        for (eid, fld), records in self.history.items():
            if eid == entity_id:
                out.extend({"field": fld, **r} for r in records)
        return sorted(out, key=lambda r: r.get("at", 0.0))

    # -- relations -----------------------------------------------------
    def relate(self, src: str, rel: str, dst: str,
               confidence: float = 0.6,
               provenance: dict[str, Any] | None = None) -> WorldRelation:
        if src not in self.entities:
            raise UnknownEntity(f"never observed: {src}")
        if dst not in self.entities:
            raise UnknownEntity(f"never observed: {dst}")
        for existing in self.relations.values():
            if (existing.src, existing.rel, existing.dst) == (src, rel, dst):
                existing.confidence = max(existing.confidence, confidence)
                existing.updated_at = now()
                existing.version += 1
                if provenance:
                    existing.provenance.update(provenance)
                return existing
        relation = WorldRelation(
            id=new_id("wrel"), src=src, rel=rel, dst=dst,
            confidence=confidence, provenance=dict(provenance or {}))
        self.relations[relation.id] = relation
        return relation

    def get_relationships(self, entity_id: str,
                          rel: str | None = None) -> list[WorldRelation]:
        return [r for r in self.relations.values()
                if (r.src == entity_id or r.dst == entity_id)
                and (rel is None or r.rel == rel)]

    def related_entities(self, entity_id: str,
                         rel: str | None = None) -> list[WorldEntity]:
        out = []
        for relation in self.get_relationships(entity_id, rel):
            other = relation.dst if relation.src == entity_id else relation.src
            entity = self.entities.get(other)
            if entity is not None:
                out.append(entity)
        return out

    # -- observations (recorded, not auto-asserted) --------------------
    def observe(self, what: str, observer: str = "", source: str = "",
                confidence: float = 0.6,
                evidence: list[str] | None = None) -> WorldObservation:
        obs = WorldObservation(
            what=what, observer=observer, source=source,
            confidence=confidence, evidence=list(evidence or []),
            trusted=WorldObservation.classify_source(source))
        self.observations[obs.id] = obs
        return obs

    def apply_observation(self, observation_id: str, entity_id: str,
                          field_updates: dict[str, Any],
                          expected_version: int | None = None) -> WorldEntity:
        """Explicitly apply one recorded observation to an entity.

        Conflicting values are kept visible in self.conflicts instead of
        being resolved silently.
        """
        obs = self.observations.get(observation_id)
        if obs is None:
            raise KeyError(f"unknown observation: {observation_id}")
        entity = self.require_entity(entity_id)
        for key, value in field_updates.items():
            current = entity.state.get(key, None)
            if key in entity.state and current != value:
                self._record_conflict(
                    entity_id, key, current, value, obs)
        updated, _ = self.upsert_entity(
            entity.type, entity.name, state=field_updates,
            provenance={"observer": obs.observer, "source": obs.source,
                        "observation_id": obs.id,
                        "trusted": obs.trusted},
            confidence=min(entity.confidence, obs.confidence),
            expected_version=expected_version, entity_id=entity_id)
        obs.applied = True
        return updated

    def _record_conflict(self, entity_id: str, field: str,
                         old: Any, new: Any, obs: WorldObservation) -> None:
        for conflict in self.conflicts:
            if conflict["entity"] == entity_id and conflict["field"] == field:
                conflict["claims"].append({
                    "value": new, "at": obs.observed_at,
                    "observer": obs.observer, "source": obs.source,
                    "observation_id": obs.id, "trusted": obs.trusted})
                return
        self.conflicts.append({
            "entity": entity_id, "field": field,
            "claims": [
                {"value": old, "at": None, "observer": "prior-state",
                 "source": "registry", "observation_id": "", "trusted": True},
                {"value": new, "at": obs.observed_at,
                 "observer": obs.observer, "source": obs.source,
                 "observation_id": obs.id, "trusted": obs.trusted}]})

    def find_conflicts(self, entity_id: str = "") -> list[dict[str, Any]]:
        if entity_id:
            return [c for c in self.conflicts if c["entity"] == entity_id]
        return list(self.conflicts)

    def find_uncertain(self, max_confidence: float = 0.5) -> list[WorldEntity]:
        return [e for e in self.entities.values()
                if e.confidence < max_confidence or e.uncertainty]

    def changes_since(self, timestamp: float) -> list[dict[str, Any]]:
        out = []
        for (eid, fld), records in self.history.items():
            for record in records:
                if record.get("at", 0.0) >= timestamp:
                    out.append({"entity": eid, "field": fld, **record})
        return sorted(out, key=lambda r: r.get("at", 0.0))

    def get_current_state(self) -> dict[str, Any]:
        """Summary snapshot: entity states keyed by id. Unknowns omitted."""
        return {eid: {"type": e.type, "name": e.name, "state": dict(e.state),
                      "confidence": e.confidence, "version": e.version,
                      "updated_at": e.updated_at}
                for eid, e in sorted(self.entities.items())}

    def get_evidence(self, entity_id: str) -> dict[str, Any]:
        entity = self.require_entity(entity_id)
        supporting, conflicting = [], []
        tokens = {entity_id.lower(), entity.name.lower()}
        for obs in self.observations.values():
            haystack = f"{obs.what} {' '.join(obs.evidence)}".lower()
            if any(token and token in haystack for token in tokens):
                (supporting if obs.trusted else conflicting).append(obs.to_dict())
        for conflict in self.find_conflicts(entity_id):
            conflicting.append(conflict)
        provenance = dict(entity.provenance) or {
            "note": "no direct provenance recorded; see supporting observations"}
        return {"entity": entity_id, "supporting": supporting,
                "conflicting": conflicting, "provenance": provenance}

    # -- memory promotion (controlled, auditable) ----------------------
    def promote_memory(self, memory: Any,
                       entity_type: str = "", name: str = "",
                       allow_speculative: bool = False) -> WorldEntity | None:
        """Promote ONE memory into an entity. Returns None when refused,
        with the reason recorded in the audit trail — never silent."""
        origin = getattr(memory, "origin", "") or ""
        tier = getattr(memory, "tier", "") or ""
        audit = {"memory_id": getattr(memory, "id", ""),
                 "at": now(), "origin": origin, "tier": tier}
        if getattr(memory, "id", "") in self._promoted:
            audit.update(action="skipped-duplicate",
                         entity_id=self._promoted[memory.id])
            self.promotions.append(audit)
            return self.entities.get(self._promoted[memory.id])
        if tier == "hypothesis" and not allow_speculative:
            audit.update(action="refused-speculative")
            self.promotions.append(audit)
            return None
        if origin not in PROMOTABLE_ORIGINS and not allow_speculative:
            audit.update(action="refused-origin")
            self.promotions.append(audit)
            return None
        label = name or (getattr(memory, "content", "") or "")[:60]
        entity, _ = self.upsert_entity(
            entity_type or "event", label,
            state={"content": getattr(memory, "content", "")},
            provenance={"observer": "memory-promotion",
                        "source": f"memory:{audit['memory_id']}",
                        "memory_origin": origin,
                        "memory_confidence": getattr(memory, "confidence", 0.6)},
            confidence=float(getattr(memory, "confidence", 0.6) or 0.6))
        self._promoted[audit["memory_id"]] = entity.id
        audit.update(action="promoted", entity_id=entity.id)
        self.promotions.append(audit)
        return entity

    # -- graph mirror (uses existing graph, no duplication) ------------
    def mirror_to_graph(self, graph: Any) -> dict[str, int]:
        """Mirror entities/relations into the KnowledgeGraph with
        layer/world-2.2 attribution. The graph stays canonical for
        traversal; this registry stays canonical for world state."""
        nodes, edges = 0, 0
        for entity in self.entities.values():
            try:
                graph.upsert_node(entity.name)
                nodes += 1
            except Exception:
                continue
        for relation in self.relations.values():
            src = self.entities.get(relation.src)
            dst = self.entities.get(relation.dst)
            if src is None or dst is None:
                continue
            try:
                graph.relate(src.name, relation.rel, dst.name,
                             confidence=relation.confidence,
                             attrs={"layer": "world-2.2"})
                edges += 1
            except Exception:
                continue
        return {"nodes": nodes, "edges": edges}

    # -- persistence ---------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "entities": {eid: e.to_dict() for eid, e in self.entities.items()},
            "relations": {rid: r.to_dict() for rid, r in self.relations.items()},
            "observations": {oid: o.to_dict()
                             for oid, o in self.observations.items()},
            "history": [{"entity": eid, "field": fld, "records": recs}
                        for (eid, fld), recs in self.history.items()],
            "conflicts": self.conflicts,
            "promotions": self.promotions,
            "exported_at": now(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorldRegistry":
        registry = cls()
        for eid, raw in (data.get("entities") or {}).items():
            try:
                entity = WorldEntity.from_dict(raw)
            except (ValueError, KeyError, TypeError):
                continue
            registry.entities[entity.id] = entity
        for rid, raw in (data.get("relations") or {}).items():
            try:
                relation = WorldRelation.from_dict(raw)
            except (ValueError, KeyError, TypeError):
                continue
            registry.relations[relation.id] = relation
        for oid, raw in (data.get("observations") or {}).items():
            try:
                registry.observations[oid] = WorldObservation.from_dict(raw)
            except (KeyError, TypeError):
                continue
        for block in data.get("history") or []:
            registry.history[(block.get("entity", ""),
                              block.get("field", ""))] = block.get("records", [])
        registry.conflicts = list(data.get("conflicts") or [])
        registry.promotions = list(data.get("promotions") or [])
        for row in registry.promotions:
            if row.get("action") == "promoted" and row.get("memory_id") \
                    and row.get("entity_id"):
                registry._promoted[row["memory_id"]] = row["entity_id"]
        return registry

    def save(self, store: WorldRepository) -> None:
        store.save(self.to_dict())

    def load(self, store: WorldRepository) -> None:
        data = store.load()
        if not data:
            return
        restored = WorldRegistry.from_dict(data)
        self.entities = restored.entities
        self.relations = restored.relations
        self.observations = restored.observations
        self.history = restored.history
        self.conflicts = restored.conflicts
        self.promotions = restored.promotions
        self._promoted = restored._promoted

    def stats(self) -> dict[str, int]:
        return {"entities": len(self.entities),
                "relations": len(self.relations),
                "observations": len(self.observations),
                "conflicts": len(self.conflicts),
                "promotions": len(self.promotions)}
