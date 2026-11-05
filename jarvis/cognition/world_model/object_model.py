"""Object Model - M13 World Model Component.

Manages object representations in the world model including:
- Object detection and tracking
- Object state transitions
- Object-property relationships
- Object lifecycle management
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ObjectState:
    """Represents the state of an object at a point in time."""
    object_id: str
    name: str
    object_type: str
    properties: dict[str, Any] = field(default_factory=dict)
    location: str | None = None
    state: str = "unknown"
    confidence: float = 0.5
    timestamp: float = field(default_factory=time.time)
    source: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "object_id": self.object_id,
            "name": self.name,
            "object_type": self.object_type,
            "properties": self.properties,
            "location": self.location,
            "state": self.state,
            "confidence": self.confidence,
            "timestamp": self.timestamp,
            "source": self.source,
        }


class ObjectModel:
    """Manages object representations and their states over time.

    Provides object detection, tracking, state management, and
    relationship reasoning for objects in the world.
    """

    def __init__(self) -> None:
        self.objects: dict[str, WorldObject] = {}
        self.object_history: dict[str, list[ObjectState]] = {}
        self.created_at = time.time()

    def add_object(self, obj: WorldObject) -> None:
        """Add or update an object in the model."""
        self.objects[obj.object_id] = obj

    def get_object(self, object_id: str) -> WorldObject | None:
        """Get an object by ID."""
        return self.objects.get(object_id)

    def get_objects_by_type(self, object_type: str) -> list[WorldObject]:
        """Get all objects of a given type."""
        return [obj for obj in self.objects.values()
                if obj.object_type == object_type]

    def get_objects_at_location(self, location: str) -> list[WorldObject]:
        """Get all objects at a specific location."""
        return [obj for obj in self.objects.values()
                if obj.location == location]

    def update_object_state(self, object_id: str, state: str,
                            confidence: float = 0.5,
                            source: str = "unknown") -> bool:
        """Update the state of an object."""
        obj = self.objects.get(object_id)
        if obj is None:
            return False
        obj.state = state
        obj.confidence = confidence
        obj.last_updated = time.time()
        obj.source = source
        return True

    def update_object_location(self, object_id: str, location: str,
                               confidence: float = 0.5,
                               source: str = "unknown") -> bool:
        """Update the location of an object."""
        obj = self.objects.get(object_id)
        if obj is None:
            return False
        obj.location = location
        obj.confidence = confidence
        obj.last_updated = time.time()
        obj.source = source
        return True

    def add_object_state(self, object_id: str, state: ObjectState) -> None:
        """Add a state record to an object's history."""
        if object_id not in self.object_history:
            self.object_history[object_id] = []
        self.object_history[object_id].append(state)

    def get_object_history(self, object_id: str,
                           limit: int = 10) -> list[ObjectState]:
        """Get the state history for an object."""
        return self.object_history.get(object_id, [])[-limit:]

    def get_objects_summary(self) -> dict[str, Any]:
        """Get a summary of all objects in the model."""
        return {
            "total_objects": len(self.objects),
            "by_type": {
                obj_type: len([o for o in self.objects.values()
                               if o.object_type == obj_type])
                for obj_type in set(o.object_type for o in self.objects.values())
            },
            "by_location": {
                loc: len([o for o in self.objects.values()
                          if o.location == loc])
                for loc in set(o.location for o in self.objects.values()
                               if o.location)
            },
        }


# Global object model instance
_object_model: ObjectModel | None = None


def get_object_model() -> ObjectModel:
    """Get or create the global object model."""
    global _object_model
    if _object_model is None:
        _object_model = ObjectModel()
    return _object_model


__all__ = [
    "ObjectState",
    "ObjectModel",
    "get_object_model",
]
