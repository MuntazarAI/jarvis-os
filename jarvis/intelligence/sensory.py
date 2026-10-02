"""Typed sensory bus: bounded events from every perception source.

Each SensoryEvent carries bounded metadata only (source, timestamp, type,
confidence, payload reference or small payload, correlation id). Large
blobs (frames, audio) are NEVER copied through the loop: producers pass a
reference plus precomputed features.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable


SENSORY_TYPES = (
    "vision", "audio", "speech", "input", "screen", "network",
    "device", "environment", "gods_eye", "proactive", "user", "timer",
)

MAX_PAYLOAD_BYTES = 4096


def _payload_size(payload: dict[str, Any]) -> int:
    try:
        import json
        return len(json.dumps(payload, default=str))
    except Exception:
        return MAX_PAYLOAD_BYTES + 1


@dataclass
class SensoryEvent:
    source: str
    type: str
    timestamp: float = field(default_factory=time.time)
    confidence: float = 0.6
    payload: dict[str, Any] = field(default_factory=dict)
    correlation_id: str = ""
    event_id: str = ""

    def __post_init__(self) -> None:
        if self.type not in SENSORY_TYPES:
            raise ValueError(f"unknown sensory type: {self.type}")
        if not self.source:
            raise ValueError("sensory event needs a source")
        self.confidence = max(0.0, min(1.0, float(self.confidence)))
        if _payload_size(self.payload) > MAX_PAYLOAD_BYTES:
            raise ValueError(
                f"sensory payload exceeds {MAX_PAYLOAD_BYTES} bytes; "
                "pass a reference + features instead of blobs"
            )
        if not self.event_id:
            import uuid
            self.event_id = f"sen-{uuid.uuid4().hex[:12]}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "source": self.source,
            "type": self.type,
            "timestamp": self.timestamp,
            "confidence": self.confidence,
            "payload": dict(self.payload),
            "correlation_id": self.correlation_id,
        }


Handler = Callable[[SensoryEvent], None]


class SensoryBus:
    """Bounded pub/sub for sensory events with per-type subscriptions."""

    def __init__(self, max_history: int = 500) -> None:
        if max_history <= 0:
            raise ValueError("max_history must be positive")
        self._handlers: dict[str, list[Handler]] = {}
        self._history: deque[SensoryEvent] = deque(maxlen=max_history)
        self.dropped_oversize = 0

    def subscribe(self, sensory_type: str, handler: Handler) -> None:
        if sensory_type != "*" and sensory_type not in SENSORY_TYPES:
            raise ValueError(f"unknown sensory type: {sensory_type}")
        self._handlers.setdefault(sensory_type, []).append(handler)

    def publish(self, event: SensoryEvent) -> int:
        """Deliver to matching handlers. Returns handler count. Isolation:
        one bad handler never breaks the bus."""
        delivered = 0
        targets = list(self._handlers.get(event.type, [])) + list(self._handlers.get("*", []))
        for handler in targets:
            try:
                handler(event)
                delivered += 1
            except Exception:
                continue
        self._history.append(event)
        return delivered

    def history(self, limit: int = 50, sensory_type: str = "") -> list[SensoryEvent]:
        items = list(self._history)
        if sensory_type:
            items = [e for e in items if e.type == sensory_type]
        return items[-limit:]

    def stats(self) -> dict[str, Any]:
        by_type: dict[str, int] = {}
        for event in self._history:
            by_type[event.type] = by_type.get(event.type, 0) + 1
        return {"buffered": len(self._history), "by_type": by_type,
                "dropped_oversize": self.dropped_oversize}


def event_from_gods_eye(observation: Any) -> SensoryEvent:
    """Adapter: GeoObservation/live observation -> SensoryEvent (features only)."""
    name = getattr(observation, "name", "observation")
    kind = getattr(observation, "kind", getattr(observation, "source", "unknown"))
    lat = getattr(observation, "latitude", None)
    lon = getattr(observation, "longitude", None)
    payload: dict[str, Any] = {"name": str(name)[:200], "kind": str(kind)[:80]}
    if lat is not None and lon is not None:
        try:
            payload["latitude"] = float(lat)
            payload["longitude"] = float(lon)
        except (TypeError, ValueError):
            pass
    return SensoryEvent(source="gods-eye", type="gods_eye",
                        confidence=float(getattr(observation, "confidence", 0.6)),
                        payload=payload)


def event_from_device(device_id: str, event_type: str, data: dict[str, Any]) -> SensoryEvent:
    """Adapter: device-fabric event -> SensoryEvent (untrusted data, typed)."""
    payload = {k: v for k, v in data.items() if isinstance(v, (str, int, float, bool))}
    payload = {k: (str(v)[:200] if isinstance(v, str) else v) for k, v in payload.items()}
    payload["device_id"] = str(device_id)[:120]
    payload["device_event"] = str(event_type)[:80]
    return SensoryEvent(source="device-fabric", type="device", payload=payload)


def event_from_user(text: str, correlation_id: str = "") -> SensoryEvent:
    return SensoryEvent(source="user", type="user", confidence=1.0,
                        payload={"text": text[:1000]}, correlation_id=correlation_id)
