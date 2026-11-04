"""OMNINET M12 — Global Intelligence Dashboard tests.

Tests unified status dashboard, diagnostic reports, and completion
verification for all OMNINET modules (M1-M11).
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from jarvis.core.config import JarvisConfig
from jarvis.core.internet import InternetAccess
from jarvis.core.types import ActionPlan, RiskLevel
from jarvis.omninet import (
    ComponentStatus,
    DashboardReport,
    GlobalIntelligenceDashboard,
    SecurityManager,
    SecurityMetrics,
)
from jarvis.policy.policy import PolicyEngine


# -- fixtures -----------------------------------------------------------


def _make_security_manager(home: str | None = None):
    cfg = JarvisConfig()
    if home:
        cfg.paths.home = Path(home)
    policy = PolicyEngine(cfg)
    internet = InternetAccess(policy)
    policy.grant("jarvis", "net.fetch")
    metrics = SecurityMetrics()
    return SecurityManager(policy, internet, metrics=metrics)


def _make_jarvis_mock():
    """Create a mock Jarvis with a status() method."""
    mock = MagicMock()
    mock.status.return_value = {
        "available": True,
        "cycle": 5,
        "memory": {"entries": 100},
        "graph": {"nodes": 50},
        "events": 200,
        "agents": {"count": 10},
        "tasks": {"pending": 3},
        "tools": {"registered": 25},
        "models": {"available": 3},
        "policy_conflicts": [],
        "audit_entries": 50,
    }
    return mock


# -- ComponentStatus tests ----------------------------------------------


def test_component_status_creation():
    comp = ComponentStatus(
        name="Test Component",
        module="jarvis.test",
        healthy=True,
        details={"key": "value"},
    )
    assert comp.name == "Test Component"
    assert comp.module == "jarvis.test"
    assert comp.healthy is True
    assert comp.details == {"key": "value"}


def test_component_status_defaults():
    comp = ComponentStatus(name="X", module="Y", healthy=False)
    assert comp.healthy is False
    assert comp.details == {}


# -- GlobalIntelligenceDashboard tests ---------------------------------


def test_dashboard_init():
    dashboard = GlobalIntelligenceDashboard()
    assert dashboard is not None
    assert dashboard._report_counter == 0
    assert dashboard._last_report is None


def test_dashboard_with_jarvis_and_security():
    jarvis = _make_jarvis_mock()
    sm = _make_security_manager()
    dashboard = GlobalIntelligenceDashboard(jarvis=jarvis, security_manager=sm)
    assert dashboard.jarvis is jarvis
    assert dashboard.security_manager is sm


def test_dashboard_register_component():
    dashboard = GlobalIntelligenceDashboard()
    dashboard.register_component(
        name="test_comp",
        module="jarvis.test",
        healthy=True,
        details={"status": "ok"},
    )
    assert "test_comp" in dashboard._components
    assert dashboard._components["test_comp"].healthy is True


def test_dashboard_unregister_component():
    dashboard = GlobalIntelligenceDashboard()
    dashboard.register_component("tc", "jarvis.test", True)
    assert dashboard.unregister_component("tc") is True
    assert "tc" not in dashboard._components
    assert dashboard.unregister_component("nonexistent") is False


def test_dashboard_set_component_healthy():
    dashboard = GlobalIntelligenceDashboard()
    dashboard.register_component("tc", "jarvis.test", True)
    dashboard.set_component_healthy("tc", False)
    assert dashboard._components["tc"].healthy is False


def test_dashboard_collect_all_jarvis_only():
    jarvis = _make_jarvis_mock()
    dashboard = GlobalIntelligenceDashboard(jarvis=jarvis)
    status = dashboard.collect_all()
    assert "jarvis_core" in status
    assert status["jarvis_core"]["cycle"] == 5


def test_dashboard_collect_all_security_only():
    sm = _make_security_manager()
    dashboard = GlobalIntelligenceDashboard(security_manager=sm)
    status = dashboard.collect_all()
    assert "security" in status


def test_dashboard_generate_report_no_components():
    dashboard = GlobalIntelligenceDashboard()
    report = dashboard.generate_report()
    assert isinstance(report, DashboardReport)
    assert report.report_id.startswith("dashboard-")
    assert report.overall_healthy is True  # no degraded components
    assert report.component_count == 0


def test_dashboard_generate_report_with_components():
    dashboard = GlobalIntelligenceDashboard()
    dashboard.register_component("comp_a", "jarvis.mod_a", True, {"detail": "ok"})
    dashboard.register_component("comp_b", "jarvis.mod_b", False, {"error": "down"})
    report = dashboard.generate_report()
    assert report.component_count == 2
    assert report.healthy_count == 1
    assert report.degraded_count == 1
    assert report.overall_healthy is False


def test_dashboard_generate_report_with_jarvis_and_security():
    jarvis = _make_jarvis_mock()
    sm = _make_security_manager()
    dashboard = GlobalIntelligenceDashboard(jarvis=jarvis, security_manager=sm)
    report = dashboard.generate_report()
    assert report.component_count >= 2
    assert "jarvis_core" in report.components
    assert "security" in report.components
    assert report.components["jarvis_core"].healthy is True


def test_dashboard_report_summary():
    dashboard = GlobalIntelligenceDashboard()
    dashboard.register_component("good", "jarvis.mod", True)
    dashboard.register_component("bad", "jarvis.mod", False)
    report = dashboard.generate_report()
    assert "degraded" in report.summary.lower() or "healthy" in report.summary.lower()


def test_dashboard_milestones():
    dashboard = GlobalIntelligenceDashboard()
    report = dashboard.generate_report()
    assert "M1" in report.milestones
    assert "M12" in report.milestones
    assert "complete" in report.milestones["M12"]


def test_dashboard_recommendations():
    dashboard = GlobalIntelligenceDashboard()
    report = dashboard.generate_report()
    assert isinstance(report.recommendations, list)


def test_dashboard_get_last_report():
    dashboard = GlobalIntelligenceDashboard()
    assert dashboard.get_last_report() is None
    report = dashboard.generate_report()
    assert dashboard.get_last_report() is report


def test_dashboard_component_health():
    dashboard = GlobalIntelligenceDashboard()
    dashboard.register_component("a", "m.a", True)
    dashboard.register_component("b", "m.b", False)
    health = dashboard.component_health()
    assert health["a"] is True
    assert health["b"] is False


def test_dashboard_unhealthy_components():
    dashboard = GlobalIntelligenceDashboard()
    dashboard.register_component("a", "m.a", True)
    dashboard.register_component("b", "m.b", False)
    unhealthy = dashboard.unhealthy_components()
    assert "b" in unhealthy
    assert "a" not in unhealthy


def test_dashboard_diagnostic_report():
    jarvis = _make_jarvis_mock()
    sm = _make_security_manager()
    dashboard = GlobalIntelligenceDashboard(jarvis=jarvis, security_manager=sm)
    diag = dashboard.diagnostic_report()
    assert "report_id" in diag
    assert "component_summary" in diag
    assert "components" in diag
    assert "raw_status" in diag
    assert "milestones" in diag
    assert "recommendations" in diag


def test_dashboard_diagnostic_with_jarvis():
    jarvis = _make_jarvis_mock()
    dashboard = GlobalIntelligenceDashboard(jarvis=jarvis)
    diag = dashboard.diagnostic_report()
    assert diag["component_summary"]["total"] >= 1


def test_dashboard_report_all_milestones():
    dashboard = GlobalIntelligenceDashboard()
    report = dashboard.generate_report()
    expected = ["M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9", "M10", "M11", "M12"]
    for m in expected:
        assert m in report.milestones


def test_dashboard_register_extra_component():
    """Test registering an OMNINET component via extra_components kwarg."""
    mock_comp = MagicMock()
    mock_comp.status.return_value = {"available": True, "requests": 5}
    dashboard = GlobalIntelligenceDashboard(omninet_http=mock_comp)
    report = dashboard.generate_report()
    assert "omninet_http" in report.components
    assert report.components["omninet_http"].healthy is True


def test_dashboard_report_healthy_when_all_healthy():
    dashboard = GlobalIntelligenceDashboard()
    dashboard.register_component("a", "m.a", True)
    dashboard.register_component("b", "m.b", True)
    report = dashboard.generate_report()
    assert report.overall_healthy is True
    assert report.degraded_count == 0


def test_dashboard_report_degraded_when_some_unhealthy():
    dashboard = GlobalIntelligenceDashboard()
    dashboard.register_component("a", "m.a", True)
    dashboard.register_component("b", "m.b", False)
    dashboard.register_component("c", "m.c", False)
    report = dashboard.generate_report()
    assert report.overall_healthy is False
    assert report.degraded_count == 2


# -- integration tests -----------------------------------------------


def test_dashboard_with_real_jarvis():
    """Test with actual Jarvis instance (no mock)."""
    cfg = JarvisConfig()
    cfg.paths.home = Path(tempfile.mkdtemp(prefix="jarvis-dashboard-"))
    from jarvis.core.loop import Jarvis
    jarvis = Jarvis(cfg)
    sm = _make_security_manager()
    dashboard = GlobalIntelligenceDashboard(jarvis=jarvis, security_manager=sm)
    report = dashboard.generate_report()
    assert report.component_count >= 2
    assert "jarvis_core" in report.components


def test_dashboard_full_integration():
    """Full integration: Jarvis + Security + OMNINET components."""
    cfg = JarvisConfig()
    cfg.paths.home = Path(tempfile.mkdtemp(prefix="jarvis-full-"))
    from jarvis.core.loop import Jarvis
    jarvis = Jarvis(cfg)
    sm = _make_security_manager()
    dashboard = GlobalIntelligenceDashboard(jarvis=jarvis, security_manager=sm)
    # Register some OMNINET components
    dashboard.register_component("http_connector", "jarvis.omninet.http_connector", True)
    dashboard.register_component("search_engine", "jarvis.omninet.discovery", True)
    dashboard.register_component("crawler", "jarvis.omninet.crawler", False)
    report = dashboard.generate_report()
    assert report.component_count >= 5
    assert report.degraded_count >= 1
    assert report.overall_healthy is False
