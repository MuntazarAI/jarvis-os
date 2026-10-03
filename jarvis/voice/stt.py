"""Speech-to-text provider abstraction (5.1).

Provider-neutral STT: transcribe(segment-audio) -> result. The adapter
never executes tools, never mutates policy, never issues device
commands — it returns text + confidence and stops there. Bounded
retries (default 1 attempt, max 2); failure degrades to FAILED or
UNKNOWN, never an exception storm.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from .audio import MAX_TRANSCRIPT_CHARS, AudioError


class STTStatus(str, Enum):
    SUCCESS = "success"
    LOW_CONFIDENCE = "low_confidence"
    UNKNOWN = "unknown"
    FAILED = "failed"


class STTError(RuntimeError):
    """STT misuse (not a transcription failure — those are results)."""


@dataclass
class SpeechRecognitionResult:
    result_id: str = field(
        default_factory=lambda: f"stt-{uuid.uuid4().hex[:12]}")
    transcript: str = ""
    confidence: float = 0.0
    language: str = ""
    start_timestamp: float = 0.0
    end_timestamp: float = 0.0
    provider: str = ""
    model: str = ""
    provenance: dict[str, Any] = field(default_factory=dict)
    status: STTStatus = STTStatus.UNKNOWN
    error: str = ""
    latency_ms: float = 0.0

    def __post_init__(self) -> None:
        if isinstance(self.status, str):
            try:
                self.status = STTStatus(self.status)
            except ValueError:
                raise STTError(f"invalid status: {self.status!r}")
        self.transcript = str(self.transcript or "")[:MAX_TRANSCRIPT_CHARS]
        try:
            confidence = float(self.confidence)
        except (TypeError, ValueError):
            raise STTError("invalid confidence")
        if not 0.0 <= confidence <= 1.0:
            raise STTError("confidence out of range")
        self.confidence = confidence
        self.language = str(self.language or "")[:16]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


class STTProvider:
    """transcribe(wav_path, segment) -> SpeechRecognitionResult."""

    name = "stt"
    model = ""

    def transcribe(self, wav_path: str | Path,
                   segment: Any = None) -> SpeechRecognitionResult:
        raise NotImplementedError

    def available(self) -> bool:
        raise NotImplementedError

    def health(self) -> dict[str, Any]:
        return {"provider": self.name, "model": self.model,
                "available": self.available()}

    def capabilities(self) -> dict[str, Any]:
        return {"transcribe": self.available(), "network": False}

    def close(self) -> None:
        return None


class FasterWhisperSTT(STTProvider):
    """Local faster-whisper. Lazy import + lazy model (no import cost
    until first use). Exactly one retry on inference failure, then
    FAILED. VAD pre-filter rejects silence before the model runs."""

    name = "faster-whisper"

    def __init__(self, model: str = "tiny", language: str = "",
                 max_retries: int = 1) -> None:
        self.model = model
        self.language = language
        self.max_retries = max(0, min(2, max_retries))
        self._model: Any = None
        self.calls = 0
        self.failures = 0

    def available(self) -> bool:
        try:
            import faster_whisper  # noqa: F401
            return True
        except ImportError:
            return False

    def health(self) -> dict[str, Any]:
        return {"provider": self.name, "model": self.model,
                "available": self.available(),
                "model_loaded": self._model is not None,
                "calls": self.calls, "failures": self.failures}

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        from faster_whisper import WhisperModel
        self._model = WhisperModel(self.model, device="cpu",
                                   compute_type="int8")

    def transcribe(self, wav_path: str | Path,
                   segment: Any = None) -> SpeechRecognitionResult:
        started = time.perf_counter()
        path = Path(wav_path)
        if not path.is_file():
            return SpeechRecognitionResult(
                provider=self.name, model=self.model,
                status=STTStatus.FAILED, error="audio file not found")
        if not self.available():
            return SpeechRecognitionResult(
                provider=self.name, model=self.model,
                status=STTStatus.FAILED,
                error="faster-whisper not installed")
        self.calls += 1
        last_error = ""
        for _ in range(1 + self.max_retries):
            try:
                self._ensure_model()
                segments, info = self._model.transcribe(
                    str(path),
                    language=self.language or None,
                    vad_filter=True)
                text = " ".join(
                    s.text.strip() for s in segments).strip()
                language = str(getattr(info, "language", "")
                               or self.language or "")[:16]
                latency = (time.perf_counter() - started) * 1000.0
                if not text:
                    return SpeechRecognitionResult(
                        provider=self.name, model=self.model,
                        status=STTStatus.UNKNOWN,
                        language=language, latency_ms=round(latency, 1),
                        provenance=_provenance(segment))
                return SpeechRecognitionResult(
                    transcript=text, confidence=0.7, language=language,
                    provider=self.name, model=self.model,
                    status=STTStatus.SUCCESS,
                    latency_ms=round(latency, 1),
                    provenance=_provenance(segment))
            except Exception as exc:
                last_error = f"{type(exc).__name__}"[:120]
        self.failures += 1
        return SpeechRecognitionResult(
            provider=self.name, model=self.model,
            status=STTStatus.FAILED, error=last_error,
            latency_ms=round((time.perf_counter() - started) * 1000.0, 1),
            provenance=_provenance(segment))


def _provenance(segment: Any) -> dict[str, Any]:
    if segment is None:
        return {}
    get = getattr(segment, "segment_id", None)
    return {"segment_id": str(get)[:32]} if get else {}


class FakeSTT(STTProvider):
    """Deterministic scripted transcriber. Fixture bytes -> text map."""

    name = "fake"

    def __init__(self, mapping: dict[bytes, str] | None = None,
                 default: str = "", confidence: float = 0.9) -> None:
        self._mapping = dict(mapping or {})
        self._default = default
        self._confidence = confidence
        self.calls = 0

    def available(self) -> bool:
        return True

    def transcribe(self, wav_path: str | Path,
                   segment: Any = None) -> SpeechRecognitionResult:
        self.calls += 1
        try:
            blob = Path(wav_path).read_bytes()[:65536]
        except OSError:
            return SpeechRecognitionResult(
                provider=self.name, model="fake",
                status=STTStatus.FAILED, error="audio file not found",
                provenance=_provenance(segment))
        text = self._mapping.get(blob, self._default)
        if not text:
            return SpeechRecognitionResult(
                provider=self.name, model="fake",
                status=STTStatus.UNKNOWN,
                provenance=_provenance(segment))
        return SpeechRecognitionResult(
            transcript=text, confidence=self._confidence,
            provider=self.name, model="fake",
            status=STTStatus.SUCCESS, provenance=_provenance(segment))


class UnavailableSTT(STTProvider):
    """Explicitly incapable STT. Structured failure, never an exception."""

    name = "unavailable"

    def available(self) -> bool:
        return False

    def transcribe(self, wav_path: str | Path,
                   segment: Any = None) -> SpeechRecognitionResult:
        return SpeechRecognitionResult(
            provider=self.name, model="",
            status=STTStatus.FAILED, error="no STT provider available",
            provenance=_provenance(segment))


__all__ = [
    "FakeSTT",
    "FasterWhisperSTT",
    "STTError",
    "STTProvider",
    "STTStatus",
    "SpeechRecognitionResult",
    "UnavailableSTT",
]
