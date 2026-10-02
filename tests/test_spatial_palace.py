"""Spatial Memory Palace tests."""

from jarvis.memory.palace import MemoryPalace
from jarvis.world.registry import WorldRegistry
from jarvis.spatial.palace import SpatialMemoryPalace, SpatialObservation, SpatialVersionConflict, UnknownSpatialNode


def test_hierarchy_and_path():
    s = SpatialMemoryPalace()
    home = s.add_node("world", "Home")
    room = s.add_node("room", "Office", parent_id=home.id)
    desk = s.add_node("surface", "Desk", parent_id=room.id)
    laptop = s.add_node("object", "Laptop", parent_id=desk.id, position={"x": 1, "y": 2, "z": 0})
    assert [n.name for n in s.children(room.id)] == ["Desk"]
    assert s.locate(laptop.id).name == "Desk"
    assert [s.get(x).name for x in s.path(laptop.id)] == ["Home", "Office", "Desk", "Laptop"]


def test_unknown_and_cycle_rejected():
    s = SpatialMemoryPalace()
    home = s.add_node("world", "Home")
    room = s.add_node("room", "Office", parent_id=home.id)
    try:
        s.add_node("object", "Ghost", parent_id="room:missing")
        raise AssertionError("unknown parent must fail")
    except UnknownSpatialNode:
        pass
    try:
        s.move(home.id, room.id)
        raise AssertionError("cycle must fail")
    except ValueError:
        pass


def test_cas_and_move_history():
    s = SpatialMemoryPalace()
    home = s.add_node("world", "Home")
    room = s.add_node("room", "Office", parent_id=home.id)
    laptop = s.add_node("object", "Laptop", parent_id=room.id)
    moved = s.move(laptop.id, home.id, expected_version=laptop.version)
    assert moved.parent_id == home.id
    assert moved.version == 2
    assert s.history[-1]["event"] == "moved"
    try:
        s.move(laptop.id, room.id, expected_version=1)
        raise AssertionError("stale move must fail")
    except SpatialVersionConflict:
        pass


def test_relations_and_nearby():
    s = SpatialMemoryPalace()
    room = s.add_node("room", "Office")
    a = s.add_node("object", "Laptop", parent_id=room.id, position={"x": 0, "y": 0, "z": 0})
    b = s.add_node("object", "Phone", parent_id=room.id, position={"x": 1, "y": 0, "z": 0})
    c = s.add_node("object", "Monitor", parent_id=room.id, position={"x": 5, "y": 0, "z": 0})
    s.relate(a.id, "near", b.id)
    assert [n.name for n, _ in s.nearby(a.id, 2.0)] == ["Phone"]
    assert s.related(a.id, "near")[0].name == "Phone"
    assert s.path(c.id) == [room.id, c.id]


def test_observation_must_be_applied_explicitly():
    s = SpatialMemoryPalace()
    home = s.add_node("world", "Home")
    room = s.add_node("room", "Office", parent_id=home.id)
    laptop = s.add_node("object", "Laptop", parent_id=room.id)
    obs = s.observe(SpatialObservation(subject_id=laptop.id, parent_id=home.id,
        position={"x": 3, "y": 2, "z": 1}, source="camera", observer="vision",
        confidence=0.9, evidence_refs=["frame-1"]))
    assert not obs.applied and laptop.parent_id == room.id
    s.apply_observation(obs.id)
    assert obs.applied and laptop.parent_id == home.id
    assert laptop.position == {"x": 3, "y": 2, "z": 1}


def test_untrusted_observation_blocked():
    s = SpatialMemoryPalace()
    room = s.add_node("room", "Office")
    laptop = s.add_node("object", "Laptop", parent_id=room.id)
    obs = s.observe(SpatialObservation(subject_id=laptop.id, parent_id=room.id,
                                       source="external web page"))
    assert not obs.trusted
    try:
        s.apply_observation(obs.id)
        raise AssertionError("untrusted observation must not mutate spatial state")
    except PermissionError:
        pass


def test_memory_integration():
    palace = MemoryPalace()
    s = SpatialMemoryPalace(memory_palace=palace)
    room = s.add_node("room", "Office")
    laptop = s.add_node("object", "Laptop", parent_id=room.id, confidence=0.9)
    mem = s.remember_spatial(laptop.id, source="camera", origin="observed")
    assert mem.tier == "spatial"
    assert mem.metadata["spatial_node_id"] == laptop.id


def test_world_integration():
    world = WorldRegistry()
    s = SpatialMemoryPalace(world_registry=world)
    home = s.add_node("world", "Home")
    room = s.add_node("room", "Office", parent_id=home.id)
    laptop = s.add_node("object", "Laptop", parent_id=room.id)
    assert world.get_entity("location:office") is not None
    assert world.get_entity("device:laptop") is not None
    rels = world.get_relationships("device:laptop")
    assert any(r.rel == "located_at" and r.dst == "location:office" for r in rels)


def test_persistence_roundtrip(tmp_path):
    path = tmp_path / "spatial.json"
    s = SpatialMemoryPalace(path)
    room = s.add_node("room", "Office")
    s.add_node("object", "Laptop", parent_id=room.id)
    s2 = SpatialMemoryPalace(path)
    assert s2.get("object:laptop").parent_id == room.id
    assert s2.stats()["nodes"] == 2


def test_snapshot_is_deterministic_enough():
    s = SpatialMemoryPalace()
    s.add_node("room", "Office")
    snap = s.snapshot()
    assert snap["stats"]["nodes"] == 1
    assert snap["nodes"][0]["name"] == "Office"
