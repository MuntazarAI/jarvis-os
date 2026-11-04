"""Security & Reliability (M11).

Operational observability and security hardening for the OMNINET internet
subsystem. Builds on existing JARVIS systems:
- jarvis/policy/policy.py — PolicyEngine (audit, emergency stop, grants)
- jarvis/security/guards.py — SSRF blocking, injection scanning
- jarvis/core/internet.py — controlled internet access

All metrics are local-only. Nothing sends telemetry externally.
Security policies never auto-change — human approval required for any
policy modification.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from ..core.internet import InternetAccess
from ..core.logging import get_module_logger
from ..core.types import now
from ..omninet.connectors import ConnectorRegistry
from ..omninet.discovery import SearchEngine
from ..omninet.exploration import EnhancedBrowserAgent
from ..omninet.public_data import PublicDataRegistry
from ..omninet.crawler import BoundedCrawler
from ..omninet.observatory import LiveObservatory
from ..omninet.knowledge_graph import KnowledgeGraphStore
from ..omninet.threat_intel import ThreatIntel
from ..omninet.distributed import DistributedIntelligence
from ..policy.policy import PolicyEngine

log = get_module_logger(__name__)


# ============================================================================
# Security metrics
# ============================================================================


@dataclass
class ProviderMetric:
    """Metrics for a single provider/connector."""
    name: str
    kind: str
    requests_total: int = 0
    failures_total: int = 0
    successes_total: int = 0
    total_latency_ms: float = 0.0
    max_latency_ms: float = 0.0
    bytes_read_total: int = 0
    injection_flags_total: int = 0
    policy_denials: int = 0
    ssrf_blocks: int = 0
    last_success_at: float | None = None
    last_failure_at: float | None = None

    @property
    def success_rate(self) -> float:
        total = self.requests_total
        if total == 0:
            return 1.0
        return round(self.successes_total / total, 4)

    @property
    def average_latency_ms(self) -> float:
        if self.successes_total == 0:
            return 0.0
        return round(self.total_latency_ms / self.successes_total, 2)

    @property
    def failure_rate(self) -> float:
        total = self.requests_total
        if total == 0:
            return 0.0
        return round(self.failures_total / total, 4)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["success_rate"] = self.success_rate
        data["failure_rate"] = self.failure_rate
        data["average_latency_ms"] = self.average_latency_ms
        return data


@dataclass
class SecurityEvent:
    """A security-relevant event."""
    event_id: str
    event_type: str  # ssrf_block | injection_detected | policy_denial | emergency_stop | grant_revoked | ...
    severity: str  # low | medium | high | critical
    description: str
    source: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.monotonic)
    resolved: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SecurityMetrics:
    """Tracks security and reliability metrics for all OMNINET components.

    Local-only. No external telemetry. Metrics are reset on restart
    unless persisted (opt-in).
    """

    def __init__(self) -> None:
        self._providers: dict[str, ProviderMetric] = {}
        self._events: list[SecurityEvent] = []
        self._event_counter: int = 0
        self._started_at = time.monotonic()
        self._emergency_stop_engagements: int = 0
        self._policy_denials_total: int = 0
        self._ssrf_blocks_total: int = 0
        self._injection_detections_total: int = 0

    # -- provider metrics ----------------------------------------------

    def record_request(
        self,
        provider: str,
        kind: str,
        success: bool,
        latency_ms: float = 0.0,
        bytes_read: int = 0,
        injection_flags: list[str] | None = None,
    ) -> None:
        """Record a provider request outcome."""
        m = self._providers.get(provider)
        if m is None:
            m = ProviderMetric(name=provider, kind=kind)
            self._providers[provider] = m

        m.requests_total += 1
        m.bytes_read_total += bytes_read
        if injection_flags:
            m.injection_flags_total += len(injection_flags)

        if success:
            m.successes_total += 1
            m.last_success_at = time.monotonic()
            if latency_ms > 0:
                m.total_latency_ms += latency_ms
                m.max_latency_ms = max(m.max_latency_ms, latency_ms)
        else:
            m.failures_total += 1
            m.last_failure_at = time.monotonic()

    def record_policy_denial(self, provider: str, reason: str) -> None:
        """Record a PolicyEngine denial."""
        self._policy_denials_total += 1
        m = self._providers.get(provider)
        if m is not None:
            m.policy_denials += 1
        self._log_event(
            "policy_denial",
            "medium",
            f"PolicyEngine denied request from {provider}",
            source=provider,
            details={"reason": reason},
        )

    def record_ssrf_block(self, provider: str, reason: str) -> None:
        """Record an SSRF block."""
        self._ssrf_blocks_total += 1
        m = self._providers.get(provider)
        if m is not None:
            m.ssrf_blocks += 1
        self._log_event(
            "ssrf_block",
            "high",
            f"SSRF guard blocked request from {provider}",
            source=provider,
            details={"reason": reason},
        )

    def record_injection_detection(
        self,
        provider: str,
        flags: list[str],
    ) -> None:
        """Record prompt-injection detection in response."""
        self._injection_detections_total += 1
        m = self._providers.get(provider)
        if m is not None:
            m.injection_flags_total += len(flags)
        self._log_event(
            "injection_detected",
            "high",
            f"Prompt injection markers detected from {provider}",
            source=provider,
            details={"flags": flags[:5]},
        )

    def record_emergency_stop(self, reason: str = "") -> None:
        """Record emergency stop engagement."""
        self._emergency_stop_engagements += 1
        self._log_event(
            "emergency_stop",
            "critical",
            f"Emergency stop engaged: {reason or 'manual'}",
            details={"reason": reason},
        )

    # -- events --------------------------------------------------------

    def _log_event(
        self,
        event_type: str,
        severity: str,
        description: str,
        source: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        self._event_counter += 1
        event = SecurityEvent(
            event_id=f"sec-{self._event_counter}",
            event_type=event_type,
            severity=severity,
            description=description,
            source=source,
            details=details or {},
        )
        self._events.append(event)
        # Keep events bounded
        if len(self._events) > 1000:
            self._events = self._events[-1000:]
        log.warning(
            "Security event",
            event_id=event.event_id,
            type=event_type,
            severity=severity,
            description=description,
        )

    def get_events(
        self,
        event_type: str | None = None,
        min_severity: str | None = None,
        limit: int = 100,
    ) -> list[SecurityEvent]:
        """Get security events, optionally filtered."""
        severity_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        min_level = severity_order.get(min_severity, 0) if min_severity else 0

        results = []
        for ev in self._events:
            if event_type is not None and ev.event_type != event_type:
                continue
            if min_severity is not None and severity_order.get(ev.severity, 0) < min_level:
                continue
            results.append(ev)
        results.sort(key=lambda e: -e.timestamp)
        return results[:limit]

    # -- summary -------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        """Return overall security metrics summary."""
        providers = {name: m.to_dict() for name, m in self._providers.items()}
        total_requests = sum(m.requests_total for m in self._providers.values())
        total_failures = sum(m.failures_total for m in self._providers.values())
        total_bytes = sum(m.bytes_read_total for m in self._providers.values())

        return {
            "uptime_seconds": round(time.monotonic() - self._started_at, 2),
            "providers": providers,
            "provider_count": len(self._providers),
            "total_requests": total_requests,
            "total_failures": total_failures,
            "overall_success_rate": round(
                (total_requests - total_failures) / max(total_requests, 1), 4
            ),
            "total_bytes_read": total_bytes,
            "policy_denials_total": self._policy_denials_total,
            "ssrf_blocks_total": self._ssrf_blocks_total,
            "injection_detections_total": self._injection_detections_total,
            "emergency_stop_engagements": self._emergency_stop_engagements,
            "recent_events": [e.to_dict() for e in self.get_events(limit=10)],
        }


# ============================================================================
# Security auditor
# ============================================================================


class SecurityAuditor:
    """Audits OMNINET security configuration and runtime state.

    All checks are read-only. No auto-remediation — human review required
    for any policy change.
    """

    def __init__(
        self,
        policy: PolicyEngine,
        internet: InternetAccess,
        metrics: SecurityMetrics,
        connectors: ConnectorRegistry | None = None,
        search: SearchEngine | None = None,
        browser: EnhancedBrowserAgent | None = None,
        public_data: PublicDataRegistry | None = None,
        crawler: BoundedCrawler | None = None,
        observatory: LiveObservatory | None = None,
        knowledge_graph: KnowledgeGraphStore | None = None,
        threat_intel: ThreatIntel | None = None,
        distributed: DistributedIntelligence | None = None,
    ) -> None:
        self.policy = policy
        self.internet = internet
        self.metrics = metrics
        self.connectors = connectors
        self.search = search
        self.browser = browser
        self.public_data = public_data
        self.crawler = crawler
        self.observatory = observatory
        self.knowledge_graph = knowledge_graph
        self.threat_intel = threat_intel
        self.distributed = distributed

    def audit_configuration(self) -> dict[str, Any]:
        """Audit security configuration. Returns findings + recommendations."""
        findings: list[dict[str, Any]] = []

        # Check PolicyEngine configuration
        policy_conflicts = self.policy.conflicts()
        if policy_conflicts:
            for conflict in policy_conflicts:
                findings.append({
                    "severity": "high",
                    "category": "policy_conflict",
                    "description": conflict,
                    "recommendation": "Resolve policy conflict manually",
                })

        # Check emergency stop state
        if self.policy.emergency_stop_engaged():
            findings.append({
                "severity": "critical",
                "category": "emergency_stop",
                "description": "Emergency stop is engaged — all actions blocked",
                "recommendation": "Review and release emergency stop if safe",
            })

        # Check internet allowlist size
        allowlist_size = len(self.internet.allowed_domains)
        if allowlist_size > 100:
            findings.append({
                "severity": "medium",
                "category": "allowlist_size",
                "description": f"Internet allowlist has {allowlist_size} domains",
                "recommendation": "Review allowlist for unnecessary domains",
            })

        # Check connector count
        if self.connectors is not None:
            connector_count = len(self.connectors.list())
            findings.append({
                "severity": "info",
                "category": "connector_count",
                "description": f"{connector_count} connectors registered",
                "recommendation": "Review connector necessity",
            })

        # Check distributed intelligence state
        if self.distributed is not None and self.distributed.is_enabled():
            findings.append({
                "severity": "medium",
                "category": "distributed_enabled",
                "description": "Distributed intelligence is enabled",
                "recommendation": "Verify worker nodes are authorized and bounded",
            })

        return {
            "audit_id": f"audit-{int(time.monotonic())}",
            "timestamp": time.monotonic(),
            "findings": findings,
            "finding_count": len(findings),
            "critical_count": sum(1 for f in findings if f["severity"] == "critical"),
            "high_count": sum(1 for f in findings if f["severity"] == "high"),
            "medium_count": sum(1 for f in findings if f["severity"] == "medium"),
        }

    def audit_runtime(self) -> dict[str, Any]:
        """Audit runtime security state."""
        metrics_summary = self.metrics.summary()

        findings: list[dict[str, Any]] = []

        # High failure rate providers
        for name, m in metrics_summary["providers"].items():
            if m["failure_rate"] > 0.5 and m["requests_total"] > 5:
                findings.append({
                    "severity": "medium",
                    "category": "provider_unreliable",
                    "description": f"Provider {name} has {m['failure_rate']:.0%} failure rate",
                    "recommendation": "Investigate provider connectivity or remove",
                })

        # Recent critical events
        critical_events = [
            e for e in metrics_summary["recent_events"]
            if e.get("severity") == "critical"
        ]
        if critical_events:
            findings.append({
                "severity": "critical",
                "category": "recent_critical_events",
                "description": f"{len(critical_events)} critical security events",
                "recommendation": "Review and resolve critical events",
            })

        return {
            "audit_id": f"runtime-audit-{int(time.monotonic())}",
            "timestamp": time.monotonic(),
            "metrics": metrics_summary,
            "findings": findings,
            "finding_count": len(findings),
        }

    def full_audit(self) -> dict[str, Any]:
        """Run complete configuration + runtime audit."""
        return {
            "audit_id": f"full-audit-{int(time.monotonic())}",
            "timestamp": time.monotonic(),
            "configuration": self.audit_configuration(),
            "runtime": self.audit_runtime(),
        }


# ============================================================================
# Security manager
# ============================================================================


class SecurityManager:
    """High-level security manager for OMNINET.

    Coordinates metrics, auditing, and emergency stop. All operations
    are read-only except emergency stop which requires explicit action.
    """

    def __init__(
        self,
        policy: PolicyEngine,
        internet: InternetAccess,
        metrics: SecurityMetrics | None = None,
        auditor: SecurityAuditor | None = None,
    ) -> None:
        self.policy = policy
        self.internet = internet
        self.metrics = metrics or SecurityMetrics()
        self.auditor = auditor or SecurityAuditor(
            policy, internet, self.metrics
        )
        self._last_audit: dict[str, Any] | None = None

    def record_request(
        self,
        provider: str,
        kind: str,
        success: bool,
        latency_ms: float = 0.0,
        bytes_read: int = 0,
        injection_flags: list[str] | None = None,
    ) -> None:
        """Record a provider request for metrics."""
        self.metrics.record_request(
            provider, kind, success, latency_ms, bytes_read, injection_flags
        )

    def record_policy_denial(self, provider: str, reason: str) -> None:
        self.metrics.record_policy_denial(provider, reason)

    def record_ssrf_block(self, provider: str, reason: str) -> None:
        self.metrics.record_ssrf_block(provider, reason)

    def record_injection_detection(
        self,
        provider: str,
        flags: list[str],
    ) -> None:
        self.metrics.record_injection_detection(provider, flags)

    def record_emergency_stop(self, reason: str = "") -> None:
        self.metrics.record_emergency_stop(reason)

    def get_metrics(self) -> dict[str, Any]:
        return self.metrics.summary()

    def run_audit(self) -> dict[str, Any]:
        """Run a full security audit and store the result."""
        self._last_audit = self.auditor.full_audit()
        return self._last_audit

    def get_last_audit(self) -> dict[str, Any] | None:
        return self._last_audit

    def emergency_stop(self, reason: str = "manual") -> None:
        """Engage emergency stop. Requires explicit action."""
        self.policy.engage_stop()
        self.metrics.record_emergency_stop(reason)
        log.critical("Emergency stop engaged", reason=reason)

    def release_emergency_stop(self) -> bool:
        """Release emergency stop. Requires explicit action."""
        released = self.policy.release_stop()
        if released:
            log.info("Emergency stop released")
        return released

    def status(self) -> dict[str, Any]:
        """Return combined security status."""
        return {
            "emergency_stop_engaged": self.policy.emergency_stop_engaged(),
            "metrics": self.metrics.summary(),
            "last_audit": self._last_audit,
            "policy_conflicts": self.policy.conflicts(),
        }


__all__ = [
    "ProviderMetric",
    "SecurityEvent",
    "SecurityMetrics",
    "SecurityAuditor",
    "SecurityManager",
]
