"""World State Model - M13 Cognitive Architecture.

Represents the current state of the world as observed by JARVIS.
Tracks objects, events, relationships, and temporal context.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class WorldObject:
    """Represents an object in the world model."""
    object_id: str
    name: str
    object_type: str  # person, object, location, device, etc.
    properties: dict[str, Any]
    location: str | None = None
    state: str = "unknown"
    confidence: float = 0.5
    last_updated: float = field(default_factory=time.time)
    source: str = "unknown"
    relations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "object_id": self.object_id,
            "name": self.name,
            "object_type": self.object_type,
            "properties": self.properties,
            "location": self.location,
            "state": self.state,
            "confidence": self.confidence,
            "last_updated": self.last_updated,
            "source": self.source,
            "relations": self.relations,
        }


@dataclass
class WorldEvent:
    """Represents an event in the world model."""
    event_id: str
    event_type: str
    description: str
    timestamp: float = field(default_factory=time.time)
    source: str = "unknown"
    confidence: float = 0.5
    related_objects: list[str] = field(default_factory=list)
    related_events: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "description": self.description,
            "timestamp": self.timestamp,
            "source": self.source,
            "confidence": self.confidence,
            "related_objects": self.related_objects,
            "related_events": self.related_events,
        }


@dataclass
class WorldState:
    """Complete world state representation.

    Captures the current state of the world as observed by JARVIS,
    including objects, events, relationships, and temporal context.
    """

    state_id: str = ""
    timestamp: float = field(default_factory=time.time)
    objects: dict[str, WorldObject] = field(default_factory=dict)
    events: dict[str, WorldEvent] = field(default_factory=dict)
    relationships: dict[str, dict[str, Any]] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.5
    uncertainty: float = 0.5

    def add_object(self, obj: WorldObject) -> None:
        """Add or update an object in the world state."""
        self.objects[obj.object_id] = obj

    def add_event(self, event: WorldEvent) -> None:
        """Add an event to the world state."""
        self.events[event.event_id] = event

    def add_relationship(self, subject_id: str, predicate: str, object_id: str,
                         confidence: float = 0.5) -> None:
        """Add a relationship between objects."""
        key = f"{subject_id}:{predicate}:{object_id}"
        self.relationships[key] = {
            "subject_id": subject_id,
            "predicate": predicate,
            "object_id": object_id,
            "confidence": confidence,
            "timestamp": time.time(),
        }

    def get_objects_by_type(self, object_type: str) -> list[WorldObject]:
        """Get all objects of a given type."""
        return [obj for obj in self.objects.values()
                if obj.object_type == object_type]

    def get_objects_at_location(self, location: str) -> list[WorldObject]:
        """Get all objects at a specific location."""
        return [obj for obj in self.objects.values()
                if obj.location == location]

    def get_recent_events(self, seconds: int = 300) -> list[WorldEvent]:
        """Get events from the last N seconds."""
        cutoff = time.time() - seconds
        return [e for e in self.events.values()
                if e.timestamp >= cutoff]

    def to_dict(self) -> dict[str, Any]:
        return {
            "state_id": self.state_id,
            "timestamp": self.timestamp,
            "objects": {k: v.to_dict() for k, v in self.objects.items()},
            "events": {k: v.to_dict() for k, v in self.events.items()},
            "relationships": self.relationships,
            "context": self.context,
            "confidence": self.confidence,
            "uncertainty": self.uncertainty,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorldState":
        """Create WorldState from dictionary."""
        state = cls(
            state_id=data.get("state_id", ""),
            timestamp=data.get("timestamp", time.time()),
            confidence=data.get("confidence", 0.5),
            uncertainty=data.get("uncertainty", 0.5),
            context=data.get("context", {}),
        )
        for obj_id, obj_data in data.get("objects", {}).items():
            state.objects[obj_id] = WorldObject(
                object_id=obj_data.get("object_id", obj_id),
                name=obj_data.get("name", ""),
                object_type=obj_data.get("object_type", "unknown"),
                properties=obj_data.get("properties", {}),
                location=obj_data.get("location"),
                state=obj_data.get("state", "unknown"),
                confidence=obj_data.get("confidence", 0.5),
                last_updated=obj_data.get("last_updated", time.time()),
                source=obj_data.get("source", "unknown"),
                roles=list(obj_data.get("roles", [])),
            )
        for event_id, event_data in data.get("events", {}).items():
            state.events[event_id] = WorldEvent(
                event_id=event_data.get("event_id", event_id),
                name=event_data.get("name", ""),
                object_type=event_data.get("object_type", "unknown"),
                properties=event_data.get("properties", {}),
                location=event_data.get("location"),
                state=event_data.get("state", "unknown"),
                confidence=event_data.get("confidence", 0.5),
                last_updated=event_data.get("last_updated", time.time()),
                source=event_data.get("source", "unknown"),
                relations=list(event_data.get("relations", [])),
            )
        return state