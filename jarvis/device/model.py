"""Device model for the JARVIS distributed device fabric.

A Device is a strongly typed record for one JARVIS node (laptop, phone,
Raspberry Pi, sensor, ...). The fabric owns connectivity/lifecycle state;
the World Model mirrors what a device *means*, never the reverse.

Lifecycle is an explicit validated state machine::

    DISCOVERED -> REGISTERED -> TRUST_PENDING -> TRUSTED -> ONLINE <-> OFFLINE

plus terminal/restriction states REVOKED, QUARANTINED and DISABLED.

Trust is stored alongside lifecycle and is only ever changed through the
same validated transitions (registry.set_trust), so the two can never drift.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from ..core.types import new_id, now

FABRIC_VERSION = 1
PROTOCOL_VERSION = 1
CAPABILITY_VERSION = 1
SCHEMA_VERSION = 1

#: Known device types. The list is documentation, not a closed set:
#: any slug-like type string is accepted so future hardware just works.
DEVICE_TYPES = (
    "laptop",
    "desktop",
    "phone",
    "tablet",
    "raspberry_pi",
    "server",
    "camera",
    "sensor",
    "robot",
    "vehicle",
    "virtual",
    "unknown",
)

_TYPE_RE = re.compile(r"^[a-z0-9_]{1,32}$")
_NAME_RE = re.compile(r"^[A-Za-z0-9 _.\-]{1,80}$")


class LifecycleState(str, Enum):
    DISCOVERED = "discovered"
    REGISTERED = "registered"
    TRUST_PENDING = "trust_pending"
    TRUSTED = "trusted"
    ONLINE = "online"
    OFFLINE = "offline"
    REVOKED = "revoked"
    QUARANTINED = "quarantined"
    DISABLED = "disabled"


class TrustState(str, Enum):
    UNTRUSTED = "untrusted"
    PENDING = "pending"
    TRUSTED = "trusted"
    REVOKED = "revoked"
    QUARANTINED = "quarantined"


#: Validated lifecycle transitions. Anything not listed raises LifecycleError.
TRANSITIONS: dict[LifecycleState, set[LifecycleState]] = {
    LifecycleState.DISCOVERED: {
        LifecycleState.REGISTERED,
        LifecycleState.REVOKED,
        LifecycleState.QUARANTINED,
        LifecycleState.DISABLED,
    },
    LifecycleState.REGISTERED: {
        LifecycleState.TRUST_PENDING,
        LifecycleState.REVOKED,
        LifecycleState.QUARANTINED,
        LifecycleState.DISABLED,
    },
    LifecycleState.TRUST_PENDING: {
        LifecycleState.TRUSTED,
        LifecycleState.REVOKED,
        LifecycleState.QUARANTINED,
        LifecycleState.DISABLED,
    },
    LifecycleState.TRUSTED: {
        LifecycleState.ONLINE,
        LifecycleState.OFFLINE,
        LifecycleState.REVOKED,
        LifecycleState.QUARANTINED,
        LifecycleState.DISABLED,
    },
    LifecycleState.ONLINE: {
        LifecycleState.OFFLINE,
        LifecycleState.REVOKED,
        LifecycleState.QUARANTINED,
        LifecycleState.DISABLED,
    },
    LifecycleState.OFFLINE: {
        LifecycleState.ONLINE,
        LifecycleState.REVOKED,
        LifecycleState.QUARANTINED,
        LifecycleState.DISABLED,
    },
    LifecycleState.DISABLED: {
        LifecycleState.TRUST_PENDING,
        LifecycleState.REVOKED,
    },
    LifecycleState.QUARANTINED: {
        LifecycleState.TRUST_PENDING,
        LifecycleState.REVOKED,
    },
    LifecycleState.REVOKED: set(),  # terminal: re-admit only via fresh registration
}

#: Lifecycle states that keep the node's prior trust when entered.
_TRUST_OF: dict[LifecycleState, TrustState] = {
    LifecycleState.DISCOVERED: TrustState.UNTRUSTED,
    LifecycleState.REGISTERED: TrustState.PENDING,
    LifecycleState.TRUST_PENDING: TrustState.PENDING,
    LifecycleState.TRUSTED: TrustState.TRUSTED,
    LifecycleState.ONLINE: TrustState.TRUSTED,
    LifecycleState.OFFLINE: TrustState.TRUSTED,
    LifecycleState.REVOKED: TrustState.REVOKED,
    LifecycleState.QUARANTINED: TrustState.QUARANTINED,
}


class LifecycleError(ValueError):
    """Raised when a lifecycle transition is invalid."""


class DeviceError(ValueError):
    """Raised when device data fails validation."""


def validate_device_type(device_type: str) -> str:
    """Accept any slug-like type so future hardware just works."""
    if not isinstance(device_type, str) or not _TYPE_RE.match(device_type):
        raise DeviceError(f"invalid device_type: {device_type!r}")
    return device_type


def validate_device_name(name: str) -> str:
    if not isinstance(name, str) or not _NAME_RE.match(name.strip()):
        raise DeviceError(f"invalid device name: {name!r}")
    return name.strip()


def check_transition(frm: LifecycleState, to: LifecycleState) -> None:
    if to not in TRANSITIONS.get(frm, set()):
        raise LifecycleError(f"invalid lifecycle transition: {frm.value} -> {to.value}")


@dataclass
class Device:
    """One node in the device fabric."""

    device_id: str = field(default_factory=lambda: new_id("dev"))
    node_id: str = ""
    name: str = "unnamed"
    device_type: str = "unknown"
    platform: str = ""
    platform_version: str = ""
    architecture: str = ""
    hostname: str = ""
    capabilities: dict[str, int] = field(default_factory=dict)  # name -> version
    lifecycle: LifecycleState = LifecycleState.DISCOVERED
    trust: TrustState = TrustState.UNTRUSTED
    last_seen: float = 0.0
    first_seen: float = field(default_factory=now)
    heartbeat_interval_s: float = 60.0
    consecutive_misses: int = 0
    location: str = ""  # room/area name or "" == UNKNOWN (never guessed)
    owner: str = ""
    network: str = ""  # transport network name or "" == unknown
    node_version: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    identity: dict[str, Any] = field(default_factory=dict)
    version: int = 1
    provenance: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=now)
    updated_at: float = field(default_factory=now)
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if isinstance(self.lifecycle, str):
            self.lifecycle = LifecycleState(self.lifecycle)
        if isinstance(self.trust, str):
            self.trust = TrustState(self.trust)
        validate_device_name(self.name)
        validate_device_type(self.device_type)

    @property
    def connectivity(self) -> str:
        if self.lifecycle == LifecycleState.ONLINE:
            return "online"
        if self.lifecycle == LifecycleState.OFFLINE:
            return "offline"
        return "unknown"

    def can_execute(self) -> bool:
        """Only an online, trusted node may execute routed commands."""
        return (
            self.lifecycle == LifecycleState.ONLINE
            and self.trust == TrustState.TRUSTED
        )

    def block_reason(self) -> str:
        if self.trust == TrustState.REVOKED or self.lifecycle == LifecycleState.REVOKED:
            return "device is revoked"
        if self.trust == TrustState.QUARANTINED or self.lifecycle == LifecycleState.QUARANTINED:
            return "device is quarantined"
        if self.lifecycle == LifecycleState.DISABLED:
            return "device is disabled"
        if self.lifecycle != LifecycleState.ONLINE:
            return f"device is not online (lifecycle={self.lifecycle.value})"
        if self.trust != TrustState.TRUSTED:
            return f"device is not trusted (trust={self.trust.value})"
        return ""

    def apply_lifecycle(self, to: LifecycleState) -> None:
        check_transition(self.lifecycle, to)
        self.lifecycle = to
        if to != LifecycleState.DISABLED:
            # DISABLED is a restriction, not a trust verdict: keep prior trust.
            self.trust = _TRUST_OF[to]
        self.updated_at = now()

    def touch(self, at: float | None = None) -> None:
        self.last_seen = at if at is not None else now()
        self.consecutive_misses = 0
        self.updated_at = self.last_seen

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["lifecycle"] = self.lifecycle.value
        data["trust"] = self.trust.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Device":
        if not isinstance(data, dict):
            raise DeviceError("device record must be an object")
        known = {f for f in cls.__dataclass_fields__}
        clean = {k: v for k, v in data.items() if k in known}
        if "device_id" not in clean or not clean["device_id"]:
            raise DeviceError("device record missing device_id")
        return cls(**clean)
