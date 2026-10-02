"""Dot schedules 3.2 — persistent wake schedules for Dots.

A schedule never executes anything. It only describes *when* a Dot
deserves attention. Firing flows through TriggerEngine → EventBus →
ProactiveEngine → DotManager → DotRuntime → Orchestrator → PolicyEngine.

Schedule kinds: one-time | interval | daily | weekly | event | manual.
All time math uses Unix timestamps; timezones resolve via zoneinfo and
invalid zones are rejected at creation time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..core.types import new_id, now

SCHEDULE_VERSION = 1

SCHEDULE_KINDS = ("one-time", "interval", "daily", "weekly", "event",
                  "manual")


class InvalidSchedule(ValueError):
    """Rejected schedule configuration."""


def _validate_timezone(tz: str) -> str:
    try:
        ZoneInfo(tz or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        raise InvalidSchedule(f"unknown timezone: {tz!r}")
    return tz or "UTC"


_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def _validate_time_of_day(value: str) -> str:
    if not _TIME_RE.match(value or ""):
        raise InvalidSchedule(
            f"time_of_day must be HH:MM (24h), got {value!r}")
    return value


@dataclass
class DotSchedule:
    schedule_id: str = field(default_factory=lambda: new_id("sched"))
    dot_id: str = ""
    kind: str = "manual"
    # kind-specific configuration (all JSON-serializable):
    #   one-time: {"at": <unix ts>}
    #   interval: {"every": <seconds>}
    #   daily:    {"time": "HH:MM", "tz": name}
    #   weekly:   {"weekday": 0-6 (Mon=0), "time": "HH:MM", "tz": name}
    #   event:    {"event_type": str}
    #   manual:   {}
    config: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    timezone: str = "UTC"
    created_at: float = field(default_factory=now)
    updated_at: float = field(default_factory=now)
    next_run: float | None = None
    last_run: float | None = None
    failure_count: int = 0
    cooldown_s: float = 300.0
    max_activations: int = 0  # 0 = unbounded (cooldown still applies)
    activations: int = 0
    reason: str = ""
    version: int = SCHEDULE_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schedule_id": self.schedule_id, "dot_id": self.dot_id,
            "kind": self.kind, "config": self.config,
            "enabled": self.enabled, "timezone": self.timezone,
            "created_at": self.created_at, "updated_at": self.updated_at,
            "next_run": self.next_run, "last_run": self.last_run,
            "failure_count": self.failure_count,
            "cooldown_s": self.cooldown_s,
            "max_activations": self.max_activations,
            "activations": self.activations, "reason": self.reason,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DotSchedule":
        return cls(
            schedule_id=data.get("schedule_id", new_id("sched")),
            dot_id=data.get("dot_id", ""),
            kind=data.get("kind", "manual"),
            config=dict(data.get("config", {})),
            enabled=bool(data.get("enabled", True)),
            timezone=data.get("timezone", "UTC"),
            created_at=data.get("created_at", now()),
            updated_at=data.get("updated_at", now()),
            next_run=data.get("next_run"),
            last_run=data.get("last_run"),
            failure_count=int(data.get("failure_count", 0)),
            cooldown_s=float(data.get("cooldown_s", 300.0)),
            max_activations=int(data.get("max_activations", 0)),
            activations=int(data.get("activations", 0)),
            reason=data.get("reason", ""),
            version=int(data.get("version", 1)))


def validate_schedule(kind: str, config: dict[str, Any],
                       timezone: str = "UTC") -> dict[str, Any]:
    """Validate kind + config. Returns normalized config or raises."""
    if kind not in SCHEDULE_KINDS:
        raise InvalidSchedule(f"unknown schedule kind: {kind!r}")
    tz = _validate_timezone(timezone)
    cfg = dict(config)
    if kind == "one-time":
        at = cfg.get("at", 0)
        if not isinstance(at, (int, float)) or at <= 0:
            raise InvalidSchedule("'at' must be a positive Unix timestamp")
        cfg["at"] = float(at)
    elif kind == "interval":
        every = cfg.get("every", 0)
        if not isinstance(every, (int, float)) or every < 60:
            raise InvalidSchedule(
                "'every' must be >= 60 seconds (no sub-minute polling)")
        cfg["every"] = float(every)
    elif kind == "daily":
        cfg["time"] = _validate_time_of_day(cfg.get("time", ""))
    elif kind == "weekly":
        weekday = cfg.get("weekday", -1)
        if not isinstance(weekday, int) or not 0 <= weekday <= 6:
            raise InvalidSchedule("'weekday' must be 0-6 (Mon=0)")
        cfg["time"] = _validate_time_of_day(cfg.get("time", ""))
    elif kind == "event":
        if not str(cfg.get("event_type", "")).strip():
            raise InvalidSchedule("'event_type' must be a non-empty string")
        cfg["event_type"] = str(cfg["event_type"]).strip()
    return {"kind": kind, "config": cfg, "timezone": tz}


def compute_next(kind: str, config: dict[str, Any], timezone: str,
                 after_ts: float, created_at: float = 0.0) -> float | None:
    """Next run strictly after `after_ts`. Pure function. None = never.

    `created_at` anchors interval schedules that never ran.
    """
    if kind == "manual":
        return None
    if kind == "one-time":
        at = float(config["at"])
        return at if at > after_ts else None
    if kind == "interval":
        every = float(config["every"])
        anchor = created_at or after_ts
        if after_ts < anchor:
            return anchor
        elapsed = after_ts - anchor
        steps = int(elapsed // every) + 1
        return anchor + steps * every
    tz = ZoneInfo(timezone)
    if kind == "daily":
        hour, minute = (int(v) for v in str(config["time"]).split(":"))
        base = datetime.fromtimestamp(after_ts, tz=tz).replace(
            hour=hour, minute=minute, second=0, microsecond=0)
        if base.timestamp() <= after_ts:
            base += timedelta(days=1)
        return base.timestamp()
    if kind == "weekly":
        hour, minute = (int(v) for v in str(config["time"]).split(":"))
        weekday = int(config["weekday"])
        base = datetime.fromtimestamp(after_ts, tz=tz).replace(
            hour=hour, minute=minute, second=0, microsecond=0)
        days_ahead = (weekday - base.weekday()) % 7
        candidate = base + timedelta(days=days_ahead)
        if candidate.timestamp() <= after_ts:
            candidate += timedelta(weeks=1)
        return candidate.timestamp()
    if kind == "event":
        return None  # event-driven; TriggerEngine kind="event" fires it
    raise InvalidSchedule(f"unknown schedule kind: {kind!r}")
