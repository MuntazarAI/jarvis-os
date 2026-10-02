"""Notifications 3.2 — small provider-neutral abstraction.

A Notification carries information only. It can never execute actions,
approve anything, or carry secrets. Delivery backends implement one
method; only backends actually present in the environment report
themselves available. A MockBackend exists for tests.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ..core.types import new_id, now

NOTIFICATION_VERSION = 1


@dataclass
class Notification:
    notification_id: str = field(default_factory=lambda: new_id("notif"))
    source_dot: str = ""
    type: str = "info"  # info | question | approval | alert
    title: str = ""
    message: str = ""
    priority: str = "normal"  # low | normal | high | critical
    created_at: float = field(default_factory=now)
    expires_at: float | None = None
    dedup_key: str = ""
    related_task: str = ""
    related_event: str = ""
    evidence_refs: list[str] = field(default_factory=list)
    requires_approval: bool = False
    delivered_by: list[str] = field(default_factory=list)
    version: int = NOTIFICATION_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "notification_id": self.notification_id,
            "source_dot": self.source_dot, "type": self.type,
            "title": self.title, "message": self.message,
            "priority": self.priority, "created_at": self.created_at,
            "expires_at": self.expires_at, "dedup_key": self.dedup_key,
            "related_task": self.related_task,
            "related_event": self.related_event,
            "evidence_refs": self.evidence_refs,
            "requires_approval": self.requires_approval,
            "delivered_by": self.delivered_by, "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Notification":
        return cls(
            notification_id=data.get("notification_id", new_id("notif")),
            source_dot=data.get("source_dot", ""),
            type=data.get("type", "info"),
            title=data.get("title", ""), message=data.get("message", ""),
            priority=data.get("priority", "normal"),
            created_at=data.get("created_at", now()),
            expires_at=data.get("expires_at"),
            dedup_key=data.get("dedup_key", ""),
            related_task=data.get("related_task", ""),
            related_event=data.get("related_event", ""),
            evidence_refs=list(data.get("evidence_refs", [])),
            requires_approval=bool(data.get("requires_approval", False)),
            delivered_by=list(data.get("delivered_by", [])),
            version=int(data.get("version", 1)))

    def expired(self, at: float | None = None) -> bool:
        stamp = at if at is not None else now()
        return self.expires_at is not None and stamp >= self.expires_at


class NotificationBackend(Protocol):
    """One delivery method. Returns True when actually delivered."""

    name: str

    def available(self) -> bool: ...
    def send(self, notification: Notification) -> bool: ...


class LogBackend:
    """Always-available local backend: appends JSONL to a file + memory.

    This is the honest default. Desktop/mobile/voice/HUD are future
    backends behind this same interface.
    """

    name = "log"

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else None
        self.sent: list[Notification] = []

    def available(self) -> bool:
        return True

    def send(self, notification: Notification) -> bool:
        notification.delivered_by.append(self.name)
        self.sent.append(notification)
        if self.path is not None:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.path, "a", encoding="utf-8") as handle:
                    handle.write(json.dumps(notification.to_dict(),
                                            default=str) + "\n")
            except OSError:
                return False
        return True


class DesktopBackend:
    """Linux desktop notifications via notify-send.

    Reports unavailable when the binary is missing so callers never
    pretend delivery happened. Fire-and-forget: no replies collected.
    """

    name = "desktop"

    def available(self) -> bool:
        return shutil.which("notify-send") is not None

    def send(self, notification: Notification) -> bool:
        if not self.available():
            return False
        urgency = {"low": "low", "normal": "normal",
                   "high": "critical", "critical": "critical"}.get(
                       notification.priority, "normal")
        try:
            proc = subprocess.run(
                ["notify-send", "--urgency", urgency,
                 notification.title or "JARVIS",
                 notification.message[:500]],
                capture_output=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            return False
        if proc.returncode != 0:
            return False
        notification.delivered_by.append(self.name)
        return True


class MockBackend:
    """Test double. Records everything, delivers nothing externally."""

    name = "mock"

    def __init__(self) -> None:
        self.sent: list[Notification] = []
        self._available = True

    def available(self) -> bool:
        return self._available

    def fail(self) -> None:
        self._available = False

    def send(self, notification: Notification) -> bool:
        if not self._available:
            return False
        notification.delivered_by.append(self.name)
        self.sent.append(notification)
        return True


def scrub_notification(data: dict[str, Any]) -> dict[str, Any]:
    """Strip secret-looking fields before a notification is built/stored."""
    clean: dict[str, Any] = {}
    for key, value in data.items():
        lowered = key.lower()
        if any(marker in lowered for marker in
               ("password", "secret", "token", "credential", "api_key",
                "apikey", "private_key")):
            continue
        clean[key] = value
    return clean


class NotificationPolicy:
    """Gatekeeper: decides whether a notification may go out.

    Enforces, in order: master enable flag, emergency stop, expiry,
    quiet hours, per-key cooldown, hourly rate limit. Denials carry
    reasons; nothing is silent.
    """

    def __init__(self, max_per_hour: int = 10,
                 cooldown_s: float = 600.0,
                 quiet_hours: tuple[int, int] | None = None) -> None:
        self.max_per_hour = max_per_hour
        self.cooldown_s = cooldown_s
        self.quiet_hours = quiet_hours
        self.enabled = True
        self._sent_at: list[float] = []
        self._last_by_key: dict[str, float] = {}

    def check(self, notification: Notification,
              now_ts: float | None = None,
              emergency_stop: bool = False) -> tuple[bool, str]:
        stamp = now_ts if now_ts is not None else now()
        if not self.enabled:
            return False, "notifications disabled by user setting"
        if emergency_stop:
            return False, "emergency stop active"
        if notification.expired(stamp):
            return False, "notification expired"
        if self.quiet_hours is not None:
            import datetime
            hour = datetime.datetime.fromtimestamp(
                stamp).astimezone().hour
            start, end = self.quiet_hours
            in_quiet = (hour >= start or hour < end) if start > end \
                else (start <= hour < end)
            if in_quiet:
                return False, f"quiet hours {start:02d}:00-{end:02d}:00"
        if notification.dedup_key:
            last = self._last_by_key.get(notification.dedup_key, 0.0)
            if stamp - last < self.cooldown_s:
                return False, "dedup cooldown active for this key"
        hour_ago = stamp - 3600.0
        self._sent_at = [t for t in self._sent_at if t > hour_ago]
        if len(self._sent_at) >= self.max_per_hour:
            return False, f"hourly rate limit reached ({self.max_per_hour}/h)"
        return True, "allowed"

    def record_sent(self, notification: Notification,
                    now_ts: float | None = None) -> None:
        stamp = now_ts if now_ts is not None else now()
        self._sent_at.append(stamp)
        if notification.dedup_key:
            self._last_by_key[notification.dedup_key] = stamp


class Notifier:
    """Delivers notifications through available backends.

    Tries backends in order; records which ones actually delivered.
    Never raises on backend failure; returns a delivery report.
    """

    def __init__(self, backends: list[NotificationBackend] | None = None,
                 policy: NotificationPolicy | None = None) -> None:
        self.backends = list(backends or [])
        self.policy = policy or NotificationPolicy()
        self.delivered: list[Notification] = []
        self.denied: list[dict[str, Any]] = []

    def deliver(self, notification: Notification,
                emergency_stop: bool = False) -> dict[str, Any]:
        allowed, reason = self.policy.check(
            notification, emergency_stop=emergency_stop)
        if not allowed:
            self.denied.append(
                {"notification_id": notification.notification_id,
                 "reason": reason, "at": now()})
            return {"ok": False, "reason": reason, "delivered_by": []}
        sent_any = False
        for backend in self.backends:
            try:
                if backend.available() and backend.send(notification):
                    sent_any = True
            except Exception:
                continue
        if sent_any:
            self.policy.record_sent(notification)
            self.delivered.append(notification)
            return {"ok": True, "reason": "delivered",
                    "delivered_by": list(notification.delivered_by)}
        self.denied.append(
            {"notification_id": notification.notification_id,
             "reason": "no backend available", "at": now()})
        return {"ok": False, "reason": "no backend available",
                "delivered_by": []}
