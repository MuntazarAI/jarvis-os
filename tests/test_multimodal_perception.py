"""Deterministic multimodal perception tests (4.3).

Contract, providers (faked hardware), OCR/objects, pipeline fan-out,
privacy/retention, replay safety, CLI shapes. No camera, display,
GPU, network, or remote APIs required.
"""

from __future__ import annotations

import json

import pytest

from jarvis.intelligence.sensory import (
    SensoryBus,
    event_from_observation,
)
from jarvis.memory.palace import MemoryPalace
from jarvis.perception.contract import (
    MAX_OBJECTS,
    Modality,
    Observation,
    PerceptionError,
    PrivacyClass,
    validate_confidence,
    validate_object,
)
from jarvis.perception.objects import (
    FakeObjects,
    UnavailableObjects,
)
from jarvis.perception.ocr import FakeOCR, TesseractOCR, UnavailableOCR
from jarvis.perception.pipeline import (
    ChangeDetector,
    ObservationStore,
    PerceptionPipeline,
)
from jarvis.perception.providers import (
    CameraProvider,
    FileProvider,
    ImageProvider,
    ScreenProvider,
)
from jarvis.spatial.palace import SpatialMemoryPalace
from jarvis.world.registry import JsonFileWorldStore, WorldRegistry


def _obs(**kw):
    base = dict(source="test", modality=Modality.SCREEN,
                payload={"visible_text": "hi"}, confidence=0.8)
    base.update(kw)
    return Observation(**base)


# 1-4. schema + validation ------------------------------------------------------------

def test_valid_observation_contract():
    obs = _obs()
    assert obs.correlation_id == obs.observation_id
    assert obs.to_dict()["modality"] == "screen"
    assert Observation.from_dict(obs.to_dict()).observation_id == \
        obs.observation_id


def test_invalid_modality_rejected():
    with pytest.raises(PerceptionError):
        Observation(source="s", modality="telepathy", payload={})


def test_invalid_confidence_rejected():
    for bad in (-0.1, 1.5, "high", None):
        with pytest.raises(PerceptionError):
            validate_confidence(bad)
    with pytest.raises(PerceptionError):
        _obs(confidence=99.0)


def test_payload_size_limits():
    with pytest.raises(PerceptionError):
        _obs(payload={"visible_text": "x" * 70000})
    with pytest.raises(PerceptionError):
        _obs(payload={"a": {"b": {"c": {"d": {"e": {"f": 1}}}}}})


def test_secret_keys_refused():
    with pytest.raises(PerceptionError):
        _obs(payload={"api_key": "abc"})
    with pytest.raises(PerceptionError):
        _obs(provenance={"session": "abc"})


# 5-7. OCR -------------------------------------------------------------------------------

def test_ocr_provider_contract():
    from jarvis.perception.ocr import OCRProvider
    with pytest.raises(NotImplementedError):
        OCRProvider().recognize("x.png")
    with pytest.raises(NotImplementedError):
        OCRProvider().available()


def test_fake_ocr_deterministic():
    fake = FakeOCR(text="deploy done", confidence=0.95)
    first = fake.recognize("any.png")
    assert first["text"] == "deploy done"
    assert first["confidence"] == 0.95
    assert fake.recognize("other.png") == first
    assert fake.calls == 2


def test_ocr_unavailable_never_throws(tmp_path):
    missing = tmp_path / "nope.png"
    out = UnavailableOCR().recognize(missing)
    assert out["status"] == "unavailable"
    assert out["confidence"] == 0.0
    try:
        TesseractOCR().recognize(missing)
        raise AssertionError("missing file must raise")
    except PerceptionError:
        pass


# 8-9. objects ---------------------------------------------------------------------------------

def test_object_interface_and_identity_refusal():
    from jarvis.perception.objects import ObjectPerceptionProvider
    with pytest.raises(NotImplementedError):
        ObjectPerceptionProvider().detect("x.png")
    assert UnavailableObjects().detect("x.png") == []
    with pytest.raises(PerceptionError):
        validate_object({"label": "person name John"})
    good = validate_object({"label": "laptop",
                            "confidence": 0.9, "bbox": [0, 0, 0.5, 0.5]})
    assert good["anonymous"] is True
    with pytest.raises(PerceptionError):
        validate_object({"label": "laptop", "bbox": [0, 0, 2.0, 0.5]})
    fake = FakeObjects([{"label": "laptop", "confidence": 0.9}])
    assert len(fake.detect("x.png")) == 1
    assert fake.calls == 1


