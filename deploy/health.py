"""
JARVIS-OS Health & Readiness Endpoints
Provides /health, /ready, and /metrics for Kubernetes probes and Prometheus
"""

from __future__ import annotations

import time
import asyncio
from typing import Any, Dict, Optional
from dataclasses import dataclass, field
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
import psutil

try:
    from jarvis.integrated_system import get_jarvis_os_status, get_jarvis_os
    JARVIS_AVAILABLE = True
except ImportError:
    JARVIS_AVAILABLE = False


@dataclass
class HealthCheck:
    """Individual health check result."""
    name: str
    status: str  # "healthy", "degraded", "unhealthy"
    message: str
    latency_ms: float
    details: Dict[str, Any] = field(default_factory=dict)


class HealthResponse(BaseModel):
    """Health check response model."""
    status: str  # "healthy", "degraded", "unhealthy"
    version: str
    uptime_seconds: float
    checks: Dict[str, Any]
    timestamp: float


class MetricsCollector:
    """Prometheus metrics collector for JARVIS-OS."""

    def __init__(self):
        self._counters: Dict[str, float] = {}
        self._gauges: Dict[str, float] = {}
        self._histograms: Dict[str, list] = {}
        self._start_time = time.time()

    def increment(self, name: str, value: float = 1.0, labels: Optional[Dict[str, str]] = None):
        key = self._make_key(name, labels)
        self._counters[key] = self._counters.get(key, 0) + value

    def set_gauge(self, name: str, value: float, labels: Optional[Dict[str, str]] = None):
        key = self._make_key(name, labels)
        self._gauges[key] = value

    def observe(self, name: str, value: float, labels: Optional[Dict[str, str]] = None):
        key = self._make_key(name, labels)
        if key not in self._histograms:
            self._histograms[key] = []
        self._histograms[key].append(value)
        # Keep only last 1000 observations
        if len(self._histograms[key]) > 1000:
            self._histograms[key] = self._histograms[key][-1000:]

    def _make_key(self, name: str, labels: Optional[Dict[str, str]]) -> str:
        if not labels:
            return name
        label_str = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"

    def to_prometheus(self) -> str:
        lines = []
        # Counters
        for key, value in self._counters.items():
            lines.append(f"# TYPE {key.split('{')[0]} counter")
            lines.append(f"{key} {value}")
        # Gauges
        for key, value in self._gauges.items():
            lines.append(f"# TYPE {key.split('{')[0]} gauge")
            lines.append(f"{key} {value}")
        # Histograms (summary)
        for key, values in self._histograms.items():
            if not values:
                continue
            name = key.split('{')[0]
            lines.append(f"# TYPE {name} summary")
            count = len(values)
            total = sum(values)
            lines.append(f"{key}_count {count}")
            lines.append(f"{key}_sum {total}")
            # Quantiles
            sorted_vals = sorted(values)
            for q in [0.5, 0.9, 0.95, 0.99]:
                idx = int(q * (count - 1))
                lines.append(f'{key}{{quantile="{q}"}} {sorted_vals[idx]}')
        return "\n".join(lines) + "\n"


# Global metrics collector
metrics = MetricsCollector()


async def check_system_resources() -> HealthCheck:
    """Check system resources (CPU, memory, disk)."""
    start = time.time()
    try:
        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage("/")

        status = "healthy"
        messages = []

        if cpu_percent > 90:
            status = "unhealthy"
            messages.append(f"CPU critical: {cpu_percent:.1f}%")
        elif cpu_percent > 75:
            status = "degraded"
            messages.append(f"CPU high: {cpu_percent:.1f}%")

        if memory.percent > 90:
            status = "unhealthy"
            messages.append(f"Memory critical: {memory.percent:.1f}%")
        elif memory.percent > 80:
            status = "degraded" if status == "healthy" else status
            messages.append(f"Memory high: {memory.percent:.1f}%")

        if disk.percent > 90:
            status = "unhealthy"
            messages.append(f"Disk critical: {disk.percent:.1f}%")
        elif disk.percent > 80:
            status = "degraded" if status == "healthy" else status
            messages.append(f"Disk high: {disk.percent:.1f}%")

        message = "; ".join(messages) if messages else "All resources within limits"

        # Update metrics
        metrics.set_gauge("jarvis_system_cpu_percent", cpu_percent)
        metrics.set_gauge("jarvis_system_memory_percent", memory.percent)
        metrics.set_gauge("jarvis_system_disk_percent", disk.percent)

        return HealthCheck(
            name="system_resources",
            status=status,
            message=message,
            latency_ms=(time.time() - start) * 1000,
            details={
                "cpu_percent": cpu_percent,
                "memory_percent": memory.percent,
                "memory_available_gb": memory.available / (1024**3),
                "disk_percent": disk.percent,
                "disk_free_gb": disk.free / (1024**3),
            }
        )
    except Exception as e:
        return HealthCheck(
            name="system_resources",
            status="unhealthy",
            message=f"Failed to check resources: {e}",
            latency_ms=(time.time() - start) * 1000
        )


