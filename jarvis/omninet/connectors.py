"""OMNINET Universal Internet Gateway (M1).

Connector base class, registry, health checks, and resource quotas.
Builds on jarvis/core/internet.py, jarvis/security/guards.py,
jarvis/policy/policy.py.

Every connector is PolicyEngine-gated. No outbound request without
explicit approval.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from ..core.internet import InternetAccess
from ..core.logging import get_module_logger
from ..core.types import ActionPlan, RiskLevel
from ..policy.policy import PolicyEngine
from ..security.guards import is_safe_url, scan_injection

log = get_module_logger(__name__)


@dataclass
class ConnectorSpec:
    """Specification for a registered connector."""
    name: str
    kind: str  # http | graphql | websocket | sse | webhook | git | rss | search | ...
    description: str = ""
    enabled: bool = True
    rate_limit_s: float = 1.0
    max_concurrent: int = 4
    timeout_s: float = 15.0
    max_bytes: int = 1_000_000
    trust_note: str = "unknown"
    trust_basis: str = "unknown"  # measured | configured | documented | unknown


@dataclass
class ConnectorResult:
    """Normalized result from any connector."""
    connector: str
    kind: str
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    fetched_at: float = field(default_factory=time.monotonic)
    latency_ms: float = 0.0
    bytes_read: int = 0
    cache_hit: bool = False
    injection_flags: list[str] = field(default_factory=list)


class Connector:
    """Base class for all OMNINET connectors.

    Every connector must:
    - Be registered in ConnectorRegistry before use
    - Pass every outbound request through PolicyEngine
    - Respect SSRF guards and injection scanning
    - Honor timeouts, size caps, and rate limits
    - Return normalized ConnectorResult
    """

    def __init__(
        self,
        spec: ConnectorSpec,
        policy: PolicyEngine,
        internet: InternetAccess,
        actor: str = "jarvis",
    ) -> None:
        self.spec = spec
        self.policy = policy
        self.internet = internet
        self.actor = actor
        self._active: int = 0
        self._bytes_total: int = 0
        self._requests_total: int = 0
        self._failures_total: int = 0
        self._last_health: dict[str, Any] | None = None

    # -- resource accounting -------------------------------------------

    @property
    def active(self) -> int:
        return self._active

    @property
    def bytes_total(self) -> int:
        return self._bytes_total

    @property
    def requests_total(self) -> int:
        return self._requests_total

    @property
    def failures_total(self) -> int:
        return self._failures_total

    def within_quota(self) -> bool:
        """Check concurrency, byte, and request quotas."""
        if self._active >= self.spec.max_concurrent:
            return False
        if self._bytes_total >= self.spec.max_bytes * 100:
            return False
        return True

    # -- policy gate ---------------------------------------------------

    def _evaluate(
        self, action: str, args: dict[str, Any], required_permissions: list[str]
    ) -> Any:
        plan = ActionPlan(
            action=action,
            args=args,
            required_permissions=required_permissions,
            risk=RiskLevel.LOW,
        )
        return self.policy.evaluate(self.actor, plan)

    def _guard_url(self, url: str) -> tuple[bool, str]:
        """SSRF + injection guard on a URL before any request."""
        safe, reason = is_safe_url(url)
        if not safe:
            return False, reason
        scan = scan_injection(url)
        if not scan["clean"]:
            return False, f"injection markers in URL: {scan['hits']}"
        return True, "ok"

    # -- connector API -------------------------------------------------

    def fetch(self, url: str, **kwargs: Any) -> ConnectorResult:
        """Fetch a URL. Must be implemented by subclasses."""
        raise NotImplementedError

    def health_check(self) -> dict[str, Any]:
        """Return connector health status."""
        return {
            "name": self.spec.name,
            "kind": self.spec.kind,
            "enabled": self.spec.enabled,
            "active": self._active,
            "requests_total": self._requests_total,
            "failures_total": self._failures_total,
            "bytes_total": self._bytes_total,
            "within_quota": self.within_quota(),
            "last_health": self._last_health,
        }

    def close(self) -> None:
        """Release connector resources. Default: no-op."""


class ConnectorRegistry:
    """Registry of OMNINET connectors. Registration + discovery + health."""

    def __init__(self) -> None:
        self._connectors: dict[str, Connector] = {}

    def register(self, connector: Connector) -> None:
        self._connectors[connector.spec.name] = connector
        log.info("Connector registered", name=connector.spec.name, kind=connector.spec.kind)

    def get(self, name: str) -> Connector | None:
        return self._connectors.get(name)

    def enabled(self, kind: str = "") -> list[Connector]:
        return [c for c in self._connectors.values()
                if c.spec.enabled and (not kind or c.spec.kind == kind)]

    def list(self) -> list[dict[str, Any]]:
        return [c.health_check() for c in self._connectors.values()]

    def health_all(self) -> dict[str, Any]:
        return {name: c.health_check() for name, c in self._connectors.items()}


__all__ = [
    "ConnectorSpec",
    "ConnectorResult",
    "Connector",
    "ConnectorRegistry",
]