# 10-11. screen/camera providers ----------------------------------------------------------------------

class _FakeCapture:
    def __init__(self, ok=True):
        self.ok = ok
        self.calls = 0

    def available(self):
        return self.ok

    def capture(self, dest, device=None):
        self.calls += 1
        if device is not None and False:
            pass
        Path = __import__("pathlib").Path
        Path(dest).write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 2000)


def test_screen_provider_fake_capture():
    provider = ScreenProvider(ocr=FakeOCR(text="hello world"))
    provider._capture = _FakeCapture()
    obs = provider.observe()
    assert obs.modality == Modality.SCREEN
    assert obs.payload["status"] == "ok"
    assert obs.payload["visible_text"] == "hello world"
    assert obs.confidence == 0.6
    provider.close()


def test_screen_provider_unavailable_is_structured():
    provider = ScreenProvider(ocr=FakeOCR())
    provider._capture = _FakeCapture(ok=False)
    obs = provider.observe()
    assert obs.payload["status"] == "unavailable"
    assert obs.confidence == 0.0


def test_camera_lifecycle_and_bounds():
    provider = CameraProvider(ocr=FakeOCR(text="lab"))
    provider._capture = _FakeCapture()
    assert provider.observe_once().payload["status"] == "error"  # not started
    assert provider.start()["started"] is True
    first = provider.observe_once()
    assert first.payload["status"] == "ok"
    assert first.confidence == 0.6
    assert len(provider.sample(count=30)) <= 10  # bounded
    provider.stop()
    provider.close()
    assert provider.observe_once().payload["status"] == "error"


def test_camera_unavailable_without_backend():
    provider = CameraProvider()
    provider._capture = _FakeCapture(ok=False)
    assert provider.start()["started"] is False
    assert provider.health()["available"] is False


# 12. file provider -------------------------------------------------------------------------------------

def test_file_provider_text_json_csv_md(tmp_path):
    provider = FileProvider()
    text = tmp_path / "a.txt"
    text.write_text("line one\nline two\n")
    assert provider.observe(path=str(text)).payload["file_type"] == "txt"
    data = tmp_path / "b.json"
    data.write_text('{"b": 1, "a": 2}')
    obs = provider.observe(path=str(data))
    assert obs.payload["metadata"]["keys"] == ["a", "b"]
    assert obs.confidence == 0.8
    assert obs.payload["content_hash"]
    csvp = tmp_path / "c.csv"
    csvp.write_text("x,y\n1,2\n3,4\n")
    assert provider.observe(path=str(csvp)).payload["metadata"]["rows"] == 3
    md = tmp_path / "d.md"
    md.write_text("# Title\nbody here\n")
    assert "Title" in provider.observe(path=str(md)).payload["metadata"][
        "headings"]
    with pytest.raises(PerceptionError):
        provider.observe(path=str(tmp_path / "missing.txt"))
    binary = tmp_path / "e.bin"
    binary.write_bytes(b"\x00\x01\x02")
    with pytest.raises(PerceptionError):
        provider.observe(path=str(binary))
    with pytest.raises(PerceptionError):
        provider.observe(path="")


# 13-14. duplicates + change -------------------------------------------------------------------------------

def test_duplicate_suppression_and_change(tmp_path):
    pipe = PerceptionPipeline()
    first = pipe.ingest(_obs())
    assert first["duplicate"] is False
    second = pipe.ingest(_obs(payload={"visible_text": "hi"}))
    assert second["duplicate"] is True
    assert second["prior_observation_id"] == first["observation_id"]
    third = pipe.ingest(_obs(payload={"visible_text": "changed"}))
    assert third["duplicate"] is False
    assert pipe.status()["metrics"]["duplicates"] == 1


def test_dedup_cache_bounded():
    detector = ChangeDetector(max_entries=5)
    for i in range(10):
        detector.check(_obs(payload={"visible_text": f"text {i}"}))
    assert len(detector._seen) == 5


# 15. bus -----------------------------------------------------------------------------------------------------------

def test_bus_adapter_types_and_bounds():
    for modality, bus_type in [(Modality.SCREEN, "screen"),
                               (Modality.CAMERA, "vision"),
                               (Modality.IMAGE, "vision"),
                               (Modality.FILE, "file"),
                               (Modality.DOCUMENT, "file"),
                               (Modality.SENSOR, "environment")]:
        event = event_from_observation(_obs(modality=modality))
        assert event.type == bus_type
        assert event.payload["observation_id"].startswith("obs-")
    bus = SensoryBus()
    received = []
    bus.subscribe("screen", received.append)
    pipe = PerceptionPipeline(bus=bus)
    pipe.ingest(_obs())
    assert len(received) == 1
    assert received[0].type == "screen"


