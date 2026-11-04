"""Phase 2 integration tests: Memory 3.0 + World Model bridge.

Tests bidirectional sync between World Model and Memory Palace:
  world.observe() → Memory Palace (observation memory with provenance)
  palace.store_episode() → World Model timeline
  State change detection → auto-generated episodic memories
  Temporal queries across both systems
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from jarvis.core.config import JarvisConfig
from jarvis.core.types import Observation, Modality
from jarvis.memory.palace import MemoryPalace
from jarvis.memory.world_bridge import WorldMemoryBridge, BridgeEvent
from jarvis.world.model import WorldModel


# -- fixtures --------------------------------------------------------------


@pytest.fixture
def home():
    return tempfile.mkdtemp(prefix="jarvis-phase2-")


@pytest.fixture
def config(home):
    cfg = JarvisConfig()
    cfg.paths.home = Path(home)
    return cfg


@pytest.fixture
def palace(config):
    db = str(Path(config.paths.home) / "memories.db")
    return MemoryPalace(path=db, config=config)


@pytest.fixture
def world():
    return WorldModel()


@pytest.fixture
def bridge(world, palace):
    return WorldMemoryBridge(world=world, palace=palace, auto_sync=True)


# -- Step 2.1: World-to-Memory pipeline -----------------------------------


def test_world_observe_writes_to_memory(bridge, world, palace):
    """world.observe() should also create a memory in the palace."""
    obs = Observation(
        kind="screen",
        content="User opened the browser",
        source="screen_capture",
        modality=Modality.SCREEN,
        confidence=0.9,
    )

    bridge.observe(obs)

    # World model should have the entity
    entities = world.entities()
    assert len(entities) >= 1

    # Memory palace should have an observation memory
    obs_memories = palace.all(tier="observation")
    assert len(obs_memories) >= 1

    # The observation memory should reference the world entity
    mem = obs_memories[0]
    assert "screen" in mem.content.lower() or "browser" in mem.content.lower()
    assert mem.origin == "observed"


def test_bridge_event_recorded(bridge, world, palace):
    """Each world→memory sync should record a BridgeEvent."""
    obs = Observation(
        kind="camera",
        content="Motion detected in living room",
        source="camera",
        modality=Modality.CAMERA,
        confidence=0.8,
    )

    bridge.observe(obs)

    assert len(bridge.events) >= 1
    event = bridge.events[-1]
    assert event.direction == "world_to_memory"
    assert event.memory_id != ""
    assert "camera" in event.description.lower()


def test_multiple_observations_sync(bridge, world, palace):
    """Multiple observations should all sync to memory."""
    for i in range(3):
        obs = Observation(
            kind="system",
            content=f"System metric {i} recorded",
            source="system_monitor",
            modality=Modality.SYSTEM,
            confidence=0.7,
        )
        bridge.observe(obs)

    assert bridge._sync_count == 3
    obs_memories = palace.all(tier="observation")
    assert len(obs_memories) == 3


# -- Step 2.2: Memory-to-World pipeline -----------------------------------


def test_store_episode_writes_to_world_timeline(bridge, world, palace):
    """palace.store_episode() should also write to World Model timeline."""
    initial_count = len(world._timeline)

    bridge.remember_episode(
        "User requested a file backup",
        room="Home",
        importance=0.7,
    )

    # World timeline should have grown
    assert len(world._timeline) > initial_count

    # The new event should reference the memory content
    latest = world._timeline[-1]
    assert "file backup" in latest.description.lower()
    assert latest.source == "memory"


def test_bridge_memory_to_world_event_recorded(bridge, world, palace):
    """Each memory→world sync should record a BridgeEvent."""
    bridge.remember_episode("Test episode for bridge")

    assert len(bridge.events) >= 1
    event = bridge.events[-1]
    assert event.direction == "memory_to_world"
    assert event.memory_id != ""


def test_bridge_status_includes_both_systems(bridge, world, palace):
    """Bridge status should report metrics from both systems."""
    bridge.observe(Observation(
        kind="screen", content="test", source="test",
        modality=Modality.TEXT, confidence=0.5,
    ))
    bridge.remember_episode("test episode")

    status = bridge.status()
    assert status["sync_count"] == 2
    assert status["world_entities"] >= 1
    assert status["memories"] >= 1
    assert status["auto_sync"] is True


# -- Step 2.3: State change detection -------------------------------------


def test_detect_state_changes_new_entity(bridge, world, palace):
    """New entities should be detected as state changes."""
    # Take an initial snapshot
    initial = world.snapshot()

    # Add a new entity
    world.upsert(kind="device", name="laptop", status="online", ip="192.168.1.50")

    # Detect changes
    changes = bridge.detect_state_changes(initial)

    assert len(changes) >= 1
    entity_added = [c for c in changes if c["kind"] == "entity_added"]
    assert len(entity_added) == 1
    assert entity_added[0]["entity_id"] == "device:laptop"

    # The change should be recorded as an episodic memory
    episode_memories = palace.all(tier="episodic", room="Current Situation Room")
    assert len(episode_memories) >= 1


def test_detect_state_changes_entity_updated(bridge, world, palace):
    """Entity attribute updates should be detected."""
    # Create initial entity
    world.upsert(kind="device", name="laptop", status="online")
    initial = world.snapshot()

    # Update it
    world.upsert(kind="device", name="laptop", status="offline", battery="20%")

    changes = bridge.detect_state_changes(initial)
    updated = [c for c in changes if c["kind"] == "entity_updated"]
    assert len(updated) == 1


def test_detect_state_changes_entity_removed(bridge, world, palace):
    """Entity removal should be detected."""
    world.upsert(kind="device", name="old_phone", status="offline")
    initial = world.snapshot()

    # Remove from world model
    del world._entities["device:old_phone"]

    changes = bridge.detect_state_changes(initial)
    removed = [c for c in changes if c["kind"] == "entity_removed"]
    assert len(removed) == 1


def test_detect_state_changes_no_false_positives(bridge, world, palace):
    """No changes should produce an empty change list."""
    initial = world.snapshot()
    changes = bridge.detect_state_changes(initial)
    assert changes == []


# -- Step 2.4: Snapshots ---------------------------------------------------


def test_bridge_snapshot_includes_both_systems(bridge, world, palace):
    """Bridge snapshot should include world + memory state."""
    bridge.observe(Observation(
        kind="screen", content="snapshot test", source="test",
        modality=Modality.TEXT, confidence=0.6,
    ))

    snap = bridge.snapshot()
    assert "world" in snap
    assert "memory_stats" in snap
    assert "bridge_events" in snap
    assert "sync_count" in snap
    assert snap["sync_count"] >= 1


# -- Step 2.5: Auto-sync toggle --------------------------------------------


def test_auto_sync_can_be_disabled(world, palace):
    """Bridge should work with auto_sync disabled."""
    b = WorldMemoryBridge(world=world, palace=palace, auto_sync=False)

    obs = Observation(
        kind="system", content="no sync test", source="test",
        modality=Modality.TEXT, confidence=0.5,
    )
    b.observe(obs)

    # World model should have the entity
    assert len(world.entities()) >= 1

    # Memory palace should NOT have an observation (auto-sync off)
    obs_memories = palace.all(tier="observation")
    assert len(obs_memories) == 0