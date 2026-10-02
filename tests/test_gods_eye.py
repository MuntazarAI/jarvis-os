"""God's Eye View integration tests."""

from jarvis.geospatial.gods_eye import GeoObservation, GodsEyeBridge
from jarvis.spatial.palace import SpatialMemoryPalace
from jarvis.world.registry import WorldRegistry


def test_ingest_does_not_mutate_world_until_explicit_apply(tmp_path):
    world = WorldRegistry()
    spatial = SpatialMemoryPalace()
    bridge = GodsEyeBridge(tmp_path / "geo.json", world_registry=world, spatial=spatial)
    obs = bridge.ingest(GeoObservation(
        kind="aircraft", name="Test Flight", latitude=10, longitude=20,
        altitude=1000, provider="test", confidence=0.9,
    ))
    assert bridge.get(obs.id) is not None
    assert world.entities == {}
    assert spatial.nodes == {}
    result = bridge.apply(obs.id)
    assert result["world_id"] is not None
    assert result["spatial_id"] is not None
    assert world.get_entity(result["world_id"]).state["latitude"] == 10


def test_untrusted_data_cannot_be_applied(tmp_path):
    bridge = GodsEyeBridge(tmp_path / "geo.json")
    obs = bridge.ingest(GeoObservation(
        kind="camera", name="Public Camera", source="external web",
        latitude=1, longitude=2, trusted=False,
    ))
    try:
        bridge.apply(obs.id)
        raise AssertionError("untrusted observation must not apply")
    except PermissionError:
        pass


def test_persistence_roundtrip(tmp_path):
    path = tmp_path / "geo.json"
    first = GodsEyeBridge(path)
    first.ingest(GeoObservation(kind="satellite", name="Demo", latitude=3, longitude=4))
    second = GodsEyeBridge(path)
    assert second.status()["observations"] == 1
    assert second.snapshot(kind="satellite")[0]["name"] == "Demo"


def test_unknown_coordinates_stay_unknown(tmp_path):
    world = WorldRegistry()
    spatial = SpatialMemoryPalace()
    bridge = GodsEyeBridge(tmp_path / "geo.json", world_registry=world, spatial=spatial)
    obs = bridge.ingest(GeoObservation(kind="earthquake", name="Event", confidence=0.9))
    result = bridge.apply(obs.id)
    assert result["world_id"] is not None
    assert result["spatial_id"] is None
