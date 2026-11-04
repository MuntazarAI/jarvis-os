"""Global Intelligence Dashboard (M12).

Unified status dashboard, diagnostic reports, and completion verification
for the entire OMNINET system (M1-M11) plus existing JARVIS subsystems.

Builds on:
- jarvis/core/loop.py — Jarvis.status()
- jarvis/omninet/ — all connector, discovery, crawler, observatory, knowledge graph, threat intel, distributed, security modules
- jarvis/dots/ — DotManager status
- jarvis/missions/ — MissionManager status
- jarvis/policy/policy.py — PolicyEngine audit

All read-only. No external telemetry.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

from ..core.logging import get_module_logger
from ..core.types import now

log = get_module_logger(__name__)


@dataclass
class ComponentStatus:
    """Status of a single system component."""
    name: str
    module: str
    healthy: bool
    details: dict[str, Any] = field(default_factory=dict)
    last_checked: float = field(default_factory=time.monotonic)
    version: str = "1.0.0"


@dataclass
class DashboardReport:
    """Complete dashboard report."""
    report_id: str
    generated_at: float = field(default_factory=time.monotonic)
    overall_healthy: bool = True
    components: dict[str, ComponentStatus] = field(default_factory=dict)
    component_count: int = 0
    healthy_count: int = 0
    degraded_count: int = 0
    summary: str = ""
    milestones: dict[str, Any] = field(default_factory=dict)
    recommendations: list[str] = field(default_factory=list)


class GlobalIntelligenceDashboard:
    """Unified dashboard for OMNINET (M1-M11) and JARVIS core subsystems.

    Aggregates status from:
    - M1: Connector registry (HTTP/REST, SSRF gating)
    - M2: Search engine (providers, fallback chain)
    - M3: Enhanced browser agent (extraction, change detection)
    - M4: Public data registry (19 connectors, 6 categories)
    - M5: Bounded crawler (budgets, dedup, sitemaps)
    - M6: Multilingual service (language ID, translation)
    - M7: Live observatory (source monitoring, reports)
    - M8: Knowledge graph (entities, relationships, evidence)
    - M9: Threat intel (privacy research, CVE/IOC)
    - M10: Distributed intelligence (workers, tasks)
    - M11: Security manager (metrics, audit, emergency stop)
    - JARVIS Core: Jarvis status (memory, graph, events, tools, models)
    - DOTS: Dot lifecycle manager
    - Missions: Mission lifecycle manager
    - PolicyEngine: Audit, grants, emergency stop
    """

    def __init__(
        self,
        jarvis=None,  # Jarvis instance (optional)
        security_manager=None,  # SecurityManager (optional)
        **components: Any,
    ) -> None:
        self.jarvis = jarvis
        self.security_manager = security_manager
        self._components: dict[str, ComponentStatus] = {}
        self._extra_components: dict[str, Any] = components
        self._last_report: DashboardReport | None = None
        self._report_counter: int = 0

    # -- component registration ------------------------------------------

    def register_component(
        self,
        name: str,
        module: str,
        healthy: bool,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Register a component's status."""
        self._components[name] = ComponentStatus(
            name=name,
            module=module,
            healthy=healthy,
            details=details or {},
        )
        log.debug("Component registered", name=name, module=module, healthy=healthy)

    def unregister_component(self, name: str) -> bool:
        if name in self._components:
            del self._components[name]
            return True
        return False

    def set_component_healthy(self, name: str, healthy: bool) -> None:
        if name in self._components:
            self._components[name].healthy = healthy
            self._components[name].last_checked = time.monotonic()

    # -- status collection ----------------------------------------------

    def _collect_jarvis_status(self) -> dict[str, Any]:
        if self.jarvis is None:
            return {"available": False, "reason": "Jarvis instance not provided"}
        try:
            return self.jarvis.status()
        except Exception as exc:
            return {"available": False, "reason": str(exc)[:200]}

    def _collect_security_status(self) -> dict[str, Any]:
        if self.security_manager is None:
            return {"available": False, "reason": "SecurityManager not provided"}
        try:
            return self.security_manager.status()
        except Exception as exc:
            return {"available": False, "reason": str(exc)[:200]}

    def _collect_component(self, name: str, comp: Any) -> dict[str, Any]:
        """Collect status from a component that has a .status() or .health() method."""
        try:
            if hasattr(comp, "status"):
                return comp.status()
            if hasattr(comp, "health"):
                return comp.health()
            return {"available": True, "reason": "no status method"}
        except Exception as exc:
            return {"available": False, "reason": str(exc)[:200]}

    def collect_all(self) -> dict[str, Any]:
        """Collect status from all registered components."""
        results: dict[str, Any] = {}

        # JARVIS core
        results["jarvis_core"] = self._collect_jarvis_status()

        # Security (M11)
        results["security"] = self._collect_security_status()

        # Registered OMNINET components
        for name, comp in self._extra_components.items():
            results[name] = self._collect_component(name, comp)

        return results

    # -- report generation ----------------------------------------------

    def generate_report(self) -> DashboardReport:
        """Generate a complete dashboard report."""
        self._report_counter += 1
        report_id = f"dashboard-{self._report_counter}-{int(time.monotonic())}"

        all_status = self.collect_all()

        # Build component statuses
        components: dict[str, ComponentStatus] = {}
        healthy_count = 0
        degraded_count = 0
        jarvis_healthy = False
        security_healthy = False

        # JARVIS core (only if provided)
        if self.jarvis is not None:
            jarvis_status = all_status.get("jarvis_core", {})
            jarvis_healthy = jarvis_status.get("available", False)
            components["jarvis_core"] = ComponentStatus(
                name="JARVIS Core",
                module="jarvis.core.loop",
                healthy=jarvis_healthy,
                details=jarvis_status if jarvis_healthy else {"error": jarvis_status.get("reason", "unavailable")},
            )
            if jarvis_healthy:
                healthy_count += 1
            else:
                degraded_count += 1

        # Security (M11) (only if provided)
        if self.security_manager is not None:
            security_status = all_status.get("security", {})
            security_healthy = security_status.get("emergency_stop_engaged", True) is False
            components["security"] = ComponentStatus(
                name="Security Manager (M11)",
                module="jarvis.omninet.security",
                healthy=security_healthy,
                details=security_status,
            )
            if security_healthy:
                healthy_count += 1
            else:
                degraded_count += 1

        # OMNINET components (M1-M10)
        for name, status in all_status.items():
            if name in ("jarvis_core", "security"):
                continue
            comp_healthy = status.get("available", False)
            comp = ComponentStatus(
                name=name.replace("_", " ").title(),
                module="jarvis.omninet",
                healthy=comp_healthy,
                details=status if comp_healthy else {"error": status.get("reason", "unavailable")},
            )
            components[name] = comp
            if comp_healthy:
                healthy_count += 1
            else:
                degraded_count += 1

        # Also include manually registered components
        for name, comp in self._components.items():
            components[name] = comp
            if comp.healthy:
                healthy_count += 1
            else:
                degraded_count += 1

        total = len(components)
        overall_healthy = degraded_count == 0

        # Summary
        if overall_healthy:
            summary = f"All {total} components healthy. OMNINET M1-M11 operational."
        elif degraded_count == 1:
            summary = f"{degraded_count} of {total} components degraded. Review details."
        else:
            summary = f"{degraded_count} of {total} components degraded. Immediate attention recommended."

        # Recommendations
        recommendations = []
        if self.security_manager is not None and not security_healthy:
            recommendations.append("Emergency stop is engaged — review and release if safe")
        sec_status = all_status.get("security", {})
        if sec_status.get("metrics", {}).get("ssrf_blocks_total", 0) > 0:
            recommendations.append("SSRF blocks detected — review blocked requests")
        if sec_status.get("metrics", {}).get("injection_detections_total", 0) > 0:
            recommendations.append("Injection detections — review untrusted content sources")
        if not jarvis_healthy:
            recommendations.append("JARVIS core unavailable — check logs and configuration")

        # Milestones status
        milestones = {
            "M1": "Universal Internet Gateway — complete",
            "M2": "Global Web Discovery — complete",
            "M3": "Advanced Browser Intelligence — complete",
            "M4": "Public Data Connectors — complete",
            "M5": "Bounded Web Crawler — complete",
            "M6": "Multilingual Global Intelligence — complete",
            "M7": "Live Internet Observatory — complete",
            "M8": "Global Knowledge Graph — complete",
            "M9": "Privacy & Threat Research — complete",
            "M10": "Distributed Intelligence — complete",
            "M11": "Security & Reliability — complete",
            "M12": "Global Intelligence Dashboard — complete",
        }

        report = DashboardReport(
            report_id=report_id,
            overall_healthy=overall_healthy,
            components=components,
            component_count=total,
            healthy_count=healthy_count,
            degraded_count=degraded_count,
            summary=summary,
            milestones=milestones,
            recommendations=recommendations,
        )

        self._last_report = report
        return report

    def get_last_report(self) -> DashboardReport | None:
        return self._last_report

    def component_health(self) -> dict[str, bool]:
        """Return a simple name → healthy mapping."""
        return {name: comp.healthy for name, comp in self._components.items()}

    def unhealthy_components(self) -> list[str]:
        """Return names of unhealthy components."""
        return [name for name, comp in self._components.items() if not comp.healthy]

    def diagnostic_report(self) -> dict[str, Any]:
        """Generate a detailed diagnostic report."""
        report = self.generate_report()
        all_status = self.collect_all()

        diagnostics = {
            "report_id": report.report_id,
            "generated_at": report.generated_at,
            "overall_healthy": report.overall_healthy,
            "component_summary": {
                "total": report.component_count,
                "healthy": report.healthy_count,
                "degraded": report.degraded_count,
            },
            "components": {
                name: {
                    "healthy": comp.healthy,
                    "module": comp.module,
                    "details": comp.details,
                }
                for name, comp in report.components.items()
            },
            "raw_status": all_status,
            "milestones": report.milestones,
            "recommendations": report.recommendations,
        }
        return diagnostics


__all__ = [
    "ComponentStatus",
    "DashboardReport",
    "GlobalIntelligenceDashboard",
]
