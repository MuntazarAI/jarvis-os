"""Vision pipeline: capture sources, OCR, detection behind swappable backends."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class VisionConfig:
    camera_backend: str = "auto"  # auto | fswebcam | ffmpeg | none
    ocr_backend: str = "auto"  # auto | tesseract | none
    capture_dir: str = "captures"


class ScreenCapture:
    def __init__(self, display: str = ":0") -> None:
        self.display = display

    @staticmethod
    def available() -> bool:
        return (shutil.which("gnome-screenshot") is not None
                or shutil.which("scrot") is not None
                or shutil.which("import") is not None
                or shutil.which("ffmpeg") is not None)

    def capture(self, dest: str) -> dict[str, Any]:
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        for binary, args in (
            ("gnome-screenshot", ["-f", dest]),
            ("scrot", [dest]),
            ("import", ["-window", "root", dest]),
        ):
            if shutil.which(binary) is None:
                continue
            try:
                proc = subprocess.run([binary, *args], capture_output=True,
                                      text=True, timeout=30)
                if proc.returncode == 0 and Path(dest).exists():
                    return {"ok": True, "path": dest, "backend": binary}
            except (OSError, subprocess.SubprocessError):
                continue
        # Fallback verified on GNOME/Wayland: x11grab sees the XWayland
        # layer (full 1920x1080 frame). Full-compositor capture needs
        # portal consent and is reported, not faked.
        if shutil.which("ffmpeg") is not None:
            try:
                proc = subprocess.run(
                    ["ffmpeg", "-y", "-v", "error", "-f", "x11grab",
                     "-i", self.display, "-frames:v", "1", dest],
                    capture_output=True, text=True, timeout=20)
                if proc.returncode == 0 and Path(dest).exists():
                    if Path(dest).stat().st_size < 1000:
                        return {"ok": False, "error": "capture is blank",
                                "note": "portal consent needed"}
                    return {"ok": True, "path": dest, "backend": "ffmpeg-x11grab",
                            "scope": "x11grab (XWayland layer)"}
            except (OSError, subprocess.SubprocessError):
                pass
        return {"ok": False, "error": "no screen capture tool available"}


class CameraCapture:
    def __init__(self, backend: str = "auto") -> None:
        self.backend = self._resolve(backend)

    @staticmethod
    def _resolve(backend: str) -> str:
        if backend != "auto":
            return backend
        if shutil.which("fswebcam"):
            return "fswebcam"
        if shutil.which("ffmpeg"):
            return "ffmpeg"
        return "none"

    def available(self) -> bool:
        return self.backend != "none"

    def capture(self, dest: str, device: str = "/dev/video0") -> dict[str, Any]:
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        if not self.available():
            return {"ok": False, "error": "no camera backend installed"}
        try:
            if self.backend == "fswebcam":
                cmd = ["fswebcam", "-d", device, "--no-banner", dest]
            else:
                cmd = ["ffmpeg", "-y", "-f", "v4l2", "-i", device,
                       "-frames:v", "1", dest]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if proc.returncode == 0 and Path(dest).exists():
                return {"ok": True, "path": dest, "backend": self.backend}
            return {"ok": False, "error": proc.stderr[-500:]}
        except (OSError, subprocess.SubprocessError) as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


class OCREngine:
    def __init__(self, backend: str = "auto") -> None:
        self.backend = self._resolve(backend)

    @staticmethod
    def _resolve(backend: str) -> str:
        if backend != "auto":
            return backend
        if shutil.which("tesseract"):
            return "tesseract"
        return "none"

    def available(self) -> bool:
        return self.backend != "none"

    def read(self, image_path: str) -> dict[str, Any]:
        if not self.available():
            return {"ok": False, "error": "tesseract not installed"}
        if not Path(image_path).exists():
            return {"ok": False, "error": f"no such image: {image_path}"}
        try:
            proc = subprocess.run(["tesseract", image_path, "stdout"],
                                  capture_output=True, text=True, timeout=60)
            if proc.returncode != 0:
                return {"ok": False, "error": proc.stderr[-500:]}
            return {"ok": True, "text": proc.stdout.strip(), "backend": self.backend}
        except (OSError, subprocess.SubprocessError) as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@dataclass
class VisionPipeline:
    config: VisionConfig = field(default_factory=VisionConfig)
    screen: ScreenCapture = field(default_factory=ScreenCapture)
    camera: CameraCapture = field(default_factory=CameraCapture)
    ocr: OCREngine = field(default_factory=OCREngine)
    observations: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.camera = CameraCapture(self.config.camera_backend)
        self.ocr = OCREngine(self.config.ocr_backend)

    def describe(self, image_path: str) -> dict[str, Any]:
        """Best-effort scene note: OCR text plus file facts. Honest limits."""
        result: dict[str, Any] = {"path": image_path, "seen": []}
        path = Path(image_path)
        if not path.exists():
            return {"ok": False, "error": f"no such image: {image_path}"}
        result["ok"] = True
        result["bytes"] = path.stat().st_size
        ocr = self.ocr.read(image_path)
        if ocr.get("ok"):
            result["seen"].append(f"text: {ocr['text'][:500]}")
        else:
            result["seen"].append(f"ocr unavailable ({ocr.get('error', '')[:80]})")
        result["note"] = ("Vision model not installed: reporting OCR and file "
                          "facts only, no scene description.")
        self.observations.append(result)
        return result

    def status(self) -> dict[str, Any]:
        return {"screen": self.screen.available(), "camera": self.camera.backend,
                "ocr": self.ocr.backend, "observations": len(self.observations)}
