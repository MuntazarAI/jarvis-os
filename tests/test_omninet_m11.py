"""OMNINET M11 — Security & Reliability tests.

Tests metrics tracking, security auditing, emergency stop, and
PolicyEngine integration. All tests are local-only — no external
telemetry.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from jarvis.core.config import JarvisConfig
from jarvis.core.internet import InternetAccess
from jarvis.core.types import ActionPlan, RiskLevel
from jarvis.omninet import (
    ConnectorRegistry,
    HttpConnector,
    SecurityAuditor,
    SecurityManager,
    SecurityMetrics,
)
from jarvis.omninet.security import ProviderMetric
from jarvis.policy.policy import PolicyEngine


# -- fixtures -----------------------------------------------------------


def _make_policy_and_internet(home: str | None = None):
    cfg = JarvisConfig()
    if home:
        cfg.paths.home = Path(home)
    policy = PolicyEngine(cfg)
    internet = InternetAccess(policy)
    policy.grant("jarvis", "net.fetch")
    internet.allowed_domains.add("example.com")
    policy.grant("jarvis", "internet:example.com")
    internet.request_domain_access(
        agent_id="jarvis", domain="example.com",
        max_requests_per_hour=100, grant_seconds=3600,
    )
    return policy, internet


# -- SecurityMetrics tests ----------------------------------------------


def test_metrics_record_request_success():
    metrics = SecurityMetrics()
    metrics.record_request(
        provider="duckduckgo",
        kind="search",
        success=True,
        latency_ms=120.5,
        bytes_read=5000,
    )
    m = metrics._providers["duckduckgo"]
    assert m.requests_total == 1
    assert m.successes_total == 1
    assert m.failures_total == 0
    assert m.success_rate == 1.0
    assert m.average_latency_ms == 120.5


def test_metrics_record_request_failure():
    metrics = SecurityMetrics()
    metrics.record_request(
        provider="brave",
        kind="search",
        success=False,
        latency_ms=0.0,
    )
    m = metrics._providers["brave"]
    assert m.requests_total == 1
    assert m.failures_total == 1
    assert m.success_rate == 0.0


def test_metrics_policy_denial():
    metrics = SecurityMetrics()
    metrics.record_policy_denial("http", "missing permission")
    assert metrics._policy_denials_total == 1
    events = metrics.get_events(event_type="policy_denial")
    assert len(events) == 1
    assert events[0].severity == "medium"


def test_metrics_ssrf_block():
    metrics = SecurityMetrics()
    metrics.record_ssrf_block("http", "private IP")
    assert metrics._ssrf_blocks_total == 1
    events = metrics.get_events(event_type="ssrf_block")
    assert len(events) == 1
    assert events[0].severity == "high"


def test_metrics_injection_detection():
    metrics = SecurityMetrics()
    metrics.record_injection_detection("browser", ["ignore previous instructions"])
    assert metrics._injection_detections_total == 1
    events = metrics.get_events(event_type="injection_detected")
    assert len(events) == 1
    assert events[0].severity == "high"


def test_metrics_emergency_stop():
    metrics = SecurityMetrics()
    metrics.record_emergency_stop("manual test")
    assert metrics._emergency_stop_engagements == 1
    events = metrics.get_events(event_type="emergency_stop")
    assert len(events) == 1
    assert events[0].severity == "critical"


def test_metrics_summary():
    metrics = SecurityMetrics()
    metrics.record_request("a", "search", True, latency_ms=100.0, bytes_read=1000)
    metrics.record_request("b", "search", False, latency_ms=0.0)
    summary = metrics.summary()
    assert summary["total_requests"] == 2
    assert summary["total_failures"] == 1
    assert summary["overall_success_rate"] == 0.5
    assert summary["provider_count"] == 2


def test_metrics_event_filtering():
    metrics = SecurityMetrics()
    metrics.record_policy_denial("a", "reason 1")
    metrics.record_ssrf_block("b", "reason 2")
    metrics.record_policy_denial("c", "reason 3")

    policy_events = metrics.get_events(event_type="policy_denial")
    assert len(policy_events) == 2

    ssrf_events = metrics.get_events(event_type="ssrf_block")
    assert len(ssrf_events) == 1

    high_severity = metrics.get_events(min_severity="high")
    assert len(high_severity) == 1  # only ssrf_block


# -- SecurityAuditor tests ----------------------------------------------


def test_auditor_configuration_no_conflicts():
    policy, internet = _make_policy_and_internet()
    metrics = SecurityMetrics()
    auditor = SecurityAuditor(policy, internet, metrics)
    result = auditor.audit_configuration()
    assert "audit_id" in result
    assert "findings" in result
    assert result["critical_count"] == 0


def test_auditor_emergency_stop_engaged():
    cfg = JarvisConfig()
    cfg.paths.home = Path(tempfile.mkdtemp(prefix="audit-test-"))
    policy = PolicyEngine(cfg)
    internet = InternetAccess(policy)
    metrics = SecurityMetrics()
    auditor = SecurityAuditor(policy, internet, metrics)

    policy.engage_stop()
    result = auditor.audit_configuration()
    assert result["critical_count"] == 1
    assert any(f["category"] == "emergency_stop" for f in result["findings"])

    policy.release_stop()


def test_auditor_full_audit():
    policy, internet = _make_policy_and_internet()
    metrics = SecurityMetrics()
    auditor = SecurityAuditor(policy, internet, metrics)
    result = auditor.full_audit()
    assert "configuration" in result
    assert "runtime" in result
    assert "audit_id" in result


# -- SecurityManager tests ----------------------------------------------


def test_manager_init():
    policy, internet = _make_policy_and_internet()
    manager = SecurityManager(policy, internet)
    assert manager is not None
    assert manager.metrics is not None


def test_manager_record_request():
    policy, internet = _make_policy_and_internet()
    manager = SecurityManager(policy, internet)
    manager.record_request(
        provider="test",
        kind="http",
        success=True,
        latency_ms=50.0,
        bytes_read=100,
    )
    metrics = manager.get_metrics()
    assert metrics["total_requests"] == 1


def test_manager_record_denial_and_block():
    policy, internet = _make_policy_and_internet()
    manager = SecurityManager(policy, internet)
    manager.record_policy_denial("http", "no permission")


def test_manager_emergency_stop_cycle():
    policy, internet = _make_policy_and_internet()
    manager = SecurityManager(policy, internet)

    assert policy.emergency_stop_engaged() is False
    manager.emergency_stop(reason="test")
    assert policy.emergency_stop_engaged() is True
    assert metrics_emergency_count(manager) == 1

    manager.release_emergency_stop()
    assert policy.emergency_stop_engaged() is False


def metrics_emergency_count(manager: SecurityManager) -> int:
    return manager.metrics._emergency_stop_engagements


def test_manager_status():
    policy, internet = _make_policy_and_internet()
    manager = SecurityManager(policy, internet)
    status = manager.status()
    assert "emergency_stop_engaged" in status
    assert "metrics" in status
    assert "policy_conflicts" in status
    assert status["emergency_stop_engaged"] is False


def test_manager_run_audit():
    policy, internet = _make_policy_and_internet()
    manager = SecurityManager(policy, internet)
    audit = manager.run_audit()
    assert "audit_id" in audit
    assert "configuration" in audit
    assert "runtime" in audit
    assert manager.get_last_audit() is audit


def test_manager_integration_with_connectors():
    policy, internet = _make_policy_and_internet()
    metrics = SecurityMetrics()
    registry = ConnectorRegistry()
    http = HttpConnector(policy, internet, actor="jarvis")
    registry.register(http)

    manager = SecurityManager(policy, internet, metrics=metrics)
    manager.record_request(
        provider="http",
        kind="http",
        success=True,
        latency_ms=200.0,
        bytes_read=2000,
    )
    summary = manager.get_metrics()
    assert summary["providers"]["http"]["requests_total"] == 1


def test_provider_metric_to_dict():
    m = ProviderMetric(name="test", kind="http")
    m.requests_total = 5
    m.successes_total = 4
    m.failures_total = 1
    d = m.to_dict()
    assert d["name"] == "test"
    assert d["success_rate"] == 0.8


def test_security_event_to_dict():
    from jarvis.omninet.security import SecurityEvent
    e = SecurityEvent(
        event_id="evt-1",
        event_type="test",
        severity="low",
        description="test event",
    )
    d = e.to_dict()
    assert d["event_id"] == "evt-1"
    assert d["severity"] == "low"


def test_security_manager_denial_counting():
    policy, internet = _make_policy_and_internet()
    manager = SecurityManager(policy, internet)
    manager.record_policy_denial("p1", "r1")
    manager.record_policy_denial("p2", "r2")
    assert manager.metrics._policy_denials_total == 2


def test_security_manager_injection_counting():
    policy, internet = _make_policy_and_internet()
    manager = SecurityManager(policy, internet)
    manager.record_injection_detection("p1", ["flag1", "flag2"])
    assert manager.metrics._injection_detections_total == 1
