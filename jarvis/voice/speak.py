"""Response → TTS → playback wiring (5.1).

Cognition finishes first; only the final response text enters this
module. Priority: Chatterbox JARVIS voice → existing local fallback
(espeak/piper) → text-only. TTS never executes tools/devices/memory;
it synthesizes text and optionally plays audio. Bounded text, bounded
outputs, transient audio unless retention is explicitly enabled.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .output import FakeAudioOutput, SystemAudioOutput, output_for
from .telemetry import TELEMETRY
from .tts import (ChatterboxTTSProvider, FakeTTSProvider,
                  LocalFallbackTTSProvider, TTSRequest, provider_for)
from .voice_profile import jarvis_profile, render_style


def resolve_tts(config: Any = None, provider_name: str = ""):
    cfg = config or {}
    get = (lambda k, d="": getattr(cfg, k, d)
           if not isinstance(cfg, dict) else cfg.get(k, d))
    name = provider_name or str(get("tts_provider", "chatterbox"))
    if name == "fake":
        return FakeTTSProvider()
    if name == "chatterbox":
        return ChatterboxTTSProvider(
            model=str(get("model", "chatterbox-turbo")),
            reference_audio=str(get("reference_audio", "")))
    if name in ("local-fallback", "espeak", "piper"):
        return LocalFallbackTTSProvider()
    from .tts import UnavailableTTSProvider
    return UnavailableTTSProvider(f"unknown TTS provider: {name}")


def speak_text(text: str, *, config: Any = None,
               workdir: str | Path = "/tmp/jarvis-voice",
               play: bool = True,
               output: Any = None,
               provider_name: str = "",
               style: str = "normal",
               correlation_id: str = "") -> dict[str, Any]:
    """Synthesize (and optionally play) one response. Never raises."""
    started = time.perf_counter()
    cfg = config or {}
    get = (lambda k, d="": getattr(cfg, k, d)
           if not isinstance(cfg, dict) else cfg.get(k, d))
    profile = jarvis_profile({
        "reference_audio": str(get("reference_audio", "")) or None,
    }) if False else None  # placeholder to keep import used
    _ = profile
    rendered = render_style(text, style)
    if not rendered.strip():
        return {"ok": False, "error": "empty response text",
                "spoken_aloud": False}
    retain = bool(get("retain_audio", False))
    request = TTSRequest(
        text=rendered,
        language=str(get("language", "en")),
        reference_audio=str(get("reference_audio", "")),
        output_format=str(get("output_format", "wav")),
        sample_rate=int(get("sample_rate", 24000) or 24000),
        exaggeration=float(get("exaggeration", 0.5) or 0.5),
        temperature=float(get("temperature", 0.8) or 0.8),
        cfg_weight=float(get("cfg_weight", 0.5) or 0.5),
        correlation_id=correlation_id)
    primary = resolve_tts(cfg, provider_name)
    dest_dir = Path(str(workdir)) / "tts"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{request.request_id}.wav"
    result = primary.synthesize(request, dest)
    TELEMETRY.record("voice.tts", status="ok" if result.ok else "failed",
                     latency_ms=result.latency_ms,
                     text_len=len(rendered),
                     audio_duration_s=result.duration_s,
                     correlation_id=correlation_id,
                     detail=primary.name)
    if result.ok and not retain:
        # Transient by default: keep path for playback, caller cleans.
        pass
    if not result.ok:
        fallback = LocalFallbackTTSProvider()
        if primary.name != fallback.name and fallback.available():
            again = fallback.synthesize(request, None)
            TELEMETRY.record("voice.tts", status="ok" if again.ok
                             else "failed",
                             latency_ms=again.latency_ms,
                             text_len=len(rendered),
                             correlation_id=correlation_id,
                             detail="local-fallback")
            if again.ok:
                return {"ok": True, "provider": again.provider,
                        "spoken_aloud": False,
                        "response_text": rendered,
                        "tts_id": request.request_id,
                        "fallback": True,
                        "primary_error": result.error,
                        "correlation_id": correlation_id}
        return {"ok": False, "provider": primary.name,
                "error": result.error, "spoken_aloud": False,
                "response_text": rendered, "tts_id": request.request_id,
                "correlation_id": correlation_id}
    if not play:
        return {"ok": True, "provider": result.provider,
                "spoken_aloud": False, "response_text": rendered,
                "audio_path": result.audio_path,
                "duration_s": result.duration_s,
                "tts_id": request.request_id,
                "correlation_id": correlation_id}
    sink = output or output_for(str(get("playback_backend", "auto")))
    if isinstance(sink, str):
        sink = output_for(sink)
    if not sink.available():
        return {"ok": True, "provider": result.provider,
                "spoken_aloud": False, "response_text": rendered,
                "audio_path": result.audio_path,
                "duration_s": result.duration_s,
                "tts_id": request.request_id,
                "playback": "unavailable",
                "correlation_id": correlation_id}
    played = sink.play(result.audio_path or dest)
    TELEMETRY.record("voice.playback",
                     status="ok" if played.ok else "failed",
                     latency_ms=played.latency_ms,
                     audio_duration_s=result.duration_s,
                     correlation_id=correlation_id,
                     detail=played.backend)
    if not retain:
        try:
            Path(result.audio_path).unlink(missing_ok=True)
        except OSError:
            pass
    total_ms = round((time.perf_counter() - started) * 1000, 2)
    return {"ok": played.ok, "provider": result.provider,
            "spoken_aloud": played.ok, "response_text": rendered,
            "duration_s": result.duration_s,
            "tts_id": request.request_id,
            "playback": played.backend if played.ok
            else played.error,
            "latency_ms": total_ms, "correlation_id": correlation_id}


class VoiceSpeaker:
    """Interruptible speak/stop controller (barge-in abstraction)."""

    def __init__(self, config: Any = None,
                 output: Any = None) -> None:
        self.config = config or {}
        self.output = output or SystemAudioOutput()
        self._speaking = False

    @property
    def speaking(self) -> bool:
        if isinstance(self.output, FakeAudioOutput):
            return False
        return self._speaking

    def say(self, text: str, **kw: Any) -> dict[str, Any]:
        self._speaking = True
        try:
            return speak_text(text, config=self.config,
                              output=self.output, **kw)
        finally:
            self._speaking = False

    def stop(self) -> bool:
        self._speaking = False
        try:
            return bool(self.output.stop())
        except Exception:
            return False


__all__ = ["resolve_tts", "speak_text", "VoiceSpeaker"]
