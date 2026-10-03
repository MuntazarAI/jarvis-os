"""World telemetry: metadata-only event ring (World Intelligence 1.0).

Same established pattern as the voice domain recorder: bounded ring +
counters recording provider, request id, duration, counts, status, and
freshness — never secrets, raw page content, private memories, or
full query text (query length only).
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class WorldEvent:
    name: str
    at: float = field(default_factory=time.time)
    status: str = ""
    latency_ms: float = 0.0
    provider: str = ""
    count: int = 0
    bytes: int = 0
    query_len: int = 0
    freshness: str = ""
    correlation_id: str = ""
    detail: str = ""


class WorldTelemetry:
    def __init__(self, max_events: int = 200) -> None:
        self._events: deque[WorldEvent] = deque(maxlen=max_events)
        self.counters: dict[str, int] = {}

    def record(self, name: str, *, status: str = "",
               latency_ms: float = 0.0, provider: str = "",
               count: int = 0, bytes: int = 0, query_len: int = 0,
               freshness: str = "", correlation_id: str = "",
               detail: str = "") -> WorldEvent:
        event = WorldEvent(
            name=name[:64], status=status[:32],
            latency_ms=max(0.0, float(latency_ms or 0.0)),
            provider=str(provider or "")[:64],
            count=max(0, int(count or 0)),
            bytes=max(0, int(bytes or 0)),
            query_len=max(0, int(query_len or 0)),
            freshness=str(freshness or "")[:16],
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
                 "latency_ms": e.latency_ms, "provider": e.provider,
                 "count": e.count, "bytes": e.bytes,
                 "query_len": e.query_len, "freshness": e.freshness,
                 "correlation_id": e.correlation_id,
                 "detail": e.detail}
                for e in list(self._events)[-limit:]]

    def summary(self) -> dict[str, Any]:
        return {"counters": dict(self.counters),
                "buffered": len(self._events)}


TELEMETRY = WorldTelemetry()

__all__ = ["WorldEvent", "WorldTelemetry", "TELEMETRY"]
