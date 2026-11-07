"""Event Model - M13 World Model Component.

Manages event detection, tracking, and temporal relationships.
Events represent changes or occurrences in the world that are
observed or inferred by JARVIS.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class EventRecord:
    """Represents an event in the world model."""
    event_id: str
    event_type: str
    description: str
    timestamp: float = field(default_factory=time.time)
    source: str = "unknown"
    confidence: float = 0.5
    related_objects: list[str] = field(default_factory=list)
    related_events: list[str] = field(default_factory=list)
    properties: dict[str, Any] = field(default_factory=dict)

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
            "properties": self.properties,
        }


class EventModel:
    """Manages event detection, tracking, and temporal relationships.

    Provides event creation, temporal ordering, causality tracking,
    and pattern detection for events in the world.
    """

    def __init__(self) -> None:
        self.events: dict[str, EventRecord] = {}
        self.created_at = time.time()

    def add_event(self, event: EventRecord) -> None:
        """Add an event to the model."""
        self.events[event.event_id] = event

    def get_event(self, event_id: str) -> EventRecord | None:
        """Get an event by ID."""
        return self.events.get(event_id)

    def get_events_by_type(self, event_type: str) -> list[EventRecord]:
        """Get all events of a given type."""
        return [e for e in self.events.values()
                if e.event_type == event_type]

    def get_recent_events(self, seconds: int = 300) -> list[EventRecord]:
        """Get events from the last N seconds."""
        cutoff = time.time() - seconds
        return [e for e in self.events.values()
                if e.timestamp >= cutoff]

    def get_events_for_object(self, object_id: str) -> list[EventRecord]:
        """Get all events related to a specific object."""
        return [e for e in self.events.values()
                if object_id in e.related_objects]

    def get_events_in_timeframe(self, start_time: float,
                                end_time: float) -> list[EventRecord]:
        """Get events within a time range."""
        return [e for e in self.events.values()
                if start_time <= e.timestamp <= end_time]

    def add_relationship(self, event_id_1: str, event_id_2: str,
                         relation: str,
                         confidence: float = 0.5) -> None:
        """Add a relationship between two events."""
        event = self.events.get(event_id_1)
        if event is None:
            return
        event.related_events.append(event_id_2)

    def get_event_summary(self) -> dict[str, Any]:
        """Get a summary of all events in the model."""
        return {
            "total_events": len(self.events),
            "by_type": {
                etype: len([e for e in self.events.values()
                            if e.event_type == etype])
                for etype in set(e.event_type for e in self.events.values())
            },
            "recent_count": len(self.get_recent_events()),
        }


# Global event model instance
_event_model: EventModel | None = None


def get_event_model() -> EventModel:
    """Get or create the global event model."""
    global _event_model
    if _event_model is None:
        _event_model = EventModel()
    return _event_model


__all__ = [
    "EventRecord",
    "EventModel",
    "get_event_model",
]
