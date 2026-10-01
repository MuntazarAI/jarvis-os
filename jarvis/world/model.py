"""World model: digital, physical, temporal and system-state representation."""

from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import subprocess
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from ..core.types import Modality, Observation, now


@dataclass
class WorldEntity:
    entity_id: str
    kind: str
    name: str
    attributes: dict[str, Any] = field(default_factory=dict)
    domain: str = "digital"
    last_updated: float = field(default_factory=now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WorldEvent:
    timestamp: float
    description: str
    source: str = "system"
    confidence: float = 0.8
    location: str = ""
    participants: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class WorldModel:
    """Digital + physical + temporal + system state, with a timeline."""

    def __init__(self) -> None:
        self._entities: dict[str, WorldEntity] = {}
        self._timeline: list[WorldEvent] = []
        self._arrival_order: list[WorldEvent] = []
        self._rooms: dict[str, dict[str, Any]] = {}
        self._clock_skew: float = 0.0

    # -- entities --------------------------------------------------------
    def upsert(self, kind: str, name: str, **attrs: Any) -> WorldEntity:
        entity_id = f"{kind}:{name}"
        existing = self._entities.get(entity_id)
        if existing:
            existing.attributes.update(attrs)
            existing.last_updated = now()
            return existing
        entity = WorldEntity(entity_id=entity_id, kind=kind, name=name, attributes=attrs)
        self._entities[entity_id] = entity
        return entity

    def get(self, entity_id: str) -> WorldEntity | None:
        return self._entities.get(entity_id)

    def find(self, kind: str | None = None, name: str | None = None) -> list[WorldEntity]:
        return [
            e
            for e in self._entities.values()
            if (kind is None or e.kind == kind)
            and (name is None or name.lower() in e.name.lower())
        ]

    def entities(self) -> list[WorldEntity]:
        return list(self._entities.values())

    # -- timeline --------------------------------------------------------
    def record_event(
        self,
        description: str,
        source: str = "system",
        confidence: float = 0.8,
        location: str = "",
        participants: list[str] | None = None,
        timestamp: float | None = None,
    ) -> WorldEvent:
        event = WorldEvent(
            timestamp=timestamp if timestamp is not None else now() + self._clock_skew,
            description=description,
            source=source,
            confidence=confidence,
            location=location,
            participants=participants or [],
        )
        self._timeline.append(event)
        self._timeline.sort(key=lambda e: e.timestamp)
        self._arrival_order.append(event)
        return event

    def timeline(self, start: float | None = None, end: float | None = None) -> list[WorldEvent]:
        events = self._timeline
        if start is not None:
            events = [e for e in events if e.timestamp >= start]
        if end is not None:
            events = [e for e in events if e.timestamp <= end]
        return list(events)

    def timeline_gaps(self, tolerance: float = 1.0) -> list[dict[str, Any]]:
        """Detect unexpected intervals and impossible orderings.

        Out-of-order arrivals are checked against arrival order (an event
        recorded with an earlier timestamp than what was recorded before it
        is an impossible sequence). Missing intervals are checked against
        the sorted timeline.
        """
        gaps: list[dict[str, Any]] = []
        for prev, nxt in zip(self._arrival_order, self._arrival_order[1:]):
            delta = nxt.timestamp - prev.timestamp
            if delta < -tolerance:
                gaps.append(
                    {
                        "kind": "impossible_sequence",
                        "before": prev.description,
                        "after": nxt.description,
                        "delta": delta,
                    }
                )
        for prev, nxt in zip(self._timeline, self._timeline[1:]):
            delta = nxt.timestamp - prev.timestamp
            if delta > 3600:
                gaps.append(
                    {
                        "kind": "missing_interval",
                        "before": prev.description,
                        "after": nxt.description,
                        "seconds": delta,
                    }
                )
        return gaps

    def overlaps(self, tolerance: float = 0.5) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        for i, a in enumerate(self._timeline):
            for b in self._timeline[i + 1:]:
                if abs(a.timestamp - b.timestamp) <= tolerance and a.description != b.description:
                    found.append({"a": a.description, "b": b.description, "at": a.timestamp})
        return found

    # -- expectations (expected-state modeling) ----------------------------------
    def expect(self, metric: str, minimum: float | None = None,
               maximum: float | None = None, note: str = "") -> dict[str, Any]:
        """Declare what a system metric SHOULD look like. Checked on demand."""
        if not hasattr(self, "_expectations"):
            self._expectations: dict[str, dict[str, Any]] = {}
        self._expectations[metric] = {"min": minimum, "max": maximum, "note": note}
        return self._expectations[metric]

    def check_expectations(self) -> list[dict[str, Any]]:
        """Compare live system state against expectations. Violations out."""
        state = self.system_state()
        flat = {
            "disk_free": state.get("disk", {}).get("free", 0),
            "disk_percent_used": state.get("disk", {}).get("percent_used", 0),
            "mem_percent_used": state.get("memory", {}).get("percent_used", 0),
            "battery_percent": state.get("battery", {}).get("percent", 100),
            "load_1": (state.get("load_average") or [0])[0],
        }
        violations: list[dict[str, Any]] = []
        for metric, rule in getattr(self, "_expectations", {}).items():
            value = flat.get(metric)
            if value is None:
                violations.append({"metric": metric, "status": "unknown",
                                   "note": "no such metric"})
                continue
            if rule.get("min") is not None and value < rule["min"]:
                violations.append({"metric": metric, "value": value,
                                   "expected_min": rule["min"],
                                   "status": "unexpected",
                                   "note": rule.get("note", "")})
            elif rule.get("max") is not None and value > rule["max"]:
                violations.append({"metric": metric, "value": value,
                                   "expected_max": rule["max"],
                                   "status": "unexpected",
                                   "note": rule.get("note", "")})
        return violations

    # -- temporal --------------------------------------------------------
    def sync_clock(self, offset_seconds: float) -> None:
        self._clock_skew = offset_seconds

    def now(self) -> float:
        return now() + self._clock_skew

    def timezone(self) -> str:
        try:
            return subprocess.run(
                ["timedatectl", "show", "-p", "Timezone", "--value"],
                capture_output=True, text=True, timeout=3,
            ).stdout.strip() or "local"
        except (OSError, subprocess.SubprocessError):
            return "local"

    # -- digital world ---------------------------------------------------
    def filesystem_state(self, path: str = ".", depth: int = 1) -> dict[str, Any]:
        root = Path(path).resolve()
        if not root.exists():
            return {"path": str(root), "exists": False}
        entries: list[dict[str, Any]] = []
        try:
            for item in sorted(root.iterdir())[:500]:
                try:
                    stat = item.stat()
                    entries.append(
                        {
                            "name": item.name,
                            "is_dir": item.is_dir(),
                            "size": stat.st_size,
                            "modified": stat.st_mtime,
                        }
                    )
                except OSError:
                    continue
        except PermissionError:
            return {"path": str(root), "exists": True, "error": "permission denied"}
        return {"path": str(root), "exists": True, "entries": entries, "depth": depth}

    def applications(self) -> list[str]:
        found: list[str] = []
        for proc in Path("/proc").iterdir():
            if not proc.name.isdigit():
                continue
            try:
                comm = (proc / "comm").read_text().strip()
                if comm and comm not in found:
                    found.append(comm)
            except (OSError, UnicodeDecodeError):
                continue
        return sorted(found)

    def network_topology(self) -> dict[str, Any]:
        hostname = socket.gethostname()
        try:
            addresses = sorted({addr for addr in socket.gethostbyname_ex(hostname)[2]})
        except OSError:
            addresses = []
        return {
            "hostname": hostname,
            "addresses": addresses,
            "interface_count": len(os.listdir("/sys/class/net")) if Path("/sys/class/net").exists() else 0,
        }

    def containers(self) -> dict[str, Any]:
        result: dict[str, Any] = {"docker": None, "podman": None}
        for runtime in ("docker", "podman"):
            binary = shutil.which(runtime)
            if not binary:
                continue
            try:
                out = subprocess.run(
                    [binary, "ps", "--format", "{{.Names}}"], capture_output=True,
                    text=True, timeout=5,
                )
                if out.returncode == 0:
                    result[runtime] = [ln for ln in out.stdout.splitlines() if ln.strip()]
            except (OSError, subprocess.SubprocessError):
                result[runtime] = "error"
        return result

    # -- system state ----------------------------------------------------
    def system_state(self) -> dict[str, Any]:
        return {
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "cpu_count": os.cpu_count(),
            "load_average": os.getloadavg() if hasattr(os, "getloadavg") else [],
            "disk": self._disk_usage(),
            "memory": self._memory(),
            "battery": self._battery(),
            "uptime": self._uptime(),
        }

    @staticmethod
    def _disk_usage() -> dict[str, Any]:
        usage = shutil.disk_usage("/")
        return {
            "total": usage.total,
            "used": usage.used,
            "free": usage.free,
            "percent_used": round(usage.used / usage.total * 100, 1) if usage.total else 0.0,
        }

    @staticmethod
    def _memory() -> dict[str, Any]:
        meminfo = Path("/proc/meminfo")
        if not meminfo.exists():
            return {}
        values: dict[str, int] = {}
        for line in meminfo.read_text().splitlines():
            parts = line.split()
            if len(parts) >= 2:
                values[parts[0].rstrip(":")] = int(parts[1]) // 1024
        total = values.get("MemTotal", 0)
        available = values.get("MemAvailable", 0)
        return {
            "total_mb": total,
            "available_mb": available,
            "used_mb": total - available,
            "percent_used": round((total - available) / total * 100, 1) if total else 0.0,
        }

    @staticmethod
    def _battery() -> dict[str, Any]:
        base = Path("/sys/class/power_supply")
        if not base.exists():
            return {"present": False}
        for supply in base.iterdir():
            cap = supply / "capacity"
            status = supply / "status"
            if cap.exists():
                return {
                    "present": True,
                    "name": supply.name,
                    "percent": int(cap.read_text().strip()),
                    "status": status.read_text().strip() if status.exists() else "unknown",
                }
        return {"present": False}

    @staticmethod
    def _uptime() -> float:
        uptime = Path("/proc/uptime")
        if uptime.exists():
            try:
                return float(uptime.read_text().split()[0])
            except (OSError, ValueError, IndexError):
                pass
        return 0.0

    # -- physical world --------------------------------------------------
    def rooms(self) -> dict[str, dict[str, Any]]:
        return dict(self._rooms)

    def record_room(self, room: str, objects: dict[str, Any], sensor: str = "") -> dict[str, Any]:
        entry = {
            "objects": objects,
            "sensor": sensor,
            "observed_at": now(),
            "history": self._rooms.get(room, {}).get("history", [])[-9:],
        }
        entry["history"] = [*entry["history"], {"at": entry["observed_at"], "objects": objects}]
        self._rooms[room] = entry
        return entry

    def room_diff(self, room: str) -> dict[str, Any]:
        """Compare the latest room state against its previous observation."""
        entry = self._rooms.get(room)
        if not entry or len(entry.get("history", [])) < 2:
            return {"room": room, "has_baseline": False, "added": [], "removed": [], "moved": []}
        latest = entry["history"][-1]["objects"]
        previous = entry["history"][-2]["objects"]
        added = [k for k in latest if k not in previous]
        removed = [k for k in previous if k not in latest]
        moved = [
            k for k in latest
            if k in previous and latest[k] != previous[k]
        ]
        return {
            "room": room,
            "has_baseline": True,
            "added": added,
            "removed": removed,
            "moved": moved,
            "changed_at": entry["history"][-1]["at"],
        }

    # -- observation integration -----------------------------------------
    def observe(self, obs: Observation) -> WorldEntity:
        entity = self.upsert(
            obs.kind, obs.metadata.get("name", obs.source), content=obs.content,
            modality=obs.modality, last_seen=obs.timestamp,
        )
        self.record_event(
            f"{obs.kind} observed: {obs.content[:80]}",
            source=obs.source,
            confidence=obs.confidence,
        )
        return entity

    def snapshot(self) -> dict[str, Any]:
        kept = self._timeline[-100:]
        kept_ids = {id(e) for e in kept}
        order = [kept.index(e) for e in self._arrival_order if id(e) in kept_ids]
        return {
            "entities": [e.to_dict() for e in self._entities.values()],
            "timeline": [e.to_dict() for e in kept],
            "arrival_order": order,
            "rooms": self._rooms,
            "system": self.system_state(),
            "network": self.network_topology(),
            "captured_at": now(),
        }

    def restore(self, data: dict[str, Any]) -> None:
        for raw in data.get("entities", []):
            self._entities[raw["entity_id"]] = WorldEntity(**raw)
        self._timeline = [WorldEvent(**e) for e in data.get("timeline", [])]
        order = data.get("arrival_order")
        if order and len(order) == len(self._timeline):
            self._arrival_order = [self._timeline[i] for i in order]
        else:
            # Legacy snapshots without arrival order: assume sorted arrival.
            self._arrival_order = list(self._timeline)
        self._rooms = data.get("rooms", {})

    def to_json(self) -> str:
        return json.dumps(self.snapshot(), default=str, indent=2)
