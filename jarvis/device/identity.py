"""Stable node identity for the device fabric.

Every JARVIS node (including this core) owns a persistent identity: a
stable ``node_id`` plus a stable ``device_id``. Identity is *identification*,
not authentication: nothing in 3.8 trusts a node because of its id.

Trust always comes from an explicit, recorded human/policy decision
(``registry.set_trust`` / ``fabric.trust_device`` with actor + reason).
``AuthContext`` records *how* a decision was verified so future transports
(mTLS, public-key signatures) can plug in without redesigning the core.

Current trust limitation (honest, by design): the in-process transport
cannot cryptographically prove which node sent a message. Remote transports
MUST set ``auth.method`` to something stronger than ``explicit-approval``
before trust is granted, and ``require_verified_transport`` enforces that.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from ..core.types import new_id, now
from .model import CAPABILITY_VERSION, PROTOCOL_VERSION

#: Auth methods the fabric understands today. Anything stronger can be
#: added without changing the trust-decision path.
AUTH_METHODS = (
    "explicit-approval",  # a human approved this node out-of-band; no crypto proof
    "local-process",  # same process/machine; OS identity, not network identity
    # Future: "mtls", "ed25519".
)

#: Transports that cannot prove sender identity. Nodes arriving over these
#: may reach TRUST_PENDING but must never auto-advance to TRUSTED.
UNVERIFIED_TRANSPORTS = ("in-process",)


class IdentityError(ValueError):
    """Raised when identity data fails validation."""


@dataclass
class AuthContext:
    """How (and whether) a node's identity was verified."""

    method: str = "explicit-approval"
    verified: bool = False
    verified_by: str = ""
    verified_at: float = 0.0
    note: str = ""

    def __post_init__(self) -> None:
        if self.method not in AUTH_METHODS:
            raise IdentityError(f"unknown auth method: {self.method!r}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AuthContext":
        if not isinstance(data, dict):
            raise IdentityError("auth context must be an object")
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class NodeIdentity:
    """Persistent identity of one node (local core or remote device)."""

    node_id: str = field(default_factory=lambda: new_id("node"))
    device_id: str = field(default_factory=lambda: new_id("dev"))
    display_name: str = ""
    created_at: float = field(default_factory=now)
    protocol_version: int = PROTOCOL_VERSION
    capability_version: int = CAPABILITY_VERSION

    def __post_init__(self) -> None:
        if not self.node_id or not isinstance(self.node_id, str):
            raise IdentityError("node_id must be a non-empty string")
        if not self.device_id or not isinstance(self.device_id, str):
            raise IdentityError("device_id must be a non-empty string")
        if self.protocol_version < 1:
            raise IdentityError("protocol_version must be >= 1")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NodeIdentity":
        if not isinstance(data, dict):
            raise IdentityError("identity must be an object")
        known = {f for f in cls.__dataclass_fields__}
        clean = {k: v for k, v in data.items() if k in known}
        if "node_id" not in clean or "device_id" not in clean:
            raise IdentityError("identity missing node_id/device_id")
        return cls(**clean)


def generate_identity(display_name: str = "", device_id: str = "") -> NodeIdentity:
    """Create a fresh stable identity for a node being enrolled."""
    return NodeIdentity(
        device_id=device_id or new_id("dev"),
        display_name=display_name[:80] if display_name else "",
    )


def current_limitation() -> str:
    return (
        "3.8 fabric identity is stable but unauthenticated: node_ids are "
        "self-asserted over the in-process transport. Trust requires an "
        "explicit human approval (actor + reason recorded); future transports "
        "must verify sender identity (mTLS / public-key) before trust."
    )
