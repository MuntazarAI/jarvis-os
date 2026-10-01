"""Vision observer: camera/screen → OCR + scene model → world + memory.

Feeds the existing WorldModel, MemoryPalace and MentalistMode. Camera use
can require explicit consent through ConsentEngine.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core.types import Observation, now


@dataclass
class VisionObservation:
    source: str  # camera | screen | file
    path: str
    ocr_text: str = ""
    scene: str = ""
    objects_noted: list[str] = field(default_factory=list)
    at: float = field(default_factory=now)
    ok: bool = True
    error: str = ""

    def summary(self) -> str:
        parts = [f"{self.source} observation at {self.path}"]
        if self.ocr_text.strip():
            parts.append(f"text seen: {self.ocr_text.strip()[:300]}")
        if self.scene.strip():
            parts.append(f"scene: {self.scene.strip()[:500]}")
        return ". ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {"source": self.source, "path": self.path,
                "ocr_text": self.ocr_text, "scene": self.scene,
                "objects_noted": self.objects_noted, "at": self.at,
                "ok": self.ok, "error": self.error}


class VisionObserver:
    """High-level see() API over the pipeline pieces."""

    def __init__(self, capture_dir: str = "/tmp/jarvis-vision",
                 consent: Any | None = None) -> None:
        from .pipeline import CameraCapture, OCREngine, ScreenCapture
        self.captures = ScreenCapture()
        self.camera = CameraCapture()
        self.ocr = OCREngine()
        self.capture_dir = Path(capture_dir)
        self.capture_dir.mkdir(parents=True, exist_ok=True)
        self.consent = consent
        self.history: list[VisionObservation] = []

    def status(self) -> dict[str, Any]:
        return {"screen": self.captures.available(),
                "camera": self.camera.backend,
                "ocr": self.ocr.backend,
                "vision_model": self._vision_ready(),
                "observations": len(self.history)}

    def _vision_ready(self) -> bool:
        try:
            from ..models.ollama import OllamaClient
            client = OllamaClient()
            return client.alive() and client.has("minicpm-v:latest")
        except Exception:
            return False

    def _ocr_file(self, path: str) -> str:
        result = self.ocr.read(path)
        return result.get("text", "") if result.get("ok") else ""

    def _describe(self, path: str, question: str) -> str:
        try:
            from ..models.ollama import OllamaClient
            result = OllamaClient().describe_image(path, question)
            return result.get("text", "") if result.get("ok") else ""
        except Exception:
            return ""

    def _require_camera(self) -> str | None:
        if self.consent is None:
            return None
        try:
            self.consent.require("camera")
            return None
        except PermissionError as exc:
            return str(exc)

    def see_camera(self, device: str = "/dev/video0",
                   question: str = "Briefly describe what you see. "
                                   "List visible objects.",
                   scene: bool = True) -> VisionObservation:
        denied = self._require_camera()
        if denied:
            return VisionObservation(source="camera", path="", ok=False, error=denied)
        dest = str(self.capture_dir / "camera.png")
        shot = self.camera.capture(dest, device=device)
        if not shot.get("ok"):
            obs = VisionObservation(source="camera", path=dest, ok=False,
                                    error=shot.get("error", "capture failed"))
            self.history.append(obs)
            return obs
        return self._finish("camera", dest, question, scene=scene)

    def see_screen(self, question: str = "Describe this screen. "
                                       "What application is visible and what text stands out?",
                   scene: bool = True) -> VisionObservation:
        dest = str(self.capture_dir / "screen.png")
        shot = self.captures.capture(dest)
        if not shot.get("ok"):
            obs = VisionObservation(source="screen", path=dest, ok=False,
                                    error=shot.get("error", "capture failed"))
            self.history.append(obs)
            return obs
        return self._finish("screen", dest, question, scene=scene)

    def see_file(self, path: str, question: str = "Describe this image.",
                 scene: bool = True) -> VisionObservation:
        if not Path(path).exists():
            return VisionObservation(source="file", path=path, ok=False,
                                     error=f"no such image: {path}")
        return self._finish("file", path, question, scene=scene)

    def _finish(self, source: str, path: str, question: str,
                scene: bool = True) -> VisionObservation:
        ocr_text = self._ocr_file(path)
        # Scene description runs on CPU (no GPU here) and takes minutes:
        # callers that need speed pass scene=False for the OCR-only fast path.
        scene_text = self._describe(path, question) if scene else ""
        recognized = bool(ocr_text.strip() or scene_text.strip())
        obs = VisionObservation(source=source, path=path, ocr_text=ocr_text,
                                scene=scene_text,
                                objects_noted=self._nouns(scene_text + " " + ocr_text),
                                ok=True,  # capture succeeded; recognition may be empty
                                error="" if recognized else "nothing recognized")
        self.history.append(obs)
        return obs

    @staticmethod
    def _nouns(scene: str) -> list[str]:
        import re
        words = re.findall(r"\b[a-z]{4,}\b", scene.lower())
        stop = {"this", "that", "with", "from", "there", "image", "shows",
                "visible", "appears", "looks", "like", "what", "object"}
        seen: dict[str, None] = {}
        for word in words:
            if word not in stop:
                seen.setdefault(word, None)
        return list(seen)[:12]

    # -- integration ---------------------------------------------------------
    def feed(self, obs: VisionObservation, world: Any = None,
             palace: Any = None, mentalist: Any = None) -> dict[str, Any]:
        """Record one observation into world model + memory + evidence."""
        fed: dict[str, Any] = {"summary": obs.summary()}
        if world is not None:
            record = Observation(kind="visual", content=obs.summary(),
                                 modality="camera" if obs.source == "camera"
                                 else "screen",
                                 source=obs.source, confidence=0.7,
                                 metadata={"path": obs.path,
                                           "objects": obs.objects_noted})
            world.observe(record)
            fed["world"] = True
        if palace is not None:
            mem = palace.store_observation(obs.summary(), room="Observation Room",
                                           source=obs.source, confidence=0.7,
                                           related_entities=obs.objects_noted[:6])
            fed["memory_id"] = mem.id
        if mentalist is not None:
            record = mentalist.observe(obs.summary(), kind="visual",
                                       source=obs.source)
            mentalist.record_facts([record])
            fed["evidence"] = True
        return fed

    def watch(self, world: Any = None, palace: Any = None,
              room: str = "office") -> dict[str, Any]:
        """Room-change detection: capture + OCR fast path (no scene model;
        scene description takes minutes on CPU and runs on demand instead)."""
        obs = self.see_camera(scene=False)
        if not obs.ok or world is None:
            return {"ok": obs.ok, "error": obs.error}
        state = {f"ocr_snippet_{i}": line
                 for i, line in enumerate(obs.ocr_text.splitlines()[:5]) if line.strip()}
        state["objects"] = ",".join(obs.objects_noted[:8])
        world.record_room(room, state, sensor="camera")
        diff = world.room_diff(room)
        if palace is not None and diff.get("has_baseline") and (
                diff["added"] or diff["removed"] or diff["moved"]):
            palace.store_episode(
                f"room {room} changed: added={diff['added']} "
                f"removed={diff['removed']} moved={diff['moved']}",
                room="Experiences", importance=0.6)
        return {"ok": True, "diff": diff, "observation": obs.to_dict()}
