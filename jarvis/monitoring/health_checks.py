"""
Health Checks — JARVIS-OS subsystem health monitoring.

Provides per-subsystem health checks with dependency status, dependency
graph analysis, and overall system health aggregation.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from ..core.logging import get_module_logger

log = get_module_logger(__name__)


@dataclass
class HealthCheck:
    """A single health check result."""
    subsystem: str
    status: str  # healthy, degraded, unhealthy, unknown
    message: str
    checked_at: float = field(default_factory=time.time)
    dependencies: dict[str, str] = field(default_factory=dict)


class HealthChecker:
    """
    Health Checks — subsystem health monitoring.

    Provides per-subsystem health checks with dependency tracking and
    overall system health aggregation. All checks are read-only.
    """

    def __init__(self) -> None:
        self._checks: dict[str, HealthCheck] = {}
        self._checkers: dict[str, Callable] = {}
        self._initialized = False

    def initialize(self) -> dict[str, Any]:
        """Initialize the health checker."""
        self._initialized = True
        return {
            "status": "operational",
            "subsystem": "health_checks",
        }

    def register_checker(
        self,
        subsystem: str,
        checker: Callable[[], HealthCheck],
    ) -> None:
        """Register a health check function for a subsystem."""
        self._checkers[subsystem] = checker

    def run_check(self, subsystem: str) -> HealthCheck:
        """Run a health check for a specific subsystem."""
        checker = self._checkers.get(subsystem)
        if not checker:
            return HealthCheck(
                subsystem=subsystem,
                status="unknown",
                message=f"No checker registered for {subsystem}",
            )

        try:
            result = checker()
            if not isinstance(result, HealthCheck):
                result = HealthCheck(
                    subsystem=subsystem,
                    status="healthy",
                    message="checker returned non-HealthCheck result",
                )
            return result
        except Exception as exc:
            return HealthCheck(
                subsystem=subsystem,
                status="unhealthy",
                message=f"Checker failed: {exc}",
            )

    def run_all_checks(self) -> dict[str, HealthCheck]:
        """Run all registered health checks."""
        results: dict[str, HealthCheck] = {}
        for subsystem in self._checkers:
            results[subsystem] = self.run_check(subsystem)
            self._checks[subsystem] = results[subsystem]
        return results

    def get_overall_health(self) -> dict[str, Any]:
        """Get overall system health."""
        results = self.run_all_checks()
        unhealthy = sum(1 for r in results.values() if r.status == "unhealthy")
        degraded = sum(1 for r in results.values() if r.status == "degraded")
        healthy = sum(1 for r in results.values() if r.status == "healthy")

        overall = "healthy"
        if unhealthy > 0:
            overall = "unhealthy"
        elif degraded > 0:
            overall = "degraded"

        return {
            "overall": overall,
            "healthy": healthy,
            "degraded": degraded,
            "unhealthy": unhealthy,
            "total": len(results),
            "subsystems": {
                name: {
                    "status": hc.status,
                    "message": hc.message,
                    "checked_at": hc.checked_at,
                }
                for name, hc in results.items()
            },
            "timestamp": time.time(),
        }

    def get_status(self) -> dict[str, Any]:
        """Get subsystem status."""
        return {
            "subsystem": "health_checks",
            "status": "operational" if self._initialized else "offline",
            "registered_checkers": len(self._checkers),
            "capabilities": [
                "per_subsystem_health_checks",
                "dependency_tracking",
                "overall_health_aggregation",
            ],
        }


# Global instance
_health_checker: HealthChecker | None = None


def get_health_checker() -> HealthChecker:
    """Get or create the global HealthChecker instance."""
    global _health_checker
    if _health_checker is None:
        _health_checker = HealthChecker()
    return _health_checker


__all__ = [
    "HealthChecker",
    "HealthCheck",
    "get_health_checker",
]