"""OCR abstraction for perception (4.3).

Local-first, optional, honest: when no engine is available the
provider reports ``available: False`` instead of throwing, and every
result says where its confidence came from. Deterministic fakes keep
the test suite hardware-free.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from .contract import MAX_OCR_CHARS, PerceptionError


class OCRProvider:
    """recognize(path) -> {text, confidence, blocks, engine}."""

    name = "ocr"

    def recognize(self, image_path: str | Path) -> dict[str, Any]:
        raise NotImplementedError

    def available(self) -> bool:
        raise NotImplementedError

    def health(self) -> dict[str, Any]:
        return {"provider": self.name, "available": self.available()}

    def capabilities(self) -> dict[str, Any]:
        return {"ocr": self.available(), "confidence": "heuristic",
                "blocks": False}

    def close(self) -> None:
        return None


class TesseractOCR(OCRProvider):
    """CLI tesseract wrapper. No confidence from stdout: non-empty
    output is reported at heuristic 0.6 (labeled as such), empty at
    0.0. Never invents text."""

    name = "tesseract"

    def __init__(self, timeout_s: float = 60.0) -> None:
        self.timeout_s = timeout_s

    def available(self) -> bool:
        return shutil.which("tesseract") is not None

    def recognize(self, image_path: str | Path) -> dict[str, Any]:
        path = Path(image_path)
        if not path.is_file():
            raise PerceptionError(f"ocr input not found: {path}")
        if not self.available():
            return {"text": "", "confidence": 0.0, "blocks": [],
                    "engine": "tesseract",
                    "status": "unavailable"}
        try:
            proc = subprocess.run(
                ["tesseract", str(path), "stdout"],
                capture_output=True, text=True,
                timeout=self.timeout_s)
        except subprocess.TimeoutExpired:
            return {"text": "", "confidence": 0.0, "blocks": [],
                    "engine": "tesseract", "status": "timeout"}
        except OSError as exc:
            return {"text": "", "confidence": 0.0, "blocks": [],
                    "engine": "tesseract",
                    "status": f"error: {exc}"[:120]}
        text = (proc.stdout or "").strip()[:MAX_OCR_CHARS]
        if proc.returncode != 0 or not text:
            return {"text": "", "confidence": 0.0, "blocks": [],
                    "engine": "tesseract", "status": "nothing recognized"}
        return {"text": text, "confidence": 0.6, "blocks": [],
                "engine": "tesseract",
                "confidence_basis": "heuristic: tesseract CLI "
                                    "exposes no confidence",
                "status": "ok"}

    def capabilities(self) -> dict[str, Any]:
        return {"ocr": self.available(), "confidence": "heuristic-0.6",
                "blocks": False, "languages": "tesseract-defaults"}


class UnavailableOCR(OCRProvider):
    """Explicitly incapable provider (unsupported environments)."""

    name = "unavailable"

    def available(self) -> bool:
        return False

    def recognize(self, image_path: str | Path) -> dict[str, Any]:
        return {"text": "", "confidence": 0.0, "blocks": [],
                "engine": "unavailable", "status": "unavailable"}


class FakeOCR(OCRProvider):
    """Deterministic scripted OCR for tests. No hardware, no binaries."""

    name = "fake"

    def __init__(self, text: str = "", confidence: float = 0.9) -> None:
        self._text = text[:MAX_OCR_CHARS]
        self._confidence = confidence
        self.calls = 0

    def available(self) -> bool:
        return True

    def recognize(self, image_path: str | Path) -> dict[str, Any]:
        self.calls += 1
        return {"text": self._text, "confidence": self._confidence,
                "blocks": [], "engine": "fake", "status": "ok"}


__all__ = ["OCRProvider", "TesseractOCR", "UnavailableOCR", "FakeOCR"]
