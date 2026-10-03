"""Perception providers: screen, camera, image, file (4.3).

Providers are READ-ONLY observers with explicit lifecycles. They never
act, never open sockets, never run forever: camera sampling is
caller-driven and bounded, files are single explicit paths, captures go
to bounded temp dirs. Unavailable hardware/capabilities produce
structured ``available: False`` results — never fabricated data.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from .contract import (
    MAX_DIMENSION_PX,
    MAX_FILE_BYTES,
    MAX_FRAME_BYTES,
    MAX_METADATA_KEYS,
    MAX_OBJECTS,
    MAX_TEXT_CHARS,
    Modality,
    Observation,
    PerceptionError,
    PrivacyClass,
    redact_secret_spans,
    summarize_text,
    validate_confidence,
    validate_object,
)
from .objects import ObjectPerceptionProvider, UnavailableObjects
from .ocr import OCRProvider, TesseractOCR, UnavailableOCR

CAPTURE_DIR_PREFIX = "jarvis-perception-"
MAX_SAMPLE_FRAMES = 10
MIN_SAMPLE_INTERVAL_S = 1.0
MAX_TEXT_READ_BYTES = 256 * 1024


class PerceptionProvider:
    """observe(...) -> Observation. health/capabilities/close included."""

    name = "provider"
    modality = Modality.SENSOR

    def observe(self, **kwargs: Any) -> Observation:
        raise NotImplementedError

    def health(self) -> dict[str, Any]:
        return {"provider": self.name, "available": True}

    def capabilities(self) -> dict[str, Any]:
        return {}

    def close(self) -> None:
        return None


def _capture_dir() -> Path:
    base = Path(tempfile.gettempdir()) / (CAPTURE_DIR_PREFIX +
                                          str(os.getpid()))
    base.mkdir(parents=True, exist_ok=True)
    return base


def _sha256_file(path: Path, limit_bytes: int = MAX_FILE_BYTES) -> str:
    digest = hashlib.sha256()
    remaining = limit_bytes
    with open(path, "rb") as handle:
        while remaining > 0:
            chunk = handle.read(min(65536, remaining))
            if not chunk:
                break
            digest.update(chunk)
            remaining -= len(chunk)
    return digest.hexdigest()


def _image_magic(path: Path) -> str:
    try:
        with open(path, "rb") as handle:
            head = handle.read(16)
    except OSError:
        return ""
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head.startswith(b"GIF87a") or head.startswith(b"GIF89a"):
        return "gif"
    if head.startswith(b"BM"):
        return "bmp"
    if head.startswith(b"II*\x00") or head.startswith(b"MM\x00*"):
        return "tiff"
    return ""


def _image_dimensions(path: Path, kind: str) -> tuple[int, int]:
    """Best-effort dimensions without new dependencies (0 = unknown)."""
    try:
        from PIL import Image as _PILImage  # optional, never required
        with _PILImage.open(path) as img:
            width, height = img.size
            if 0 < width <= MAX_DIMENSION_PX \
                    and 0 < height <= MAX_DIMENSION_PX:
                return width, height
            return 0, 0
    except ImportError:
        pass
    except Exception:
        pass
    if kind == "png":
        try:
            with open(path, "rb") as handle:
                data = handle.read(33)
            if len(data) >= 33:
                import struct
                width, height = struct.unpack(">II", data[16:24])
                if 0 < width <= MAX_DIMENSION_PX \
                        and 0 < height <= MAX_DIMENSION_PX:
                    return width, height
        except (OSError, struct.error):
            pass
    return 0, 0


class ScreenProvider(PerceptionProvider):
    """One-shot screen observation: capture + OCR + window metadata."""

    name = "screen"
    modality = Modality.SCREEN

    def __init__(self, ocr: OCRProvider | None = None) -> None:
        self._ocr = ocr or TesseractOCR()
        try:
            from ..vision.pipeline import ScreenCapture
            self._capture = ScreenCapture()
        except ImportError:
            self._capture = None

    def capabilities(self) -> dict[str, Any]:
        capture = self._capture.available() if self._capture else False
        return {"screenshot": bool(capture),
                "ocr": self._ocr.available(),
                "window_metadata": shutil.which("xdotool") is not None}

    def health(self) -> dict[str, Any]:
        caps = self.capabilities()
        return {"provider": self.name, "available": caps["screenshot"],
                "detail": caps}

    def _window_metadata(self) -> dict[str, str]:
        if shutil.which("xdotool") is None:
            return {}
        try:
            proc = subprocess.run(
                ["xdotool", "getactivewindow", "getwindowname"],
                capture_output=True, text=True, timeout=10)
        except (subprocess.TimeoutExpired, OSError):
            return {}
        if proc.returncode != 0:
            return {}
        title = (proc.stdout or "").strip()[:200]
        return {"window_title": title} if title else {}

    def observe(self, **kwargs: Any) -> Observation:
        if self._capture is None or not self._capture.available():
            return Observation(
                source="screen-provider", modality=Modality.SCREEN,
                payload={"status": "unavailable",
                         "detail": "no screenshot backend "
                                   "(need gnome-screenshot/scrot/ffmpeg)"},
                confidence=0.0,
                provenance={"provider": self.name},
                privacy_class=PrivacyClass.LOCAL)
        dest = _capture_dir() / f"screen-{int(time.time())}.png"
        try:
            self._capture.capture(str(dest))
        except Exception as exc:
            return Observation(
                source="screen-provider", modality=Modality.SCREEN,
                payload={"status": "error",
                         "detail": f"{type(exc).__name__}"[:120]},
                confidence=0.0,
                provenance={"provider": self.name},
                privacy_class=PrivacyClass.LOCAL)
        try:
            if dest.stat().st_size > MAX_FRAME_BYTES:
                return Observation(
                    source="screen-provider", modality=Modality.SCREEN,
                    payload={"status": "error",
                             "detail": "capture exceeds frame bound"},
                    confidence=0.0,
                    provenance={"provider": self.name},
                    privacy_class=PrivacyClass.LOCAL)
        except OSError:
            pass
        ocr = self._ocr.recognize(dest)
        meta = self._window_metadata()
        try:
            dest.unlink(missing_ok=True)
        except OSError:
            pass
        text = str(ocr.get("text", ""))[:4000]
        text, secret_kinds = redact_secret_spans(text)
        provenance: dict[str, Any] = {
            "provider": self.name,
            "ocr_engine": str(ocr.get("engine", "")),
            "confidence_basis": str(ocr.get(
                "confidence_basis", "capture succeeded"))}
        if secret_kinds:
            provenance["spans_redacted"] = True
        return Observation(
            source="screen-provider", modality=Modality.SCREEN,
            payload={"status": "ok", "visible_text": text,
                     "ui_elements": [],
                     "active_app": "", "window_title": meta.get(
                         "window_title", ""),
                     "width_px": 0, "height_px": 0,
                     "ocr_confidence": float(ocr.get("confidence", 0.0)
                                             or 0.0)},
            confidence=0.6 if text else 0.3,
            provenance=provenance,
            privacy_class=PrivacyClass.LOCAL)


class CameraProvider(PerceptionProvider):
    """Bounded camera: explicit start/stop, one-shot or N-sample reads."""

    name = "camera"
    modality = Modality.CAMERA

    def __init__(self, ocr: OCRProvider | None = None,
                 objects: ObjectPerceptionProvider | None = None,
                 device: str = "/dev/video0") -> None:
        self._ocr = ocr or UnavailableOCR()
        self._objects = objects or UnavailableObjects()
        self._device = device
        self._started = False
        try:
            from ..vision.pipeline import CameraCapture
            self._capture = CameraCapture()
        except ImportError:
            self._capture = None

    def capabilities(self) -> dict[str, Any]:
        camera = self._capture.available() if self._capture else False
        return {"camera": bool(camera), "ocr": self._ocr.available(),
                "objects": self._objects.available(),
                "single_shot": True, "bounded_sampling": True}

    def health(self) -> dict[str, Any]:
        caps = self.capabilities()
        return {"provider": self.name, "available": caps["camera"],
                "started": self._started, "detail": caps}

    def start(self) -> dict[str, Any]:
        if self._capture is None or not self._capture.available():
            return {"started": False,
                    "detail": "no camera backend (need fswebcam/ffmpeg "
                              "and a video device)"}
        self._started = True
        return {"started": True, "device": self._device}

    def stop(self) -> None:
        self._started = False

    def close(self) -> None:
        self.stop()

    def observe_once(self) -> Observation:
        if not self._started:
            return Observation(
                source="camera-provider", modality=Modality.CAMERA,
                payload={"status": "error",
                         "detail": "camera not started (call start())"},
                confidence=0.0,
                provenance={"provider": self.name},
                privacy_class=PrivacyClass.LOCAL)
        if self._capture is None or not self._capture.available():
            return Observation(
                source="camera-provider", modality=Modality.CAMERA,
                payload={"status": "unavailable",
                         "detail": "no camera backend"},
                confidence=0.0,
                provenance={"provider": self.name},
                privacy_class=PrivacyClass.LOCAL)
        dest = _capture_dir() / f"camera-{int(time.time())}.jpg"
        try:
            self._capture.capture(str(dest), device=self._device)
        except TypeError:
            try:
                self._capture.capture(str(dest))
            except Exception as exc:
                return self._capture_error(exc)
        except Exception as exc:
            return self._capture_error(exc)
        try:
            if dest.stat().st_size > MAX_FRAME_BYTES:
                return self._capture_error(
                    ValueError("frame exceeds frame bound"))
        except OSError:
            pass
        ocr = self._ocr.recognize(dest)
        objects = self._objects.detect(dest)
        try:
            dest.unlink(missing_ok=True)
        except OSError:
            pass
        return Observation(
            source="camera-provider", modality=Modality.CAMERA,
            payload={"status": "ok",
                     "objects": objects,
                     "scene": summarize_text(str(ocr.get("text", "")),
                                             limit=500),
                     "frame_ref": ""},
            confidence=0.6 if (ocr.get("text") or objects) else 0.3,
            provenance={"provider": self.name,
                        "ocr_engine": str(ocr.get("engine", ""))},
            privacy_class=PrivacyClass.LOCAL)

    def _capture_error(self, exc: Exception) -> Observation:
        return Observation(
            source="camera-provider", modality=Modality.CAMERA,
            payload={"status": "error",
                     "detail": f"{type(exc).__name__}"[:120]},
            confidence=0.0,
            provenance={"provider": self.name},
            privacy_class=PrivacyClass.LOCAL)

    def sample(self, count: int = 1,
               interval_s: float = MIN_SAMPLE_INTERVAL_S) -> list[Observation]:
        """Bounded multi-frame sampling. No infinite loops, ever."""
        count = max(1, min(int(count), MAX_SAMPLE_FRAMES))
        interval = max(float(interval_s), MIN_SAMPLE_INTERVAL_S)
        out: list[Observation] = []
        for _ in range(count):
            out.append(self.observe_once())
            if len(out) < count:
                time.sleep(interval)
        return out

    def observe(self, **kwargs: Any) -> Observation:
        return self.observe_once()


class ImageProvider(PerceptionProvider):
    """File-image observation: metadata + OCR + objects, no raw bytes."""

    name = "image"
    modality = Modality.IMAGE

    def __init__(self, ocr: OCRProvider | None = None,
                 objects: ObjectPerceptionProvider | None = None) -> None:
        self._ocr = ocr or UnavailableOCR()
        self._objects = objects or UnavailableObjects()

    def capabilities(self) -> dict[str, Any]:
        return {"metadata": True, "ocr": self._ocr.available(),
                "objects": self._objects.available()}

    def observe(self, path: str = "", **kwargs: Any) -> Observation:
        target = self._safe_path(path)
        kind = _image_magic(target)
        if not kind:
            return self._unsupported(target, "not a recognized image")
        size = target.stat().st_size
        if size > MAX_FRAME_BYTES:
            return self._unsupported(target, "image exceeds frame bound")
        width, height = _image_dimensions(target, kind)
        ocr = self._ocr.recognize(target)
        objects = self._objects.detect(target)
        text = str(ocr.get("text", ""))[:4000]
        text, secret_kinds = redact_secret_spans(text)
        payload: dict[str, Any] = {"status": "ok", "path": str(target),
                     "width_px": width, "height_px": height,
                     "objects": objects, "ocr_text": text,
                     "ocr_confidence": float(ocr.get("confidence", 0.0)
                                             or 0.0),
                     "content_hash": _sha256_file(target)}
        if secret_kinds:
            payload["spans_redacted"] = True
        return Observation(
            source="image-provider", modality=Modality.IMAGE,
            payload=payload,
            confidence=0.7 if (text or objects) else 0.4,
            provenance={"provider": self.name, "format": kind,
                        "ocr_engine": str(ocr.get("engine", ""))},
            privacy_class=PrivacyClass.LOCAL)

    @staticmethod
    def _safe_path(path: str) -> Path:
        if not path:
            raise PerceptionError("image path is required")
        target = Path(path).expanduser()
        try:
            resolved = target.resolve()
        except OSError:
            raise PerceptionError(f"cannot resolve image path: {path}")
        if not resolved.is_file():
            raise PerceptionError(f"not a file: {path}")
        return resolved

    def _unsupported(self, target: Path, detail: str) -> Observation:
        return Observation(
            source="image-provider", modality=Modality.IMAGE,
            payload={"status": "unsupported", "path": str(target),
                     "detail": detail},
            confidence=0.0,
            provenance={"provider": self.name},
            privacy_class=PrivacyClass.LOCAL)


class FileProvider(PerceptionProvider):
    """Bounded observation of explicit file paths (no crawling)."""

    name = "file"
    modality = Modality.FILE

    SUPPORTED_SUFFIXES = (".txt", ".md", ".markdown", ".json", ".csv",
                          ".log", ".yaml", ".yml", ".toml", ".ini")
    MAX_CSV_ROWS = 5000
    MAX_CSV_ROWS = 5000

    #: Credential stores and equivalent are never readable, even when
    #: explicitly requested (fail closed; observing them would launder
    #: secrets into memory/world through summaries).
    BLOCKED_PATHS = ("/etc/shadow", "/etc/sudoers", "/etc/gshadow",
                     "/etc/master.passwd")
    BLOCKED_NAMES = ("id_rsa", "id_ed25519", "id_ecdsa", ".pem", ".key",
                     ".p12", ".pfx", "secrets.json", ".env", ".netrc",
                     "_history", "credentials.json", "cookies.sqlite",
                     "Login Data", "keystore", "wallet.dat")

    @classmethod
    def _refuse_sensitive(cls, resolved: Path, original: str) -> None:
        text = str(resolved)
        for blocked in cls.BLOCKED_PATHS:
            if text == blocked or text.startswith(blocked + "/"):
                raise PerceptionError(
                    f"refusing credential store: {original}")
        name = resolved.name
        for blocked in cls.BLOCKED_NAMES:
            if blocked in name:
                raise PerceptionError(
                    f"refusing credential store: {original}")

    def capabilities(self) -> dict[str, Any]:
        return {"text": True, "json": True, "csv": True, "markdown": True,
                "yaml": False, "toml": False,
                "note": "yaml/toml need optional parsers; "
                        "structured unsupported otherwise"}

    def observe(self, path: str = "", **kwargs: Any) -> Observation:
        if not path:
            raise PerceptionError("file path is required")
        target = Path(path).expanduser()
        try:
            resolved = target.resolve()
        except OSError:
            raise PerceptionError(f"cannot resolve path: {path}")
        if not resolved.is_file():
            raise PerceptionError(f"not a file: {path}")
        self._refuse_sensitive(resolved, path)
        try:
            size = resolved.stat().st_size
        except OSError:
            raise PerceptionError(f"cannot stat path: {path}")
        if size > MAX_FILE_BYTES:
            raise PerceptionError(f"file exceeds {MAX_FILE_BYTES} bytes")
        suffix = resolved.suffix.lower()
        if suffix not in self.SUPPORTED_SUFFIXES:
            kind = _image_magic(resolved)
            if kind:
                return Observation(
                    source="file-provider", modality=Modality.FILE,
                    payload={"status": "ok", "path": str(resolved),
                             "file_type": "image/" + kind,
                             "size_bytes": size,
                             "content_hash": _sha256_file(resolved),
                             "summary": f"{kind} image, "
                                        f"{size} bytes (metadata only)"},
                    confidence=0.5,
                    provenance={"provider": self.name},
                    privacy_class=PrivacyClass.LOCAL)
            raise PerceptionError(f"unsupported file type: {suffix or '(none)'}")
        try:
            text = resolved.read_text(encoding="utf-8",
                                      errors="replace")[:MAX_TEXT_READ_BYTES]
        except OSError as exc:
            raise PerceptionError(f"cannot read file: {exc}"[:160])
        summary, metadata = self._summarize(suffix, text)
        return Observation(
            source="file-provider", modality=Modality.FILE,
            payload={"status": "ok", "path": str(resolved),
                     "file_type": suffix.lstrip(".") or "text",
                     "size_bytes": size,
                     "content_hash": _sha256_file(resolved),
                     "summary": summary, "metadata": metadata},
            confidence=0.8,
            provenance={"provider": self.name},
            privacy_class=PrivacyClass.LOCAL)

    def _summarize(self, suffix: str,
                   text: str) -> tuple[str, dict[str, Any]]:
        if suffix == ".json":
            try:
                data = json.loads(text)
            except ValueError as exc:
                raise PerceptionError(f"invalid JSON: {exc}"[:160])
            if isinstance(data, dict):
                keys = sorted(map(str, data.keys()))[:MAX_METADATA_KEYS]
                return (f"JSON object, {len(data)} keys: "
                        f"{', '.join(keys)}"[:500],
                        {"keys": keys, "count": len(data)})
            if isinstance(data, list):
                return (f"JSON array, {len(data)} items"[:200],
                        {"count": len(data)})
            return (f"JSON {type(data).__name__}"[:200], {})
        if suffix == ".csv":
            try:
                reader = csv.reader(text.splitlines())
                header: list[str] = []
                count = 0
                for i, row in enumerate(reader):
                    if i == 0:
                        header = [str(c)[:64] for c in row][:MAX_METADATA_KEYS]
                    count += 1
                    if count > FileProvider.MAX_CSV_ROWS:
                        break
            except csv.Error as exc:
                raise PerceptionError(f"invalid CSV: {exc}"[:160])
            truncated = count > FileProvider.MAX_CSV_ROWS
            return (f"CSV {count} rows"
                    f"{'+' if truncated else ''}, "
                    f"columns: {', '.join(header)}"[:500],
                    {"columns": header, "rows": count,
                     "truncated": truncated})
        if suffix in (".md", ".markdown"):
            headings = [line.strip("# ").strip()[:120]
                        for line in text.splitlines()
                        if line.startswith("#")][:20]
            body = "\n".join(line for line in text.splitlines()
                             if line.strip())[:2000]
            return (f"Markdown, {len(headings)} headings"[:200],
                    {"headings": headings, "text": body})
        lines = text.splitlines()
        return (f"text, {len(lines)} lines"[:200],
                {"lines": len(lines),
                 "text": "\n".join(lines)[:2000]})


__all__ = [
    "PerceptionProvider",
    "ScreenProvider",
    "CameraProvider",
    "ImageProvider",
    "FileProvider",
]
