"""World-Memory Bridge — bidirectional sync between World Model and Memory Palace.

Every world observation becomes a memory (with provenance). Every
significant memory writes to the world timeline. State changes in the
world model auto-generate episodic memories so nothing is lost.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..core.logging import get_module_logger
from ..core.types import Modality, Observation, now
from ..memory.palace import MemoryPalace

if TYPE_CHECKING:
    # Imported for typing only: the world model imports the cognition
    # package, which imports this module back. A runtime import here is
    # a circular import.
    from ..world.model import WorldModel

log = get_module_logger(__name__)


@dataclass
class BridgeEvent:
    """One bridge sync event, for audit and replay."""
    timestamp: float = field(default_factory=now)
    direction: str = ""  # "world_to_memory" or "memory_to_world"
    entity_id: str = ""
    memory_id: str = ""
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "direction": self.direction,
            "entity_id": self.entity_id,
            "memory_id": self.memory_id,
            "description": self.description,
        }


class WorldMemoryBridge:
    """Keeps World Model and Memory Palace in sync.

    Directions:
      - world_to_memory: world.observe() → palace.store_observation()
      - memory_to_world: palace.store_episode() → world.record_event()
    """

    def __init__(self, world: "WorldModel", palace: MemoryPalace,
                 auto_sync: bool = True) -> None:
        self.world = world
        self.palace = palace
        self.auto_sync = auto_sync
        self.events: list[BridgeEvent] = []
        self._sync_count = 0

    # -- world → memory --------------------------------------------------
    def observe(self, obs: Observation) -> None:
        """Record an observation in both world model and memory palace."""
        # 1. World model
        entity = self.world.observe(obs)

        # 2. Memory palace (if auto-sync enabled)
        memory_id = ""
        if self.auto_sync:
            mem = self.palace.store_observation(
                content=obs.content,
                source=obs.source,
                origin="observed",
                confidence=obs.confidence,
                related_entities=[entity.entity_id],
                metadata={
                    "world_entity": entity.entity_id,
                    "world_kind": obs.kind,
                    "modality": obs.modality,
                },
                modality=obs.modality,
            )
            memory_id = mem.id

        # 3. Audit
        event = BridgeEvent(
            direction="world_to_memory",
            entity_id=entity.entity_id,
            memory_id=memory_id,
            description=f"observed {obs.kind}: {obs.content[:60]}",
        )
        self.events.append(event)
        self._sync_count += 1

        log.info("Bridge: world→memory observed",
                 entity=entity.entity_id, memory=memory_id,
                 kind=obs.kind, source=obs.source)

    # -- memory → world --------------------------------------------------
    def remember_episode(self, content: str, **kw: Any) -> str:
        """Store an episodic memory and write it to the world timeline."""
        mem = self.palace.store_episode(content, **kw)

        event = self.world.record_event(
            description=content[:200],
            source="memory",
            confidence=mem.confidence,
            location=kw.get("room", "Home"),
        )

        bridge_event = BridgeEvent(
            direction="memory_to_world",
            entity_id="",
            memory_id=mem.id,
            description=f"episode: {content[:60]}",
        )
        self.events.append(bridge_event)
        self._sync_count += 1

        log.info("Bridge: memory→world episode",
                 memory=mem.id, event_timestamp=event.timestamp,
                 content=content[:60])
        return mem.id

    # -- state change detection ------------------------------------------
    def detect_state_changes(self, previous_snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        """Compare current world snapshot against a previous one.

        Returns a list of changes, each of which is auto-recorded as
        an episodic memory (so changes are never lost).
        """
        current = self.world.snapshot()
        changes: list[dict[str, Any]] = []

        # Entity changes
        prev_entities = {e["entity_id"]: e for e in previous_snapshot.get("entities", [])}
        curr_entities = {e["entity_id"]: e for e in current.get("entities", [])}

        for eid, curr in curr_entities.items():
            if eid not in prev_entities:
                changes.append({
                    "kind": "entity_added",
                    "entity_id": eid,
                    "name": curr.get("name", ""),
                    "attributes": curr.get("attributes", {}),
                })
            else:
                prev = prev_entities[eid]
                if curr.get("attributes") != prev.get("attributes"):
                    changes.append({
                        "kind": "entity_updated",
                        "entity_id": eid,
                        "name": curr.get("name", ""),
                        "changed_attributes": {
                            k: (prev.get(k), curr.get(k))
                            for k in set(curr.get("attributes", {})) | set(prev.get("attributes", {}))
                            if curr.get(k) != prev.get(k)
                        },
                    })

        for eid in prev_entities:
            if eid not in curr_entities:
                changes.append({
                    "kind": "entity_removed",
                    "entity_id": eid,
                    "name": prev_entities[eid].get("name", ""),
                })

        # Timeline changes
        prev_count = len(previous_snapshot.get("timeline", []))
        curr_count = len(current.get("timeline", []))
        if curr_count > prev_count:
            new_events = current["timeline"][prev_count:]
            for ev in new_events:
                changes.append({
                    "kind": "timeline_event",
                    "description": ev.get("description", ""),
                    "source": ev.get("source", "system"),
                    "timestamp": ev.get("timestamp", 0),
                })

        # Record each change as an episodic memory
        for change in changes:
            self._record_change_as_memory(change)

        return changes

    def _record_change_as_memory(self, change: dict[str, Any]) -> None:
        """Persist a detected world change as an episodic memory."""
        kind = change["kind"]
        if kind == "entity_added":
            content = (f"World change: new {change.get('name', change.get('entity_id', ''))} "
                       f"({change.get('entity_id', '')}) detected")
        elif kind == "entity_updated":
            content = (f"World change: {change.get('name', change.get('entity_id', ''))} "
                       f"attributes updated")
        elif kind == "entity_removed":
            content = (f"World change: {change.get('name', change.get('entity_id', ''))} "
                       f"removed")
        else:
            content = f"World change: {change.get('description', '')}"

        self.palace.store_episode(
            content=content,
            room="Current Situation Room",
            importance=0.6,
            source="world_bridge",
            origin="observed",
            metadata={"change_kind": kind, "change": change},
        )

    # -- snapshots -------------------------------------------------------
    def snapshot(self) -> dict[str, Any]:
        """Combined snapshot of world + memory state."""
        return {
            "world": self.world.snapshot(),
            "memory_stats": self.palace.stats(),
            "bridge_events": [e.to_dict() for e in self.events[-50:]],
            "sync_count": self._sync_count,
            "captured_at": now(),
        }

    def status(self) -> dict[str, Any]:
        return {
            "auto_sync": self.auto_sync,
            "sync_count": self._sync_count,
            "world_entities": len(self.world.entities()),
            "world_timeline_events": len(self.world._timeline),
            "memories": self.palace.stats()["total"],
            "recent_bridge_events": [e.to_dict() for e in self.events[-10:]],
        }
