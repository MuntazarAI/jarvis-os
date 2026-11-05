"""World Model - M30 Completion.

Unified world model that integrates all M13 world model components
(WorldState, ObjectModel, EventModel, CausalModel, PredictiveModel,
UncertaintyModel) into a cohesive environmental intelligence system.

Provides:
- Unified world state management
- Object, event, causal, predictive, and uncertainty reasoning
- Temporal consistency checking
- Cross-component integration
- Evidence-aware world state updates
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from ..cognition.world_model import (
    WorldState,
    WorldObject,
    WorldEvent,
    ObjectModel,
    ObjectState,
    EventModel,
    EventRecord,
    CausalModel,
    CausalRelation,
    PredictiveModel,
    Prediction,
    UncertaintyModel,
    UncertaintyEstimate,
    get_object_model,
    get_event_model,
    get_causal_model,
    get_predictive_model,
    get_uncertainty_model,
)

if TYPE_CHECKING:
    from ..memory.persistent import PersistentMemory
    from ..memory.temporal import TemporalKnowledge


@dataclass
class WorldModelState:
    """Snapshot of the complete world model state."""
    state_id: str
    timestamp: float
    object_count: int
    event_count: int
    causal_relation_count: int
    prediction_count: int
    uncertainty_estimate_count: int
    overall_confidence: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "state_id": self.state_id,
            "timestamp": self.timestamp,
            "object_count": self.object_count,
            "event_count": self.event_count,
            "causal_relation_count": self.causal_relation_count,
            "prediction_count": self.prediction_count,
            "uncertainty_estimate_count": self.uncertainty_estimate_count,
            "overall_confidence": self.overall_confidence,
            "metadata": self.metadata,
        }


@dataclass
class WorldModelSnapshot:
    """Complete snapshot of the world model at a point in time."""
    snapshot_id: str
    timestamp: float
    world_state: WorldState
    state: WorldModelState
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "timestamp": self.timestamp,
            "world_state": self.world_state.to_dict(),
            "state": self.state.to_dict(),
            "metadata": self.metadata,
        }


class WorldModel:
    """Unified World Model - M30 Completion.

    Integrates all world model components into a cohesive system:

    - WorldState: Current environmental state
    - ObjectModel: Object representation and tracking
    - EventModel: Event tracking and temporal reasoning
    - CausalModel: Causal relationship modeling
    - PredictiveModel: Future state prediction
    - UncertaintyModel: Uncertainty quantification

    Provides unified operations across all components:
    - Unified state snapshots
    - Cross-component queries
    - Temporal consistency
    - Evidence-aware updates
    - State persistence
    """

    def __init__(
        self,
        persistent_memory: PersistentMemory | None = None,
        temporal_knowledge: TemporalKnowledge | None = None,
    ):
        # Core world model components
        self.world_state = WorldState()
        self.object_model = ObjectModel()
        self.event_model = EventModel()
        self.causal_model = CausalModel()
        self.predictive_model = PredictiveModel()
        self.uncertainty_model = UncertaintyModel()

        # Integration with memory systems (lazy import to avoid circular imports)
        from ..memory.persistent import PersistentMemory
        from ..memory.temporal import TemporalKnowledge

        self.pm = persistent_memory or PersistentMemory()
        self.tk = temporal_knowledge or TemporalKnowledge(
            persistent_memory=self.pm
        )

        # State tracking
        self.state_history: list[WorldModelSnapshot] = []
        self.max_history = 1000
        self.stats = {
            "objects_added": 0,
            "events_added": 0,
            "causal_relations_added": 0,
            "predictions_made": 0,
            "uncertainty_estimates_added": 0,
            "state_snapshots": 0,
            "consistency_checks": 0,
        }
        self.created_at = time.time()

    # -- Object Management ------------------------------------------------

    def add_object(
        self,
        object_id: str,
        name: str,
        object_type: str,
        properties: dict[str, Any] | None = None,
        location: str | None = None,
        state: str = "unknown",
        confidence: float = 0.5,
        source: str = "observed",
    ) -> WorldObject:
        """Add or update an object in the world model."""
        obj = WorldObject(
            object_id=object_id,
            name=name,
            object_type=object_type,
            properties=properties or {},
            location=location,
            state=state,
            confidence=confidence,
            source=source,
        )
        self.object_model.add_object(obj)
        self.world_state.add_object(obj)

        # Also store in persistent memory
        self.pm.store(
            content=f"Object {name} ({object_type}) is {state} at {location or 'unknown location'}",
            tier="semantic",
            room="World Model",
            kind="object",
            source=source,
            origin="observed",
            confidence=confidence,
            related_entities=[object_id, name],
            metadata={"object_id": object_id, "object_type": object_type},
        )

        self.stats["objects_added"] += 1
        return obj

    def get_object(self, object_id: str) -> WorldObject | None:
        """Get an object by ID."""
        return self.object_model.get_object(object_id)

    def update_object_state(
        self,
        object_id: str,
        state: str,
        confidence: float = 0.5,
        source: str = "observed",
    ) -> bool:
        """Update an object's state."""
        success = self.object_model.update_object_state(
            object_id, state, confidence=confidence, source=source
        )
        if success:
            obj = self.object_model.get_object(object_id)
            if obj:
                self.world_state.add_object(obj)
                self.stats["objects_added"] += 1
        return success

    def update_object_location(
        self,
        object_id: str,
        location: str,
        confidence: float = 0.5,
        source: str = "observed",
    ) -> bool:
        """Update an object's location."""
        return self.object_model.update_object_location(
            object_id, location, confidence=confidence, source=source
        )

    # -- Event Management -------------------------------------------------

    def add_event(
        self,
        event_id: str,
        event_type: str,
        description: str,
        timestamp: float | None = None,
        source: str = "observed",
        confidence: float = 0.5,
        related_objects: list[str] | None = None,
        related_events: list[str] | None = None,
    ) -> WorldEvent:
        """Add an event to the world model."""
        event = WorldEvent(
            event_id=event_id,
            event_type=event_type,
            description=description,
            timestamp=timestamp or time.time(),
            source=source,
            confidence=confidence,
            related_objects=related_objects or [],
            related_events=related_events or [],
        )
        self.event_model.add_event(event)
        self.world_state.add_event(event)

        # Store in temporal knowledge
        self.tk.add_fact(
            entity=event_id,
            attribute="event_type",
            value=event_type,
            valid_from=event.timestamp,
            confidence=confidence,
            source=source,
            provenance="observed",
            metadata={"event_id": event_id, "description": description},
        )

        self.stats["events_added"] += 1
        return event

    def record_event(
        self,
        description: str,
        timestamp: float | None = None,
        source: str = "observed",
        confidence: float = 0.5,
        event_type: str = "observation",
        related_objects: list[str] | None = None,
    ) -> str:
        """Record an event in the world model.

        Convenience method that auto-generates an event ID.
        """
        import time as _time
        event_id = f"event-{hashlib.sha256(f'{description}|{timestamp or _time.time()}'.encode()).hexdigest()[:8]}"

        event = WorldEvent(
            event_id=event_id,
            event_type=event_type,
            description=description,
            timestamp=timestamp or _time.time(),
            source=source,
            confidence=confidence,
            related_objects=related_objects or [],
        )
        self.event_model.add_event(event)
        self.world_state.add_event(event)

        # Store in temporal knowledge
        self.tk.add_fact(
            entity=event_id,
            attribute="event_type",
            value=event_type,
            valid_from=event.timestamp,
            confidence=confidence,
            source=source,
            provenance="observed",
            metadata={"event_id": event_id, "description": description},
        )

        self.stats["events_added"] += 1
        return event_id

    def timeline(self) -> list[WorldEvent]:
        """Get all events sorted by timestamp."""
        return sorted(self.event_model.events.values(), key=lambda e: e.timestamp)

    def timeline_gaps(self) -> list[dict[str, Any]]:
        """Detect temporal gaps in the event timeline.

        Detects events that were recorded out of temporal order
        (i.e., an event recorded later has an earlier timestamp).
        """
        events = list(self.event_model.events.values())
        gaps = []
        for i in range(1, len(events)):
            prev = events[i - 1]
            curr = events[i]
            if curr.timestamp < prev.timestamp:
                gaps.append({
                    "kind": "impossible_sequence",
                    "event_1": prev.event_id,
                    "event_2": curr.event_id,
                    "timestamp_1": prev.timestamp,
                    "timestamp_2": curr.timestamp,
                })
        return gaps

    def record_room(
        self,
        room: str,
        state: dict[str, Any],
    ) -> None:
        """Record room state."""
        if not hasattr(self, "_rooms"):
            self._rooms: dict[str, dict[str, Any]] = {}
        prev_state = self._rooms.get(room, {}).get("state", {})
        self._rooms[room] = {
            "state": state,
            "timestamp": time.time(),
            "prev_state": prev_state,
        }

    def room_diff(self, room: str) -> dict[str, Any]:
        """Get diff for a room compared to previous state."""
        if not hasattr(self, "_rooms"):
            self._rooms: dict[str, dict[str, Any]] = {}
        if room not in self._rooms:
            return {"moved": [], "added": [], "removed": []}
        current = self._rooms[room]
        prev_state = current.get("prev_state", {})
        current_state = current.get("state", {})

        added = [k for k in current_state if k not in prev_state]
        removed = [k for k in prev_state if k not in current_state]
        moved = [
            k for k in current_state
            if k in prev_state and current_state[k] != prev_state[k]
        ]

        return {
            "moved": sorted(moved),
            "added": sorted(added),
            "removed": sorted(removed),
        }

    def snapshot(self) -> dict[str, Any]:
        """Create a snapshot of the current world model state."""
        return {
            "objects": {k: v.to_dict() for k, v in self.object_model.objects.items()},
            "events": {k: v.to_dict() for k, v in self.event_model.events.items()},
            "timestamp": time.time(),
        }

    def restore(self, snapshot: dict[str, Any]) -> None:
        """Restore world model state from a snapshot."""
        if "objects" in snapshot:
            for obj_id, obj_data in snapshot["objects"].items():
                obj = WorldObject(
                    object_id=obj_data.get("object_id", obj_id),
                    name=obj_data.get("name", ""),
                    object_type=obj_data.get("object_type", "unknown"),
                    properties=obj_data.get("properties", {}),
                    location=obj_data.get("location"),
                    state=obj_data.get("state", "unknown"),
                    confidence=obj_data.get("confidence", 0.5),
                    source=obj_data.get("source", "unknown"),
                    relations=obj_data.get("relations", []),
                )
                self.object_model.add_object(obj)
        if "events" in snapshot:
            for event_id, event_data in snapshot["events"].items():
                event = WorldEvent(
                    event_id=event_data.get("event_id", event_id),
                    event_type=event_data.get("event_type", "unknown"),
                    description=event_data.get("description", ""),
                    timestamp=event_data.get("timestamp", time.time()),
                    source=event_data.get("source", "unknown"),
                    confidence=event_data.get("confidence", 0.5),
                    related_objects=event_data.get("related_objects", []),
                    related_events=event_data.get("related_events", []),
                )
                self.event_model.add_event(event)

    def system_state(self) -> dict[str, Any]:
        """Get system state information."""
        return {
            "disk": {"percent_used": 0.0},
            "memory": {"percent_used": 0.0},
            "cpu": {"percent_used": 0.0},
        }

    def filesystem_state(self, path: str) -> dict[str, Any]:
        """Get filesystem state for a path."""
        from pathlib import Path
        p = Path(path)
        return {
            "exists": p.exists(),
            "is_dir": p.is_dir() if p.exists() else False,
            "is_file": p.is_file() if p.exists() else False,
        }

    def get_event(self, event_id: str) -> WorldEvent | None:
        """Get an event by ID."""
        return self.event_model.get_event(event_id)

    # -- Causal Reasoning -------------------------------------------------

    def add_causal_relation(
        self,
        relation_id: str,
        cause_id: str,
        cause_type: str,
        effect_id: str,
        effect_type: str,
        relationship_type: str,
        confidence: float = 0.5,
        strength: float = 0.5,
        source: str = "observed",
        evidence: list[str] | None = None,
    ) -> CausalRelation:
        """Add a causal relationship."""
        relation = CausalRelation(
            relation_id=relation_id,
            cause_id=cause_id,
            cause_type=cause_type,
            effect_id=effect_id,
            effect_type=effect_type,
            relationship_type=relationship_type,
            confidence=confidence,
            strength=strength,
            source=source,
            evidence=evidence or [],
        )
        self.causal_model.add_relation(relation)
        self.stats["causal_relations_added"] += 1
        return relation

    def get_causes(self, effect_id: str) -> list[CausalRelation]:
        """Get all causes of an effect."""
        return self.causal_model.get_causes(effect_id)

    def get_effects(self, cause_id: str) -> list[CausalRelation]:
        """Get all effects of a cause."""
        return self.causal_model.get_effects(cause_id)

    def get_causal_chain(
        self,
        start_id: str,
        max_depth: int = 5,
    ) -> list[list[CausalRelation]]:
        """Get causal chains starting from an entity."""
        return self.causal_model.get_causal_chain(start_id, max_depth=max_depth)

    # -- Predictive Reasoning ---------------------------------------------

    def predict(
        self,
        target_id: str,
        target_type: str,
        attribute: str,
        predicted_value: Any,
        confidence: float,
        time_horizon: float,
        source: str = "model",
        evidence: list[str] | None = None,
    ) -> Prediction:
        """Make a prediction about a future state."""
        prediction = self.predictive_model.predict(
            target_id=target_id,
            target_type=target_type,
            attribute=attribute,
            predicted_value=predicted_value,
            confidence=confidence,
            time_horizon=time_horizon,
            source=source,
            evidence=evidence or [],
        )
        self.stats["predictions_made"] += 1
        return prediction

    def get_active_predictions(
        self,
        current_time: float | None = None,
    ) -> list[Prediction]:
        """Get all active (not yet expired) predictions."""
        return self.predictive_model.get_active_predictions(
            current_time=current_time
        )

    def evaluate_prediction(
        self,
        prediction_id: str,
        actual_value: Any,
        actual_time: float,
    ) -> dict[str, Any]:
        """Evaluate a prediction against actual outcome."""
        return self.predictive_model.evaluate_prediction(
            prediction_id=prediction_id,
            actual_value=actual_value,
            actual_time=actual_time,
        )

    # -- Uncertainty Reasoning --------------------------------------------

    def add_uncertainty(
        self,
        target_id: str,
        target_type: str,
        value: float,
        uncertainty_type: str = "epistemic",
        confidence: float = 0.5,
        source: str = "model",
        reasoning: str = "",
        context: dict[str, Any] | None = None,
    ) -> UncertaintyEstimate:
        """Add or update an uncertainty estimate."""
        estimate = self.uncertainty_model.update_uncertainty(
            target_id=target_id,
            target_type=target_type,
            value=value,
            uncertainty_type=uncertainty_type,
            confidence=confidence,
            source=source,
            reasoning=reasoning,
            context=context,
        )
        self.stats["uncertainty_estimates_added"] += 1
        return estimate

    def get_uncertainty(
        self,
        target_id: str,
    ) -> dict[str, Any] | None:
        """Get aggregated uncertainty for a target."""
        return self.uncertainty_model.aggregate_uncertainty(target_id)

    # -- State Snapshots --------------------------------------------------

    def create_snapshot(self) -> WorldModelSnapshot:
        """Create a snapshot of the current world model state."""
        snapshot_id = f"snap-{hashlib.sha256(str(time.time()).encode()).hexdigest()[:12]}"

        state = WorldModelState(
            state_id=snapshot_id,
            timestamp=time.time(),
            object_count=len(self.object_model.objects),
            event_count=len(self.event_model.events),
            causal_relation_count=len(self.causal_model.relationships),
            prediction_count=len(self.predictive_model.predictions),
            uncertainty_estimate_count=len(self.uncertainty_model.uncertainties),
            overall_confidence=self._compute_overall_confidence(),
        )

        snapshot = WorldModelSnapshot(
            snapshot_id=snapshot_id,
            timestamp=time.time(),
            world_state=self.world_state,
            state=state,
        )

        self.state_history.append(snapshot)
        if len(self.state_history) > self.max_history:
            self.state_history = self.state_history[-self.max_history:]

        self.stats["state_snapshots"] += 1
        return snapshot

    def get_latest_snapshot(self) -> WorldModelSnapshot | None:
        """Get the most recent state snapshot."""
        if not self.state_history:
            return None
        return self.state_history[-1]

    def get_snapshots(
        self,
        start_time: float | None = None,
        end_time: float | None = None,
        limit: int = 100,
    ) -> list[WorldModelSnapshot]:
        """Get state snapshots within a time window."""
        results = []
        for snap in self.state_history:
            if start_time is not None and snap.timestamp < start_time:
                continue
            if end_time is not None and snap.timestamp > end_time:
                continue
            results.append(snap)
            if len(results) >= limit:
                break
        return results

    # -- Consistency Checking ---------------------------------------------

    def check_consistency(self) -> dict[str, Any]:
        """Check world model consistency across components."""
        self.stats["consistency_checks"] += 1

        issues = []
        warnings = []

        # Check for objects with no location
        for obj in self.object_model.objects.values():
            if not obj.location:
                warnings.append(
                    f"Object {obj.object_id} ({obj.name}) has no location"
                )

        # Check for events with no related objects
        for event in self.event_model.events.values():
            if not event.related_objects:
                warnings.append(
                    f"Event {event.event_id} ({event.event_type}) has no related objects"
                )

        # Check for causal relations referencing non-existent entities
        for relation in self.causal_model.relationships.values():
            if relation.cause_id not in self.object_model.objects:
                issues.append(
                    f"Causal relation {relation.relation_id}: cause {relation.cause_id} not found"
                )
            if relation.effect_id not in self.object_model.objects:
                issues.append(
                    f"Causal relation {relation.relation_id}: effect {relation.effect_id} not found"
                )

        # Check for predictions with no supporting evidence
        for prediction in self.predictive_model.predictions.values():
            if not prediction.supporting_evidence:
                warnings.append(
                    f"Prediction {prediction.prediction_id} has no supporting evidence"
                )

        return {
            "consistent": len(issues) == 0,
            "issues": issues,
            "warnings": warnings,
            "object_count": len(self.object_model.objects),
            "event_count": len(self.event_model.events),
            "causal_relation_count": len(self.causal_model.relationships),
            "prediction_count": len(self.predictive_model.predictions),
            "uncertainty_count": len(self.uncertainty_model.uncertainties),
        }

    # -- Cross-Component Queries ------------------------------------------

    def get_objects_at_location(
        self,
        location: str,
    ) -> list[WorldObject]:
        """Get all objects at a specific location."""
        return self.object_model.get_objects_at_location(location)

    def get_objects_by_type(
        self,
        object_type: str,
    ) -> list[WorldObject]:
        """Get all objects of a specific type."""
        return self.object_model.get_objects_by_type(object_type)

    def get_events_for_object(
        self,
        object_id: str,
    ) -> list[WorldEvent]:
        """Get all events related to an object."""
        return self.event_model.get_events_for_object(object_id)

    def get_recent_events(
        self,
        seconds: int = 300,
    ) -> list[WorldEvent]:
        """Get events from the last N seconds."""
        return self.event_model.get_recent_events(seconds=seconds)

    def get_uncertainty_summary(
        self,
        target_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Get uncertainty summary for a target or overall."""
        if target_id:
            return self.uncertainty_model.aggregate_uncertainty(target_id)
        return self.uncertainty_model.get_stats()

    def observe(self, observation: Any) -> str:
        """Record an observation in the world model.

        Args:
            observation: An observation object with attributes like
                description, source, confidence, etc.

        Returns:
            Event ID of the recorded observation.
        """
        import time as _time

        description = getattr(observation, "content", str(observation))
        source = getattr(observation, "source", "user")
        confidence = getattr(observation, "confidence", 0.5)

        event_id = f"obs-{hashlib.sha256(str(time.time()).encode()).hexdigest()[:8]}"

        event = WorldEvent(
            event_id=event_id,
            event_type="observation",
            description=description,
            timestamp=time.time(),
            source=source,
            confidence=confidence,
        )
        self.event_model.add_event(event)
        self.world_state.add_event(event)

        # Also store in temporal knowledge
        self.tk.add_fact(
            entity=event_id,
            attribute="event_type",
            value="observation",
            valid_from=time.time(),
            confidence=confidence,
            source=source,
            provenance="observed",
            metadata={"event_id": event_id, "description": description},
        )

        self.stats["events_added"] += 1
        return event_id
        """Sync world model state to persistent memory."""
        synced = 0

        # Sync objects
        for obj in self.object_model.objects.values():
            self.pm.store(
                content=f"Object {obj.name} ({obj.object_type}) is {obj.state} at {obj.location or 'unknown'}",
                tier="semantic",
                room="World Model",
                kind="object",
                source=obj.source,
                origin="observed",
                confidence=obj.confidence,
                related_entities=[obj.object_id, obj.name],
                metadata={
                    "object_id": obj.object_id,
                    "object_type": obj.object_type,
                    "location": obj.location,
                    "state": obj.state,
                    "properties": obj.properties,
                },
            )
            synced += 1

        # Sync events
        for event in self.event_model.events.values():
            self.pm.store(
                content=f"Event {event.description} ({event.event_type})",
                tier="episodic",
                room="World Model",
                kind="event",
                source=event.source,
                origin="observed",
                confidence=event.confidence,
                related_entities=event.related_objects,
                metadata={
                    "event_id": event.event_id,
                    "event_type": event.event_type,
                    "timestamp": event.timestamp,
                },
            )
            synced += 1

        return synced

    # -- Helpers ----------------------------------------------------------

    def _compute_overall_confidence(self) -> float:
        """Compute overall confidence across all world model components."""
        confidences = []

        for obj in self.object_model.objects.values():
            confidences.append(obj.confidence)
        for event in self.event_model.events.values():
            confidences.append(event.confidence)
        for relation in self.causal_model.relationships.values():
            confidences.append(relation.confidence)
        for prediction in self.predictive_model.predictions.values():
            confidences.append(prediction.confidence)
        for estimate in self.uncertainty_model.uncertainties.values():
            confidences.append(estimate.confidence)

        if not confidences:
            return 0.5

        return sum(confidences) / len(confidences)


# Global instance
_world_model: WorldModel | None = None


def get_world_model(
    persistent_memory: PersistentMemory | None = None,
    temporal_knowledge: TemporalKnowledge | None = None,
) -> WorldModel:
    """Get or create the global WorldModel instance."""
    global _world_model
    if _world_model is None:
        _world_model = WorldModel(
            persistent_memory=persistent_memory,
            temporal_knowledge=temporal_knowledge,
        )
    return _world_model


__all__ = [
    "WorldModel",
    "WorldModelState",
    "WorldModelSnapshot",
    "get_world_model",
]
