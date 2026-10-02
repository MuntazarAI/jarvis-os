"""Distributed device fabric for JARVIS.

First-class subsystem owning node identity, capability declarations,
lifecycle/trust, presence, policy-gated command routing, and world/spatial
mirroring. See docs/DEVICE_FABRIC.md.
"""

from .capabilities import (
    WELL_KNOWN,
    Capability,
    CapabilityError,
    CapabilityRegistry,
    validate_capability_name,
)
from .fabric import DeviceFabric, FabricError
from .identity import (
    AUTH_METHODS,
    AuthContext,
    IdentityError,
    NodeIdentity,
    current_limitation,
    generate_identity,
)
from .model import (
    CAPABILITY_VERSION,
    DEVICE_TYPES,
    FABRIC_VERSION,
    PROTOCOL_VERSION,
    Device,
    DeviceError,
    LifecycleError,
    LifecycleState,
    TrustState,
    check_transition,
)
from .protocol import FabricMessage, MessageType, ProtocolError, make_error
from .registry import DeviceRegistry, RegistryError, VersionConflict
from .router import DeviceRouter, RoutingError
from .security import FabricSecurityError, audit_record, scrub
from .telemetry import Telemetry, TelemetryError, is_stale
from .transport import (
    InProcessTransport,
    LocalNode,
    Transport,
    TransportError,
    available_transports,
    get_transport,
    register_transport,
)

__all__ = [
    "AUTH_METHODS",
    "WELL_KNOWN",
    "CAPABILITY_VERSION",
    "DEVICE_TYPES",
    "FABRIC_VERSION",
    "PROTOCOL_VERSION",
    "AuthContext",
    "Capability",
    "CapabilityError",
    "CapabilityRegistry",
    "Device",
    "DeviceError",
    "DeviceFabric",
    "DeviceRegistry",
    "DeviceRouter",
    "FabricError",
    "FabricMessage",
    "FabricSecurityError",
    "IdentityError",
    "InProcessTransport",
    "LifecycleError",
    "LifecycleState",
    "LocalNode",
    "MessageType",
    "NodeIdentity",
    "ProtocolError",
    "RegistryError",
    "RoutingError",
    "Telemetry",
    "TelemetryError",
    "Transport",
    "TransportError",
    "VersionConflict",
    "audit_record",
    "available_transports",
    "check_transition",
    "current_limitation",
    "generate_identity",
    "get_transport",
    "is_stale",
    "make_error",
    "register_transport",
    "scrub",
    "validate_capability_name",
]
