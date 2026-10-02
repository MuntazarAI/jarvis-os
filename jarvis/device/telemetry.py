"""Bounded telemetry model for the device fabric.

A node reports whatever metrics it has. Every metric except identity and
timestamp is optional: unknown stays unknown (``None``), never fabricated.
Telemetry is timestamped and sourced; the registry keeps only the latest
summary per device.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from ..core.types import now


class TelemetryError(ValueError):
    """Raised when telemetry fails validation."""


@dataclass
class Telemetry:
    device_id: str = ""
    timestamp: float = field(default_factory=now)
    online: bool | None = None
    uptime_s: float | None = None
    battery_pct: float | None = None
    battery_charging: bool | None = None
    cpu_pct: float | None = None
    mem_pct: float | None = None
    network: dict[str, Any] | None = None
    temperature_c: float | None = None
    node_version: str = ""
    capability_health: dict[str, str] | None = None
    source: str = "device-fabric"
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.device_id or not isinstance(self.device_id, str):
            raise TelemetryError("telemetry requires device_id")
        for numeric in ("battery_pct", "cpu_pct", "mem_pct"):
            value = getattr(self, numeric)
            if value is not None:
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    raise TelemetryError(f"telemetry {numeric} must be numeric")
                if not 0.0 <= value <= 100.0:
                    raise TelemetryError(f"telemetry {numeric} out of range 0..100")
                setattr(self, numeric, value)
        if self.uptime_s is not None and float(self.uptime_s) < 0:
            raise TelemetryError("telemetry uptime_s must be >= 0")

    def unknown_metrics(self) -> list[str]:
        """Metrics this report did not include (unknown, not zero)."""
        return [
            name for name in (
                "online", "uptime_s", "battery_pct", "battery_charging",
                "cpu_pct", "mem_pct", "network", "temperature_c",
                "node_version", "capability_health",
            )
            if getattr(self, name) in (None, "")
        ]

    def summary(self) -> dict[str, Any]:
        """Compact latest-state summary for registry persistence."""
        data = asdict(self)
        data.pop("extra", None)
        return data

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Telemetry":
        """Tolerant parse: missing metrics stay unknown; unknown keys dropped."""
        if not isinstance(data, dict):
            raise TelemetryError("telemetry must be an object")
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


def is_stale(last_seen: float, at: float, timeout_s: float) -> bool:
    if last_seen <= 0:
        return True
    return (at - last_seen) > timeout_s
