"""Structured voice telemetry (5.1).

Bounded in-memory counters + recent-event ring for voice.request /
voice.stt / voice.tts / voice.playback / voice.error. Never stores raw
speech, transcripts, secrets, or audio — only lengths, latencies,
statuses, and correlation ids.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class VoiceEvent:
    name: str
    at: float = field(default_factory=time.time)
    status: str = ""
    latency_ms: float = 0.0
    text_len: int = 0
    audio_duration_s: float = 0.0
    correlation_id: str = ""
    detail: str = ""


class VoiceTelemetry:
    def __init__(self, max_events: int = 200) -> None:
        self._events: deque[VoiceEvent] = deque(maxlen=max_events)
        self.counters: dict[str, int] = {}

    def record(self, name: str, *, status: str = "",
               latency_ms: float = 0.0, text_len: int = 0,
               audio_duration_s: float = 0.0, correlation_id: str = "",
               detail: str = "") -> VoiceEvent:
        event = VoiceEvent(
            name=name[:64], status=status[:32],
            latency_ms=max(0.0, float(latency_ms or 0.0)),
            text_len=max(0, int(text_len or 0)),
            audio_duration_s=max(0.0, float(audio_duration_s or 0.0)),
            correlation_id=str(correlation_id or "")[:64],
            detail=str(detail or "")[:200])
        self._events.append(event)
        self.counters[name] = self.counters.get(name, 0) + 1
        if status == "failed":
            self.counters[f"{name}.failed"] = \
                self.counters.get(f"{name}.failed", 0) + 1
        return event

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        return [{"name": e.name, "status": e.status,
                 "latency_ms": e.latency_ms, "text_len": e.text_len,
                 "audio_duration_s": e.audio_duration_s,
                 "correlation_id": e.correlation_id,
                 "detail": e.detail}
                for e in list(self._events)[-limit:]]

    def summary(self) -> dict[str, Any]:
        return {"counters": dict(self.counters),
                "buffered": len(self._events)}


TELEMETRY = VoiceTelemetry()

__all__ = ["VoiceEvent", "VoiceTelemetry", "TELEMETRY"]