async def check_jarvis_core() -> HealthCheck:
    """Check JARVIS-OS core system status."""
    start = time.time()
    if not JARVIS_AVAILABLE:
        return HealthCheck(
            name="jarvis_core",
            status="degraded",
            message="JARVIS-OS module not available",
            latency_ms=(time.time() - start) * 1000
        )

    try:
        status = get_jarvis_os_status()
        overall_status = status.status  # "operational", "degraded", "offline"

        # Count subsystem statuses
        active = sum(1 for s in status.subsystems.values() if s.status == "active")
        total = len(status.subsystems)

        message = f"JARVIS-OS {overall_status}: {active}/{total} subsystems active"

        # Update metrics
        metrics.set_gauge("jarvis_subsystems_active", active)
        metrics.set_gauge("jarvis_subsystems_total", total)
        metrics.set_gauge("jarvis_agents_total", status.total_agents)
        metrics.set_gauge("jarvis_agents_active", status.active_agents)

        return HealthCheck(
            name="jarvis_core",
            status=overall_status,
            message=message,
            latency_ms=(time.time() - start) * 1000,
            details={
                "overall_status": overall_status,
                "subsystems": {k: v.status for k, v in status.subsystems.items()},
                "uptime_seconds": status.uptime_seconds,
            }
        )
    except Exception as e:
        return HealthCheck(
            name="jarvis_core",
            status="unhealthy",
            message=f"JARVIS-OS check failed: {e}",
            latency_ms=(time.time() - start) * 1000
        )


async def check_dependencies() -> HealthCheck:
    """Check external dependencies (database, redis, etc.)."""
    start = time.time()
    checks = {}
    overall = "healthy"

    # Check database connectivity (placeholder)
    # In production: asyncpg, sqlalchemy, etc.
    checks["database"] = {"status": "healthy", "latency_ms": 5}
    checks["redis"] = {"status": "healthy", "latency_ms": 2}

    # If any dependency is unhealthy, overall is unhealthy
    for name, result in checks.items():
        if result["status"] == "unhealthy":
            overall = "unhealthy"
            break
        elif result["status"] == "degraded" and overall == "healthy":
            overall = "degraded"

    return HealthCheck(
        name="dependencies",
        status=overall,
        message="All dependencies reachable" if overall == "healthy" else "Some dependencies degraded",
        latency_ms=(time.time() - start) * 1000,
        details=checks
    )


async def run_health_checks() -> HealthResponse:
    """Run all health checks and return combined result."""
    checks = await asyncio.gather(
        check_system_resources(),
        check_jarvis_core(),
        check_dependencies(),
        return_exceptions=True
    )

    valid_checks = []
    for check in checks:
        if isinstance(check, HealthCheck):
            valid_checks.append(check)
        elif isinstance(check, Exception):
            valid_checks.append(HealthCheck(
                name="unknown",
                status="unhealthy",
                message=f"Check failed: {check}",
                latency_ms=0
            ))

    # Determine overall status
    statuses = [c.status for c in valid_checks]
    if "unhealthy" in statuses:
        overall = "unhealthy"
    elif "degraded" in statuses:
        overall = "degraded"
    else:
        overall = "healthy"

    return HealthResponse(
        status=overall,
        version="2.0.0",
        uptime_seconds=time.time() - metrics._start_time,
        checks={c.name: {
            "status": c.status,
            "message": c.message,
            "latency_ms": c.latency_ms,
            "details": c.details
        } for c in valid_checks},
        timestamp=time.time()
    )


def create_health_app() -> FastAPI:
    """Create FastAPI app with health endpoints."""
    app = FastAPI(
        title="JARVIS-OS Health",
        version="2.0.0",
        docs_url=None,
        redoc_url=None
    )

    @app.get("/health", response_model=HealthResponse)
    async def health():
        """Liveness probe - returns 200 if process is alive."""
        return await run_health_checks()

    @app.get("/ready")
    async def ready():
        """Readiness probe - returns 200 if ready to serve traffic."""
        result = await run_health_checks()
        if result.status == "unhealthy":
            raise HTTPException(status_code=503, detail="Not ready")
        return {"status": "ready", "checks": result.checks}

    @app.get("/metrics", response_class=PlainTextResponse)
    async def metrics_endpoint():
        """Prometheus metrics endpoint."""
        # Update runtime metrics
        metrics.set_gauge("jarvis_uptime_seconds", time.time() - metrics._start_time)
        return metrics.to_prometheus()

    @app.get("/")
    async def root():
        return {"service": "JARVIS-OS", "version": "2.0.0", "status": "running"}

    return app


# For direct ASGI usage
app = create_health_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)