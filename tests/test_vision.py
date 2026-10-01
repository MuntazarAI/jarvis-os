"""Vision observer tests. Fast paths run live; scene model needs RUN_SLOW=1."""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.cognition.mentalist import MentalistMode  # noqa: E402
from jarvis.memory.palace import MemoryPalace  # noqa: E402
from jarvis.security.security import ConsentEngine  # noqa: E402
from jarvis.vision.observer import VisionObserver, VisionObservation  # noqa: E402
from jarvis.vision.pipeline import CameraCapture, OCREngine, ScreenCapture  # noqa: E402
from jarvis.world.model import WorldModel  # noqa: E402


def test_observation_summary_and_nouns():
    obs = VisionObservation(source="file", path="/tmp/x.png",
                            ocr_text="deploy at 10:05", scene="a screen showing text")
    assert "deploy" in obs.summary()
    assert "deploy" in VisionObserver._nouns(obs.scene + " " + obs.ocr_text)
    assert obs.to_dict()["source"] == "file"


def test_see_file_missing():
    obs = VisionObserver().see_file("/nope-missing.png")
    assert not obs.ok and "no such image" in obs.error


def test_see_file_fast_path():
    pytest.importorskip("PIL")
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (800, 200), "white")
    ImageDraw.Draw(img).text((50, 70), "JARVIS deploy at 10:05", fill="black")
    img.save("/tmp/jarvis_ocr_probe.png")
    obs = VisionObserver().see_file("/tmp/jarvis_ocr_probe.png", scene=False)
    assert obs.ok, obs.to_dict()
    assert "deploy" in (obs.ocr_text + obs.scene).replace(" ", "").lower()


def test_feed_writes_world_memory_evidence():
    obs = VisionObservation(source="camera", path="/tmp/cam.png",
                            ocr_text="note", objects_noted=["desk"])
    world, palace, mentalist = WorldModel(), MemoryPalace(), MentalistMode()
    fed = VisionObserver().feed(obs, world=world, palace=palace, mentalist=mentalist)
    assert fed.get("world") and fed.get("memory_id") and fed.get("evidence")
    assert palace.search("note")


def test_camera_consent_gate():
    consent = ConsentEngine()
    observer = VisionObserver(consent=consent)
    denied = observer.see_camera(scene=False)
    assert not denied.ok and "consent" in denied.error
    consent.grant("camera")
    # After consent the only failure allowed is a hardware one, not consent.
    result = observer.see_camera(scene=False)
    assert "consent" not in result.error


def test_pipeline_backends_report():
    status = VisionObserver().status()
    assert set(status) == {"screen", "camera", "ocr", "vision_model", "observations"}
    assert OCREngine().available() in (True, False)
    assert CameraCapture().available() in (True, False)
    assert CameraCapture().backend in ("ffmpeg", "fswebcam", "none")
    assert ScreenCapture.available() in (True, False)


@pytest.mark.skipif(os.environ.get("RUN_SLOW") != "1",
                    reason="scene model takes minutes on CPU; set RUN_SLOW=1")
def test_live_scene_description():
    obs = VisionObserver().see_file("/tmp/jarvis_ocr_probe.png")
    assert obs.ok and obs.scene.strip()
