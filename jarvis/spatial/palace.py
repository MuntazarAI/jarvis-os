"""Spatial Memory Palace — hierarchical spatial memory for JARVIS.

This layer turns the existing Memory Palace + World Model location concepts
into an explicit spatial representation. It is deliberately not a 3-D
renderer: coordinates are a compact semantic map that can later be populated
by camera/SLAM/vision backends.

Honesty contracts:
- unknown locations remain unknown; no guessed coordinates are invented
- observations are claims until explicitly applied
- untrusted/external observations cannot become trusted instructions
- movement preserves history rather than silently rewriting the past
- confidence/provenance/evidence travel with spatial facts
- world/memory mirroring is additive and best-effort
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..core.types import new_id, now

SPACE_KINDS = ("world", "building", "floor", "room", "area", "surface", "container", "object")
SPATIAL_RELATIONS = (
    "contains", "inside", "on", "near", "adjacent_to", "left_of", "right_of",
    "above", "below", "in_front_of", "behind", "attached_to",
)
ORIGINS = ("told", "observed", "inferred", "hypothesis", "system")


@dataclass
class SpatialNode:
    id: str
    name: str
    kind: str
    parent_id: str | None = None
    position: dict[str, float] | None = None
    dimensions: dict[str, float] | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.6
    uncertainty: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    evidence_refs: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=now)
    updated_at: float = field(default_factory=now)
    observed_at: float = field(default_factory=now)
    version: int = 1

    def __post_init__(self) -> None:
        if self.kind not in SPACE_KINDS:
            raise ValueError(f"unknown spatial kind: {self.kind}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence out of range: {self.confidence}")
        if self.position is not None:
            _validate_vector(self.position)
        if self.dimensions is not None:
            _validate_dimensions(self.dimensions)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SpatialNode":
        return cls(**data)


@dataclass
class SpatialRelation:
    id: str
    src: str
    relation: str
    dst: str
    confidence: float = 0.6
    provenance: dict[str, Any] = field(default_factory=dict)
    evidence_refs: list[str] = field(default_factory=list)
    observed_at: float = field(default_factory=now)
    updated_at: float = field(default_factory=now)
    version: int = 1

    def __post_init__(self) -> None:
        if self.relation not in SPATIAL_RELATIONS:
            raise ValueError(f"unknown spatial relation: {self.relation}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence out of range: {self.confidence}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SpatialRelation":
        return cls(**data)


@dataclass
class SpatialObservation:
    id: str = field(default_factory=lambda: new_id("sobs"))
    subject_id: str = ""
    parent_id: str | None = None
    position: dict[str, float] | None = None
    relation: str | None = None
    target_id: str | None = None
    source: str = ""
    observer: str = ""
    confidence: float = 0.6
    evidence_refs: list[str] = field(default_factory=list)
    trusted: bool = True
    applied: bool = False
    observed_at: float = field(default_factory=now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence out of range: {self.confidence}")
        if self.relation is not None and self.relation not in SPATIAL_RELATIONS:
            raise ValueError(f"unknown spatial relation: {self.relation}")
        if self.position is not None:
            _validate_vector(self.position)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SpatialObservation":
        return cls(**data)

    @staticmethod
    def classify_source(source: str) -> bool:
        low = (source or "").lower()
        return not any(x in low for x in ("external", "web", "untrusted", "third-party"))


class SpatialVersionConflict(Exception):
    """A stale spatial write was rejected."""


class UnknownSpatialNode(Exception):
    """A spatial node was not observed."""


def _validate_vector(value: dict[str, float]) -> None:
    if set(value) - {"x", "y", "z"}:
        raise ValueError("position must contain only x/y/z")
    for axis in ("x", "y", "z"):
        if axis in value and not isinstance(value[axis], (int, float)):
            raise ValueError(f"position {axis} must be numeric")


def _validate_dimensions(value: dict[str, float]) -> None:
    _validate_vector(value)
    if any(v < 0 for v in value.values()):
        raise ValueError("dimensions cannot be negative")


def _distance(a: dict[str, float], b: dict[str, float]) -> float | None:
    if not all(axis in a and axis in b for axis in ("x", "y", "z")):
        return None
    return math.sqrt(sum((float(a[k]) - float(b[k])) ** 2 for k in ("x", "y", "z")))


class SpatialMemoryPalace:
    """Persistent semantic spatial map backed by JSON."""

    def __init__(self, path: str | Path | None = None, *,
                 world_registry: Any | None = None,
                 memory_palace: Any | None = None) -> None:
        self.storage_path = Path(path) if path else None
        self.world_registry = world_registry
        self.memory_palace = memory_palace
        self.nodes: dict[str, SpatialNode] = {}
        self.relations: dict[str, SpatialRelation] = {}
        self.observations: dict[str, SpatialObservation] = {}
        self.history: list[dict[str, Any]] = []
        if self.storage_path and self.storage_path.exists():
            self.load()

    def _save(self) -> None:
        if not self.storage_path:
            return
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "nodes": {k: v.to_dict() for k, v in self.nodes.items()},
            "relations": {k: v.to_dict() for k, v in self.relations.items()},
            "observations": {k: v.to_dict() for k, v in self.observations.items()},
            "history": self.history[-1000:],
        }
        fd, tmp = tempfile.mkstemp(prefix=".spatial-", dir=str(self.storage_path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.storage_path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def load(self) -> None:
        if not self.storage_path or not self.storage_path.exists():
            return
        data = json.loads(self.storage_path.read_text(encoding="utf-8"))
        self.nodes = {}
        for key, raw in data.get("nodes", {}).items():
            try:
                node = SpatialNode.from_dict(raw)
                self.nodes[key] = node
            except (TypeError, ValueError, KeyError):
                continue
        self.relations = {}
        for key, raw in data.get("relations", {}).items():
            try:
                rel = SpatialRelation.from_dict(raw)
                if rel.src in self.nodes and rel.dst in self.nodes:
                    self.relations[key] = rel
            except (TypeError, ValueError, KeyError):
                continue
        self.observations = {}
        for key, raw in data.get("observations", {}).items():
            try:
                self.observations[key] = SpatialObservation.from_dict(raw)
            except (TypeError, ValueError, KeyError):
                continue
        self.history = list(data.get("history", []))[-1000:]

    def save(self) -> None:
        self._save()

    def add_node(self, kind: str, name: str, *,
                 parent_id: str | None = None,
                 position: dict[str, float] | None = None,
                 dimensions: dict[str, float] | None = None,
                 attributes: dict[str, Any] | None = None,
                 confidence: float = 0.6,
                 provenance: dict[str, Any] | None = None,
                 evidence_refs: list[str] | None = None,
                 expected_version: int | None = None) -> SpatialNode:
        if parent_id is not None and parent_id not in self.nodes:
            raise UnknownSpatialNode(parent_id)
        node_id = f"{kind}:{name.strip().lower().replace(' ', '-')}"
        existing = self.nodes.get(node_id)
        if existing:
            if expected_version is not None and existing.version != expected_version:
                raise SpatialVersionConflict(
                    f"{node_id}: expected {expected_version}, got {existing.version}")
            changed = []
            if parent_id is not None and existing.parent_id != parent_id:
                changed.append("parent_id")
                existing.parent_id = parent_id
            if position is not None and existing.position != position:
                changed.append("position")
                existing.position = dict(position)
            if dimensions is not None and existing.dimensions != dimensions:
                changed.append("dimensions")
                existing.dimensions = dict(dimensions)
            if attributes:
                for key, value in attributes.items():
                    if existing.attributes.get(key) != value:
                        existing.attributes[key] = value
                        changed.append(f"attributes.{key}")
            if provenance:
                existing.provenance.update(provenance)
            if evidence_refs:
                existing.evidence_refs = sorted(set(existing.evidence_refs + evidence_refs))
            existing.confidence = confidence
            if changed:
                existing.version += 1
                existing.updated_at = now()
                existing.observed_at = now()
                self.history.append({"event": "updated", "node_id": node_id,
                                     "changed": changed, "at": existing.updated_at,
                                     "version": existing.version})
            self._mirror(existing)
            self._save()
            return existing

        node = SpatialNode(
            id=node_id, name=name, kind=kind, parent_id=parent_id,
            position=dict(position) if position else None,
            dimensions=dict(dimensions) if dimensions else None,
            attributes=dict(attributes or {}), confidence=confidence,
            provenance=dict(provenance or {}), evidence_refs=list(evidence_refs or []),
        )
        self.nodes[node.id] = node
        self.history.append({"event": "created", "node_id": node.id, "at": node.created_at})
        self._mirror(node)
        self._save()
        return node

    def get(self, node_id: str) -> SpatialNode | None:
        return self.nodes.get(node_id)

    def require(self, node_id: str) -> SpatialNode:
        node = self.get(node_id)
        if node is None:
            raise UnknownSpatialNode(node_id)
        return node

    def children(self, parent_id: str) -> list[SpatialNode]:
        return sorted((n for n in self.nodes.values() if n.parent_id == parent_id),
                      key=lambda n: (n.kind, n.name.lower()))

    def ancestors(self, node_id: str) -> list[SpatialNode]:
        result: list[SpatialNode] = []
        seen: set[str] = set()
        current = self.require(node_id)
        while current.parent_id:
            if current.parent_id in seen:
                break
            seen.add(current.parent_id)
            parent = self.require(current.parent_id)
            result.append(parent)
            current = parent
        return result

    def locate(self, node_id: str) -> SpatialNode | None:
        node = self.get(node_id)
        if node is None:
            return None
        return self.get(node.parent_id) if node.parent_id else None

    def move(self, node_id: str, parent_id: str | None, *,
             position: dict[str, float] | None = None,
             confidence: float | None = None,
             provenance: dict[str, Any] | None = None,
             evidence_refs: list[str] | None = None,
             expected_version: int | None = None) -> SpatialNode:
        node = self.require(node_id)
        if parent_id is not None:
            self.require(parent_id)
            if parent_id == node_id or self._would_cycle(node_id, parent_id):
                raise ValueError("spatial move would create a cycle")
        if expected_version is not None and node.version != expected_version:
            raise SpatialVersionConflict(
                f"{node_id}: expected {expected_version}, got {node.version}")
        old_parent = node.parent_id
        node.parent_id = parent_id
        if position is not None:
            _validate_vector(position)
            node.position = dict(position)
        if confidence is not None:
            if not 0.0 <= confidence <= 1.0:
                raise ValueError("confidence out of range")
            node.confidence = confidence
        if provenance:
            node.provenance.update(provenance)
        if evidence_refs:
            node.evidence_refs = sorted(set(node.evidence_refs + evidence_refs))
        node.version += 1
        node.updated_at = now()
        node.observed_at = node.updated_at
        self.history.append({"event": "moved", "node_id": node_id, "from": old_parent,
                             "to": parent_id, "position": node.position,
                             "at": node.updated_at, "version": node.version})
        self._mirror(node)
        self._save()
        return node

    def _would_cycle(self, node_id: str, parent_id: str) -> bool:
        current = parent_id
        seen: set[str] = set()
        while current:
            if current == node_id or current in seen:
                return True
            seen.add(current)
            parent = self.nodes.get(current)
            current = parent.parent_id if parent else None
        return False

    def relate(self, src: str, relation: str, dst: str, *,
               confidence: float = 0.6,
               provenance: dict[str, Any] | None = None,
               evidence_refs: list[str] | None = None) -> SpatialRelation:
        self.require(src)
        self.require(dst)
        if relation not in SPATIAL_RELATIONS:
            raise ValueError(f"unknown spatial relation: {relation}")
        existing = next((r for r in self.relations.values()
                         if r.src == src and r.relation == relation and r.dst == dst), None)
        if existing:
            existing.version += 1
            existing.confidence = confidence
            existing.updated_at = now()
            if provenance:
                existing.provenance.update(provenance)
            if evidence_refs:
                existing.evidence_refs = sorted(set(existing.evidence_refs + evidence_refs))
            self._save()
            return existing
        rel = SpatialRelation(id=new_id("srel"), src=src, relation=relation, dst=dst,
                              confidence=confidence, provenance=dict(provenance or {}),
                              evidence_refs=list(evidence_refs or []))
        self.relations[rel.id] = rel
        self.history.append({"event": "relation", "relation_id": rel.id, "at": rel.observed_at})
        self._save()
        return rel

    def related(self, node_id: str, relation: str | None = None) -> list[SpatialNode]:
        self.require(node_id)
        ids = []
        for rel in self.relations.values():
            if rel.src == node_id and (relation is None or rel.relation == relation):
                ids.append(rel.dst)
            elif rel.dst == node_id and (relation is None or rel.relation == relation):
                ids.append(rel.src)
        return sorted((self.nodes[x] for x in set(ids)), key=lambda n: n.name.lower())

    def nearby(self, node_id: str, radius: float) -> list[tuple[SpatialNode, float]]:
        node = self.require(node_id)
        if node.position is None:
            return []
        found = []
        for other in self.nodes.values():
            if other.id == node.id or other.position is None:
                continue
            distance = _distance(node.position, other.position)
            if distance is not None and distance <= radius:
                found.append((other, distance))
        return sorted(found, key=lambda item: (item[1], item[0].name.lower()))

    def path(self, node_id: str) -> list[str]:
        return [n.id for n in reversed([self.require(node_id), *self.ancestors(node_id)])]

    def observe(self, observation: SpatialObservation) -> SpatialObservation:
        observation.trusted = SpatialObservation.classify_source(observation.source)
        self.observations[observation.id] = observation
        self._save()
        return observation

    def apply_observation(self, observation_id: str) -> SpatialObservation:
        obs = self.observations.get(observation_id)
        if obs is None:
            raise KeyError(observation_id)
        if not obs.trusted:
            raise PermissionError("untrusted spatial observation cannot be applied")
        node = self.require(obs.subject_id)
        if obs.parent_id is not None or obs.position is not None:
            self.move(node.id, obs.parent_id if obs.parent_id is not None else node.parent_id,
                      position=obs.position, confidence=obs.confidence,
                      provenance={"source": obs.source, "observation": obs.id},
                      evidence_refs=obs.evidence_refs)
        if obs.relation and obs.target_id:
            self.relate(node.id, obs.relation, obs.target_id,
                        confidence=obs.confidence,
                        provenance={"source": obs.source, "observation": obs.id},
                        evidence_refs=obs.evidence_refs)
        obs.applied = True
        self._save()
        return obs

    def remember_spatial(self, node_id: str, *, source: str = "system",
                         origin: str = "observed", importance: float = 0.6,
                         note: str | None = None) -> Any | None:
        node = self.require(node_id)
        if self.memory_palace is None:
            return None
        if origin not in ORIGINS:
            raise ValueError(f"unknown origin: {origin}")
        place = self.locate(node_id)
        text = note or (f"{node.name} is in {place.name}" if place
                        else f"{node.name} has no known containing location")
        return self.memory_palace.remember(
            text, tier="spatial", room=place.name if place else "Unknown",
            kind="spatial_fact", source=source, origin=origin,
            confidence=node.confidence, importance=importance,
            related_entities=[node.id] + ([place.id] if place else []),
            metadata={"spatial_node_id": node.id, "position": node.position},
        )

    def _mirror(self, node: SpatialNode) -> None:
        if self.world_registry is None:
            return
        try:
            world_type = "location" if node.kind in (
                "world", "building", "floor", "room", "area", "surface", "container"
            ) else "device"
            entity, _ = self.world_registry.upsert_entity(
                world_type, node.name,
                state={"spatial_parent": node.parent_id, "position": node.position},
                attributes={"spatial_node_id": node.id, **node.attributes},
                provenance={"spatial_memory": True, **node.provenance},
                confidence=node.confidence,
            )
            if node.parent_id:
                parent = self.nodes.get(node.parent_id)
                if parent:
                    parent_type = "location" if parent.kind != "object" else "device"
                    parent_id = f"{parent_type}:{parent.name.strip().lower().replace(' ', '-')}"
                    self.world_registry.relate(
                        entity.id, "located_at", parent_id,
                        confidence=node.confidence,
                        provenance={"spatial_memory": True},
                    )
        except Exception:
            return

    def stats(self) -> dict[str, int]:
        return {"nodes": len(self.nodes), "relations": len(self.relations),
                "observations": len(self.observations), "history": len(self.history)}

    def snapshot(self) -> dict[str, Any]:
        return {
            "nodes": [n.to_dict() for n in sorted(self.nodes.values(), key=lambda x: x.name.lower())],
            "relations": [r.to_dict() for r in self.relations.values()],
            "observations": [o.to_dict() for o in self.observations.values()],
            "stats": self.stats(),
        }
