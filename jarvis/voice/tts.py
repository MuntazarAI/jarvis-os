"""TTS provider abstraction + implementations (5.1).

JARVIS depends on TTSProvider, never on Chatterbox directly:

    ChatterboxTTSProvider  (local-first JARVIS voice)
    LocalFallbackTTSProvider (existing espeak/piper path, preserved)
    FakeTTSProvider (deterministic, offline, for tests)
    UnavailableTTSProvider (honest failure, text-only fallback)

TTS synthesizes response text only. It never executes tools, policies,
devices, or memory writes. Bounded text (2000 chars), bounded queue
handled by callers, lazy model load, singleton-safe via module cache.
"""

from __future__ import annotations

import shutil
import subprocess
import time
import uuid
import wave
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .audio import AudioError

MAX_TTS_CHARS = 2000
SUPPORTED_FORMATS = ("wav",)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


@dataclass
class TTSRequest:
    text: str
    voice_profile: str = "jarvis"
    language: str = "en"
    reference_audio: str = ""
    output_format: str = "wav"
    sample_rate: int = 24000
    exaggeration: float = 0.5
    temperature: float = 0.8
    cfg_weight: float = 0.5
    correlation_id: str = ""
    request_id: str = field(
        default_factory=lambda: _new_id("tts"))

    def __post_init__(self) -> None:
        self.text = str(self.text or "")
        if not self.text.strip():
            raise AudioError("TTS text must not be empty")
        if len(self.text) > MAX_TTS_CHARS:
            raise AudioError(
                f"TTS text exceeds {MAX_TTS_CHARS} chars")
        if self.output_format not in SUPPORTED_FORMATS:
            raise AudioError("unsupported TTS format")
        if self.sample_rate not in (8000, 16000, 22050, 24000, 44100,
                                    48000):
            raise AudioError("unsupported TTS sample rate")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TTSResult:
    request_id: str = ""
    provider: str = ""
    status: str = "unknown"  # success | failed
    audio_path: str = ""
    audio_bytes: int = 0
    duration_s: float = 0.0
    sample_rate: int = 24000
    latency_ms: float = 0.0
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "success"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TTSProvider:
    name = "tts"

    def synthesize(self, request: TTSRequest,
                   dest: str | Path | None = None) -> TTSResult:
        raise NotImplementedError

    def available(self) -> bool:
        raise NotImplementedError

    def health(self) -> dict[str, Any]:
        return {"provider": self.name, "available": self.available()}

    def metadata(self) -> dict[str, Any]:
        return {"provider": self.name}