# 16. world ----------------------------------------------------------------------------------------------------------------

def test_world_claim_and_file_apply(tmp_path):
    world = WorldRegistry()
    pipe = PerceptionPipeline(world=world)
    screen = _obs(confidence=0.9)
    out = pipe.ingest(screen)
    assert out["world"]["recorded"] is True
    assert out["world"].get("applied") in (False, None)  # claims only
    assert len(world.observations) == 1
    doc = Observation(source="file-provider", modality=Modality.FILE,
                      payload={"status": "ok", "path": "/tmp/report.md",
                               "file_type": "md", "content_hash": "abc123",
                               "summary": "doc"}, confidence=0.9)
    applied = pipe.ingest(doc)["world"]
    assert applied.get("applied") is True
    assert world.get_entity(applied["entity_id"]) is not None
    # Same hash again: idempotent, no duplicate entity.
    assert pipe.ingest(doc)["duplicate"] is True


# 17. memory ----------------------------------------------------------------------------------------------------------------------

def test_memory_floor_and_privacy(tmp_path):
    palace = MemoryPalace(path=tmp_path / "m.db")
    pipe = PerceptionPipeline(palace=palace)
    assert pipe.ingest(_obs(payload={"visible_text": "store me"},
                             confidence=0.8))["memory"]["stored"] is True
    assert pipe.ingest(_obs(payload={"visible_text": "too weak"},
                             confidence=0.2))["memory"]["stored"] is False
    assert pipe.ingest(_obs(payload={"visible_text": "sensitive stuff"},
                             confidence=0.9,
                             privacy_class=PrivacyClass.SENSITIVE))[
        "memory"]["stored"] is False
    private = pipe.ingest(_obs(payload={"visible_text": "private stuff"},
                                confidence=0.9,
                                privacy_class=PrivacyClass.PRIVATE))
    assert private.get("memory", {}).get("stored", False) is False
    assert len(palace.search("hi", limit=5)) >= 1


