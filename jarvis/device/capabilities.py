"""Typed capability registry for the device fabric.

A capability describes what a node CAN expose (``device.battery``,
``system.telemetry``, ...). It never grants anything: PolicyEngine decides
what JARVIS MAY request, per call, via the router.

Capabilities are explicitly declared, typed (dotted names), versioned,
and individually enable/disable-able per node.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

#: Example capability names. Documentation only — nodes may declare others.
WELL_KNOWN = (
    "system.status",
    "system.telemetry",
    "device.battery",
    "device.network",
    "device.camera",
    "device.microphone",
    "device.location",
    "device.notifications",
    "device.files",
    "device.display",
    "compute.cpu",
    "compute.gpu",
    "storage.read",
    "storage.write",
)

_NAME_RE = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")


class CapabilityError(ValueError):
    """Raised when a capability declaration is invalid."""


def validate_capability_name(name: str) -> str:
    if not isinstance(name, str) or not _NAME_RE.match(name) or len(name) > 64:
        raise CapabilityError(f"invalid capability name: {name!r}")
    return name


@dataclass
class Capability:
    """One typed, versioned, policy-aware capability."""

    name: str = ""
    version: int = 1
    title: str = ""
    description: str = ""
    risk: float = 0.2  # 0.0..1.0; floors the policy risk score on routing
    required_permissions: list[str] = field(default_factory=list)
    enabled: bool = True
    read_only: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        validate_capability_name(self.name)
        if not isinstance(self.version, int) or self.version < 1:
            raise CapabilityError("capability version must be an int >= 1")
        try:
            self.risk = float(self.risk)
        except (TypeError, ValueError):
            raise CapabilityError("capability risk must be numeric")
        if not 0.0 <= self.risk <= 1.0:
            raise CapabilityError("capability risk must be within 0.0..1.0")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Capability":
        if not isinstance(data, dict):
            raise CapabilityError("capability must be an object")
        known = {f for f in cls.__dataclass_fields__}
        clean = {k: v for k, v in data.items() if k in known}
        if "name" not in clean:
            raise CapabilityError("capability missing name")
        return cls(**clean)


class CapabilityRegistry:
    """Versioned declarations for one node (or the fabric's known set)."""

    def __init__(self) -> None:
        self._caps: dict[str, Capability] = {}

    def declare(self, capability: Capability) -> Capability:
        """Declare (or upgrade) a capability. Downgrades are rejected."""
        existing = self._caps.get(capability.name)
        if existing is not None and capability.version < existing.version:
            raise CapabilityError(
                f"capability {capability.name} downgrade "
                f"v{existing.version} -> v{capability.version} refused"
            )
        self._caps[capability.name] = capability
        return capability

    def get(self, name: str) -> Capability | None:
        return self._caps.get(name)

    def require(self, name: str) -> Capability:
        cap = self.get(name)
        if cap is None:
            raise CapabilityError(f"unknown capability: {name}")
        return cap

    def remove(self, name: str) -> bool:
        return self._caps.pop(name, None) is not None

    def enable(self, name: str) -> Capability:
        cap = self.require(name)
        cap.enabled = True
        return cap

    def disable(self, name: str) -> Capability:
        cap = self.require(name)
        cap.enabled = False
        return cap

    def list(self, *, enabled_only: bool = False) -> list[Capability]:
        caps = self._caps.values()
        if enabled_only:
            caps = [c for c in caps if c.enabled]
        return sorted(caps, key=lambda c: c.name)

    def names(self, *, enabled_only: bool = False) -> list[str]:
        return [c.name for c in self.list(enabled_only=enabled_only)]

    def to_dict(self) -> dict[str, Any]:
        return {name: cap.to_dict() for name, cap in self._caps.items()}

    def load_dict(self, data: dict[str, Any]) -> int:
        """Load declarations, skipping corrupt entries. Returns count loaded."""
        loaded = 0
        for name, raw in (data or {}).items():
            try:
                cap = Capability.from_dict(raw if isinstance(raw, dict) else {"name": name})
                self.declare(cap)
                loaded += 1
            except (CapabilityError, TypeError):
                continue
        return loaded

    def __len__(self) -> int:
        return len(self._caps)