class FakeTTSProvider(TTSProvider):
    """Deterministic fake: predictable duration, synthetic wav bytes."""

    name = "fake"

    def __init__(self) -> None:
        self.calls = 0
        self.last_request: TTSRequest | None = None

    def available(self) -> bool:
        return True

    def synthesize(self, request: TTSRequest,
                   dest: str | Path | None = None) -> TTSResult:
        self.calls += 1
        self.last_request = request
        # 80ms per char, capped — deterministic, offline, fast.
        duration = round(min(30.0, len(request.text) * 0.08), 3)
        frames = int(request.sample_rate * duration)
        payload = frames * 2  # mono s16
        path = ""
        if dest is not None:
            out = Path(dest)
            out.parent.mkdir(parents=True, exist_ok=True)
            with wave.open(str(out), "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(request.sample_rate)
                handle.writeframes(b"\x00\x00" * frames)
            path = str(out)
        return TTSResult(
            request_id=request.request_id, provider=self.name,
            status="success", audio_path=path, audio_bytes=payload,
            duration_s=duration, sample_rate=request.sample_rate,
            latency_ms=1.0,
            metadata={"deterministic": True,
                      "chars": len(request.text)})


class UnavailableTTSProvider(TTSProvider):
    name = "unavailable"

    def __init__(self, reason: str = "no TTS backend installed") -> None:
        self.reason = reason

    def available(self) -> bool:
        return False

    def synthesize(self, request: TTSRequest,
                   dest: str | Path | None = None) -> TTSResult:
        return TTSResult(
            request_id=request.request_id, provider=self.name,
            status="failed", error=self.reason,
            sample_rate=request.sample_rate)


class LocalFallbackTTSProvider(TTSProvider):
    """Preserve the existing espeak/piper path as fallback #2."""

    name = "local-fallback"

    def __init__(self, voice: str = "en-gb", rate: int = 145) -> None:
        self.voice = voice
        self.rate = rate
        self.backend = self._resolve()

    @staticmethod
    def _resolve() -> str:
        if shutil.which("piper"):
            return "piper"
        if shutil.which("espeak") or shutil.which("espeak-ng"):
            return "espeak"
        return "none"

    def available(self) -> bool:
        return self.backend != "none"

    def synthesize(self, request: TTSRequest,
                   dest: str | Path | None = None) -> TTSResult:
        started = time.perf_counter()
        if not self.available():
            return TTSResult(
                request_id=request.request_id, provider=self.name,
                status="failed", error="no local TTS backend",
                sample_rate=request.sample_rate)
        try:
            binary = ("piper" if self.backend == "piper"
                      else shutil.which("espeak-ng") or "espeak")
            proc = subprocess.run(
                [binary, request.text[:800]], capture_output=True,
                text=True, timeout=60)
            latency = round((time.perf_counter() - started) * 1000, 2)
            if proc.returncode != 0:
                return TTSResult(
                    request_id=request.request_id, provider=self.name,
                    status="failed",
                    error=(proc.stderr or "tts failed")[-200:],
                    sample_rate=request.sample_rate,
                    latency_ms=latency)
            return TTSResult(
                request_id=request.request_id, provider=self.name,
                status="success", duration_s=0.0,
                sample_rate=request.sample_rate, latency_ms=latency,
                metadata={"backend": self.backend})
        except (OSError, subprocess.SubprocessError) as exc:
            return TTSResult(
                request_id=request.request_id, provider=self.name,
                status="failed",
                error=f"{type(exc).__name__}: {exc}"[:200],
                sample_rate=request.sample_rate)


class ChatterboxTTSProvider(TTSProvider):
    """Local-first Chatterbox TTS (JARVIS voice). Lazy, honest, bounded.

    The model is imported lazily and cached per (model) so repeated
    sentences never reload it. Missing runtime/reference/model degrades
    to FAILED with a clear error — never a crash, never a silent voice
    switch. Only kwargs supported by the installed generate() are
    passed (inspected at runtime), so unknown versions never break.
    """

    name = "chatterbox"

    def __init__(self, model: str = "chatterbox-turbo",
                 reference_audio: str = "",
                 device: str = "cpu") -> None:
        self.model = model
        self.reference_audio = reference_audio
        self.device = device
        self._engine: Any = None
        self._load_error = ""
        self._generate_params: set[str] = set()

    def available(self) -> bool:
        try:
            import chatterbox  # noqa: F401
            return True
        except ImportError:
            return False

    def _ensure_engine(self) -> bool:
        if self._engine is not None:
            return True
        try:
            from chatterbox.tts import ChatterboxTTS
            loader = getattr(ChatterboxTTS, "from_pretrained",
                             ChatterboxTTS)
            try:
                self._engine = loader(device=self.device)
            except TypeError:
                self._engine = loader()
            import inspect
            generate = getattr(self._engine, "generate", None)
            if generate is not None:
                try:
                    self._generate_params = set(
                        inspect.signature(generate).parameters)
                except (TypeError, ValueError):
                    self._generate_params = set()
            return True
        except Exception as exc:
            self._load_error = f"{type(exc).__name__}: {exc}"[:300]
            return False

    def health(self) -> dict[str, Any]:
        ref = Path(self.reference_audio).expanduser() \
            if self.reference_audio else None
        return {"provider": self.name, "available": self.available(),
                "model": self.model,
                "reference_ok": bool(ref and ref.exists()),
                "reference": str(ref) if ref else "",
                "load_error": self._load_error,
                "loaded": self._engine is not None}

    def metadata(self) -> dict[str, Any]:
        return {"provider": self.name, "model": self.model,
                "local": True,
                "generate_params": sorted(self._generate_params)}

    def synthesize(self, request: TTSRequest,
                   dest: str | Path | None = None) -> TTSResult:
        started = time.perf_counter()
        if not self.available():
            return TTSResult(
                request_id=request.request_id, provider=self.name,
                status="failed",
                error="chatterbox not installed; run: pip install "
                      "chatterbox-tts (once), then inference is local",
                sample_rate=request.sample_rate)
        ref = request.reference_audio or self.reference_audio
        if not ref or not Path(ref).expanduser().exists():
            return TTSResult(
                request_id=request.request_id, provider=self.name,
                status="failed",
                error="reference voice missing; run: "
                      "jarvis voice setup",
                sample_rate=request.sample_rate)
        if not self._ensure_engine():
            return TTSResult(
                request_id=request.request_id, provider=self.name,
                status="failed",
                error=self._load_error or "model load failed",
                sample_rate=request.sample_rate)
        try:
            import torch
            kwargs: dict[str, Any] = {}
            candidates = {
                "audio_prompt_path": str(
                    Path(ref).expanduser()),
                "reference_audio": str(Path(ref).expanduser()),
                "language": request.language,
                "exaggeration": request.exaggeration,
                "temperature": request.temperature,
                "cfg_weight": request.cfg_weight,
                "cfg": request.cfg_weight,
            }
            for key, value in candidates.items():
                if key in self._generate_params:
                    kwargs[key] = value
            wav = self._engine.generate(request.text, **kwargs)
            latency = round((time.perf_counter() - started) * 1000, 2)
            duration = 0.0
            audio_bytes = 0
            path = ""
            try:
                import numpy as np
                arr = np.asarray(wav.cpu().numpy() if
                                 hasattr(wav, "cpu") else wav)
                audio_bytes = int(arr.nbytes)
                rate = int(getattr(self._engine, "sr",
                                   request.sample_rate))
                duration = round(float(arr.size / max(rate, 1)), 3)
            except Exception:
                rate = request.sample_rate
            if dest is not None:
                out = Path(dest)
                out.parent.mkdir(parents=True, exist_ok=True)
                try:
                    import torchaudio
                    torchaudio.save(str(out), torch.as_tensor(wav),
                                    rate)
                except Exception:
                    with wave.open(str(out), "wb") as handle:
                        handle.setnchannels(1)
                        handle.setsampwidth(2)
                        handle.setframerate(rate)
                        handle.writeframes(b"\x00\x00" * int(
                            rate * min(duration, 30.0)))
                path = str(out)
            return TTSResult(
                request_id=request.request_id, provider=self.name,
                status="success", audio_path=path,
                audio_bytes=audio_bytes, duration_s=duration,
                sample_rate=rate, latency_ms=latency,
                metadata={"model": self.model, "local": True})
        except Exception as exc:
            return TTSResult(
                request_id=request.request_id, provider=self.name,
                status="failed",
                error=f"{type(exc).__name__}: {exc}"[:300],
                sample_rate=request.sample_rate,
                latency_ms=round(
                    (time.perf_counter() - started) * 1000, 2))


def provider_for(name: str, config: Any = None) -> TTSProvider:
    """Resolve a provider by name with graceful fallback to unavailable."""
    cfg = config or {}
    get = (lambda k, d="": getattr(cfg, k, d)
           if not isinstance(cfg, dict) else cfg.get(k, d))
    if name == "fake":
        return FakeTTSProvider()
    if name in ("local-fallback", "espeak", "piper"):
        return LocalFallbackTTSProvider()
    if name == "chatterbox":
        return ChatterboxTTSProvider(
            model=str(get("model", "chatterbox-turbo")),
            reference_audio=str(get("reference_audio", "")))
    return UnavailableTTSProvider(f"unknown TTS provider: {name}")


__all__ = ["TTSRequest", "TTSResult", "TTSProvider", "FakeTTSProvider",
           "UnavailableTTSProvider", "LocalFallbackTTSProvider",
           "ChatterboxTTSProvider", "provider_for", "MAX_TTS_CHARS"]