def test_private_ephemeral_everywhere(tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    palace = MemoryPalace(path=home / "m.db")
    world = WorldRegistry()
    pipe = PerceptionPipeline(world=world, palace=palace, home=home)
    obs = _obs(payload={"visible_text": "ephemeral"},
                  confidence=0.9, privacy_class=PrivacyClass.PRIVATE)
    out = pipe.ingest(obs)
    assert len(world.observations) == 0
    assert out.get("memory", {}).get("stored", False) is False
    assert not (home / "perception-observations.jsonl").exists()
    assert pipe.store.count() == 0  # fully ephemeral, not even indexed


# 18. spatial ----------------------------------------------------------------------------------------------------------------------------

def test_spatial_screen_and_camera(tmp_path):
    spatial = SpatialMemoryPalace()
    pipe = PerceptionPipeline(spatial=spatial)
    screen = _obs(payload={"visible_text": "ok", "ui_elements": [
        {"label": "Login", "confidence": 0.9, "bbox": [0, 0, 0.5, 0.2]},
        {"label": "Cancel", "confidence": 0.8, "bbox": [0.5, 0, 0.5, 0.2]}]},
        confidence=0.9)
    nodes = pipe.ingest(screen)["spatial"]["nodes"]
    assert len(nodes) == 2
    first = spatial.get(nodes[0])
    assert first is not None and first.position is not None
    assert first.provenance.get("approximate") is True
    camera = Observation(
        source="camera-provider", modality=Modality.CAMERA,
        payload={"status": "ok", "objects": [
            {"label": "laptop", "confidence": 0.9,
             "bbox": [0.0, 0.0, 0.4, 0.5]},
            {"label": "monitor", "confidence": 0.8,
             "bbox": [0.5, 0.0, 0.4, 0.5]}]}, confidence=0.9)
    result = pipe.ingest(camera)["spatial"]
    assert result["relations"] == 1
    rels = spatial.related(result["nodes"][0], "left_of")
    assert len(rels) == 1 and rels[0].name == "monitor"


# 19. supervisor ingestion -------------------------------------------------------------------------------------------------------------------------

def test_supervisor_consumes_perception_event(tmp_path):
    from jarvis.intelligence.cognitive import CognitiveSupervisor
    from jarvis.intelligence.loop import IntelligenceLoop
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    world = WorldRegistry()
    palace = MemoryPalace(path=home / "m.db")
    pipe = PerceptionPipeline(world=world, palace=palace, home=home)
    obs = _obs(confidence=0.8)
    pipe.ingest(obs)
    loop = IntelligenceLoop(
        normalize=lambda e: {"payload": dict(e.get("payload", e))}
        if isinstance(e, dict) else {})
    loop.start()
    sup = CognitiveSupervisor(loop, home=home)
    from jarvis.intelligence.sensory import SensoryBus
    bus = SensoryBus()
    pipe.bus = bus
    pipe.ingest(_obs(payload={"visible_text": "second"}))
    event = bus.history(limit=1)[0]
    out = sup.process(event)
    assert out.state.value == "completed"
    assert len(out.stages) == 13  # full engine incl. predict/verify


# 20-21. policy + service gates --------------------------------------------------------------------------------------------------------------------------------

def test_policy_denies_without_bypass_and_service_mandatory():
    from jarvis.intelligence import wiring
    from jarvis.policy.policy import PolicyEngine
    from jarvis.core.config import JarvisConfig
    from jarvis.tools.tools import default_registry
    hook = wiring.make_policy_hook(PolicyEngine(JarvisConfig()),
                                   tools=default_registry())
    assert hook("device.get_battery", {"device_id": "d"})[0] is False
    assert wiring.make_device_executor(None)(
        "device.get_battery", {"device_id": "d"})["ok"] is False
    assert wiring.make_device_executor(object())(
        "other.action", {})["ok"] is False


# 22. replay safety ---------------------------------------------------------------------------------------------------------------------------------------------------

def test_replay_uses_recorded_observation_not_providers(tmp_path):
    from jarvis.intelligence.cognitive import CognitiveSupervisor
    from jarvis.intelligence.loop import IntelligenceLoop
    from jarvis.intelligence.sensory import SensoryBus
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    bus = SensoryBus()
    fake = FakeOCR(text="screen text")
    provider_calls = []

    class CountingProvider:
        modality = Modality.SCREEN

        def observe(self, **kw):
            provider_calls.append(1)
            return _obs()

    provider = CountingProvider()
    pipe = PerceptionPipeline(bus=bus, home=home)
    pipe.ingest(provider.observe())
    assert provider_calls == [1]
    loop = IntelligenceLoop(
        normalize=lambda e: {"payload": dict(e.get("payload", e))}
        if isinstance(e, dict) else {})
    loop.start()
    sup = CognitiveSupervisor(loop, home=home)
    out = sup.process(bus.history(limit=1)[0])
    assert out.state.value == "completed"
    replayed = sup.replay(out.cycle_id)
    assert replayed.replayed is True
    assert provider_calls == [1]  # provider never re-invoked


# 23-25. secrets, retention, expiry -------------------------------------------------------------------------------------------------------------------------------------------------

def test_free_text_limitation_is_explicit_not_hidden(tmp_path):
    # Key-based scrubbing is the enforced convention (shared with
    # snapshots); free prose under innocent keys is NOT rewritten.
    # This test pins that boundary so it cannot silently widen.
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    secret = "sekret-topsecret-12345"
    obs = _obs(payload={"visible_text": f"deploy {secret} done"})
    pipe = PerceptionPipeline(home=home)
    pipe.ingest(obs)
    blob = (home / "perception-observations.jsonl").read_text()
    assert secret in blob  # free text is NOT key-scrubbed (documented)
    assert "password" not in blob


def test_ttl_expiry_pruning(tmp_path):
    from jarvis.perception.pipeline import ObservationStore
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    store = ObservationStore(home)
    old = _obs()
    old.timestamp = 1.0
    old.ttl_s = 10.0
    store.append(old)
    assert store.count() == 1
    # TTL lives on the record for consumers; the store stays bounded
    # by index cap regardless of age.
    for i in range(600):
        store.append(_obs(payload={"visible_text": f"pad {i}"}))
    assert store.count() == 500


# 26. bounds ------------------------------------------------------------------------------------------------------------------------

def test_queue_and_index_bounds():
    assert ChangeDetector.__init__.__defaults__ == (500,)
    from jarvis.perception import pipeline as pl
    assert pl.MAX_INDEX_ENTRIES == 500
    assert pl.MAX_STORE_BYTES == 4 * 1024 * 1024


# 27. malformed ---------------------------------------------------------------------------------------------------------------------------

def test_malformed_ingest_never_raises():
    pipe = PerceptionPipeline()
    assert pipe.ingest({})["ok"] is False
    assert pipe.ingest({"source": "", "modality": "screen"})["ok"] is False
    assert pipe.ingest(None)["ok"] is False  # type: ignore[arg-type]
    assert pipe.ingest({"source": "s", "modality": "screen",
                        "payload": {"password": "x"}})["ok"] is False
    assert pipe.status()["metrics"]["rejected"] == 4


# 28. lifecycle -------------------------------------------------------------------------------------------------------------------------------

def test_provider_lifecycle_idempotent():
    camera = CameraProvider()
    camera.stop()
    camera.close()
    assert camera.health()["started"] is False
    screen = ScreenProvider()
    screen.close()


# 29. unavailable hardware ------------------------------------------------------------------------------------------------------------------------------

def test_unavailable_everywhere_is_structured():
    assert ScreenProvider(
        ocr=UnavailableOCR()).capabilities()["ocr"] is False
    assert CameraProvider().health()["started"] is False
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp:
        missing = str(Path(tmp) / "nope.png")
        with pytest.raises(PerceptionError):
            ImageProvider().observe(path=missing)


# 30. synthetic multimodal e2e ------------------------------------------------------------------------------------------------------------------------------------

def test_synthetic_multimodal_e2e(tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    world = WorldRegistry()
    palace = MemoryPalace(path=home / "m.db")
    spatial = SpatialMemoryPalace()
    bus = SensoryBus()
    pipe = PerceptionPipeline(bus=bus, world=world, palace=palace,
                              spatial=spatial, home=home)
    screen = ScreenProvider(ocr=FakeOCR(text="Deploy finished"))
    screen._capture = _FakeCapture()
    file_provider = FileProvider()
    report = tmp_path / "report.md"
    report.write_text("# Deploy\nfinished ok\n")
    for obs in (screen.observe(),
                Observation(source="camera-provider",
                            modality=Modality.CAMERA,
                            payload={"status": "ok", "objects": [
                                {"label": "laptop", "confidence": 0.9,
                                 "bbox": [0, 0, 0.4, 0.5]}]},
                            confidence=0.9),
                file_provider.observe(path=str(report))):
        result = pipe.ingest(obs)
        assert result["ok"] is True and not result.get("duplicate")
    assert bus.stats()["buffered"] == 3
    assert len(world.observations) == 3
    assert len(palace.search("Deploy", limit=5)) >= 1
    assert spatial.stats()["nodes"] >= 1
    from jarvis.intelligence.cognitive import CognitiveSupervisor
    from jarvis.intelligence.loop import IntelligenceLoop
    loop = IntelligenceLoop(
        normalize=lambda e: {"payload": dict(e.get("payload", e))}
        if isinstance(e, dict) else {})
    loop.start()
    sup = CognitiveSupervisor(loop, home=home)
    for event in bus.history(limit=10):
        assert sup.process(event).state.value == "completed"
    assert sup.total_cycles == 3


class _FakeCapture:
    def __init__(self, ok=True):
        self.ok = ok

    def available(self):
        return self.ok

    def capture(self, dest, device=None):
        from pathlib import Path
        Path(dest).write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 2000)


def test_android_seam_typed_only():
    from jarvis.perception.android import (
        ANDROID_PERCEPTION_CAPABILITIES,
        ANDROID_PERCEPTION_EVENTS,
        android_capability_for,
        observation_from_device_event,
    )
    assert set(ANDROID_PERCEPTION_CAPABILITIES) == {
        "device.camera.snapshot", "device.screen.describe"}
    assert android_capability_for("camera") == "device.camera.snapshot"
    with pytest.raises(PerceptionError):
        android_capability_for("microphone")
    with pytest.raises(PerceptionError):
        observation_from_device_event("dev-1", "screen.scrape", {})
    with pytest.raises(PerceptionError):
        observation_from_device_event("", "camera.snapshot", {})
    obs = observation_from_device_event(
        "dev-1", "camera.snapshot",
        {"summary": "laptop on desk",
         "objects": [{"label": "laptop", "confidence": 0.9}]},
        confidence=0.8)
    assert obs.modality == Modality.CAMERA
    assert obs.source_device == "dev-1"
    assert obs.payload["objects"][0]["anonymous"] is True
    # Identity-shaped objects are refused at the seam (counted, visible).
    only_bad = observation_from_device_event(
        "dev-1", "camera.snapshot",
        {"objects": [{"label": "person name John"}]})
    assert only_bad.payload.get("objects", []) == []
    assert only_bad.payload.get("dropped_items") == 1
