"""The entity/expectation surface of the world model, kept alive.

The M30 rewrite replaced the entity-and-expectation world model with
an object/event/causal model. Several subsystems — the memory bridge,
the experience view, the daily workflow and the state tracker — still
speak the older vocabulary.

These adapters implement that older surface on top of the new model, so
both shapes work and nothing has to choose one. The new model stays
the source of truth; these are views over it.
"""

from __future__ import annotations

import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..core.types import now


@dataclass
class WorldEntity:
    """A named thing in the world, in the older vocabulary."""

    entity_id: str
    kind: str
    name: str
    attributes: dict[str, Any] = field(default_factory=dict)
    domain: str = "digital"
    last_updated: float = field(default_factory=now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LegacyWorldAPI:
    """Entity, expectation and clock helpers over the current model.

    Mixed into :class:`jarvis.world.model.WorldModel`. Everything here
    is a view: the underlying model keeps the real state.
    """

    # -- state -----------------------------------------------------------
    @property
    def _entities(self) -> dict[str, WorldEntity]:
        store = getattr(self, "_legacy_entities", None)
        if store is None:
            store = {}
            self._legacy_entities = store
        return store

    @property
    def _rooms(self) -> dict[str, dict[str, Any]]:
        """Room states, created on first use."""
        store = getattr(self, "_legacy_rooms", None)
        if store is None:
            store = {}
            self._legacy_rooms = store
        return store

    @_rooms.setter
    def _rooms(self, value: dict[str, dict[str, Any]]) -> None:
        self._legacy_rooms = value

    @property
    def _timeline(self) -> list[Any]:
        """The recorded events, in arrival order."""
        return list(getattr(self, "event_model").events.values())

    @property
    def _arrival_order(self) -> list[Any]:
        return self._timeline

    @property
    def _clock_skew(self) -> float:
        return float(getattr(self, "_legacy_clock_skew", 0.0))

    @_clock_skew.setter
    def _clock_skew(self, value: float) -> None:
        self._legacy_clock_skew = float(value)

    # -- entities --------------------------------------------------------
    def upsert(self, kind: str, name: str, **attrs: Any) -> WorldEntity:
        entity_id = f"{kind}:{name}"
        existing = self._entities.get(entity_id)
        if existing:
            existing.attributes.update(attrs)
            existing.last_updated = self.now()
            return existing
        entity = WorldEntity(entity_id=entity_id, kind=kind, name=name,
                             attributes=attrs, last_updated=self.now())
        self._entities[entity_id] = entity
        return entity

    def get(self, entity_id: str) -> WorldEntity | None:
        return self._entities.get(entity_id)

    def find(self, kind: str | None = None,
             name: str | None = None) -> list[WorldEntity]:
        return [e for e in self._entities.values()
                if (kind is None or e.kind == kind)
                and (name is None or name.lower() in e.name.lower())]

    def entities(self) -> list[WorldEntity]:
        return list(self._entities.values())

    # -- expectations ----------------------------------------------------
    def expect(self, metric: str, minimum: float | None = None,
               maximum: float | None = None, note: str = "") -> dict[str, Any]:
        """Declare what a system metric SHOULD look like. Checked on demand."""
        if not hasattr(self, "_expectations"):
            self._expectations: dict[str, dict[str, Any]] = {}
        self._expectations[metric] = {"min": minimum, "max": maximum,
                                       "note": note}
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
    def rooms(self) -> dict[str, dict[str, Any]]:
        """The recorded room states."""
        return dict(self._rooms)

    def network_topology(self) -> dict[str, Any]:
        """The host's network interfaces and addresses."""
        import os
        import socket
        hostname = socket.gethostname()
        try:
            addresses = sorted({addr for addr
                               in socket.gethostbyname_ex(hostname)[2]})
        except OSError:
            addresses = []
        return {
            "hostname": hostname,
            "addresses": addresses,
            "interface_count": len(os.listdir("/sys/class/net"))
            if Path("/sys/class/net").exists() else 0,
        }

    def containers(self) -> dict[str, Any]:
        """Running containers, by runtime."""
        import shutil
        result: dict[str, Any] = {"docker": None, "podman": None}
        for runtime in ("docker", "podman"):
            binary = shutil.which(runtime)
            if not binary:
                continue
            try:
                out = subprocess.run(
                    [binary, "ps", "--format", "{{.Names}}"],
                    capture_output=True, text=True, timeout=5,
                )
                if out.returncode == 0:
                    result[runtime] = [line for line in out.stdout.splitlines()
                                       if line.strip()]
            except (OSError, subprocess.SubprocessError):
                result[runtime] = "error"
        return result

    def applications(self) -> list[str]:
        """The distinct program names running on this machine."""
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


__all__ = ["LegacyWorldAPI", "WorldEntity"]
