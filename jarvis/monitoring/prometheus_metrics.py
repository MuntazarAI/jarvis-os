"""
Prometheus Metrics — JARVIS-OS metrics collection.

Exposes Prometheus-format metrics for:
- Agent execution counts, success/failure rates
- DOT template usage, success/failure rates
- PolicyEngine denials, grants, and audit events
- Subsystem health and uptime
- Resource usage (CPU, memory, disk)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from ..core.logging import get_module_logger

log = get_module_logger(__name__)


@dataclass
class Metric:
    """A single Prometheus metric."""
    name: str
    value: float
    labels: dict[str, str] = field(default_factory=dict)
    metric_type: str = "gauge"  # gauge, counter, histogram
    timestamp: float = field(default_factory=time.time)


class PrometheusMetrics:
    """
    Prometheus Metrics — metrics collection for JARVIS-OS.

    Collects and exposes metrics in Prometheus text format for scraping
    by Prometheus servers. All metrics are read-only gauges and counters.
    """

    def __init__(self) -> None:
        self._metrics: dict[str, Metric] = {}
        self._counters: dict[str, float] = {}
        self._lock = Lock()
        self._initialized = False

    def initialize(self) -> dict[str, Any]:
        """Initialize the metrics collector."""
        self._initialized = True
        return {
            "status": "operational",
            "subsystem": "prometheus_metrics",
            "format": "prometheus_text",
        }

    def increment_counter(self, name: str, labels: dict[str, str] | None = None) -> None:
        """Increment a counter metric."""
        with self._lock:
            key = self._make_key(name, labels or {})
            self._counters[key] = self._counters.get(key, 0) + 1

    def set_gauge(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        """Set a gauge metric."""
        with self._lock:
            key = self._make_key(name, labels or {})
            self._metrics[key] = Metric(
                name=name,
                value=value,
                labels=labels or {},
                metric_type="gauge",
            )

    def observe_histogram(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        """Observe a histogram value."""
        with self._lock:
            key = self._make_key(name, labels or {})
            self._metrics[key] = Metric(
                name=name,
                value=value,
                labels=labels or {},
                metric_type="histogram",
            )

    def _make_key(self, name: str, labels: dict[str, str]) -> str:
        """Create a unique key for a metric."""
        label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}" if labels else name

    def generate_prometheus_text(self) -> str:
        """Generate Prometheus text format output."""
        lines: list[str] = []
        with self._lock:
            # Output counters
            for key, value in sorted(self._counters.items()):
                name, labels = self._parse_key(key)
                label_str = ""
                if labels:
                    label_str = "{" + ",".join(f'{k}="{v}"' for k, v in sorted(labels.items())) + "}"
                lines.append(f"{name}{label_str} {value}")

            # Output gauges and histograms
            for key, metric in sorted(self._metrics.items()):
                name, labels = self._parse_key(key)
                label_str = ""
                if labels:
                    label_str = "{" + ",".join(f'{k}="{v}"' for k, v in sorted(labels.items())) + "}"
                lines.append(f"# HELP {name} {metric.metric_type} metric")
                lines.append(f"# TYPE {name} {metric.metric_type}")
                lines.append(f"{name}{label_str} {metric.value}")

        return "\n".join(lines) + "\n"

    @staticmethod
    def _parse_key(key: str) -> tuple[str, dict[str, str]]:
        """Parse a metric key back into name and labels."""
        if "{" in key:
            name, label_part = key.split("{", 1)
            label_part = label_part.rstrip("}")
            labels: dict[str, str] = {}
            for item in label_part.split(","):
                if "=" in item:
                    k, v = item.split("=", 1)
                    labels[k] = v
            return name, labels
        return key, {}

    def get_status(self) -> dict[str, Any]:
        """Get subsystem status."""
        with self._lock:
            return {
                "subsystem": "prometheus_metrics",
                "status": "operational" if self._initialized else "offline",
                "metrics_count": len(self._metrics),
                "counters_count": len(self._counters),
                "format": "prometheus_text",
            }


# Global instance
_prometheus: PrometheusMetrics | None = None


def get_prometheus_metrics() -> PrometheusMetrics:
    """Get or create the global PrometheusMetrics instance."""
    global _prometheus
    if _prometheus is None:
        _prometheus = PrometheusMetrics()
    return _prometheus


__all__ = [
    "PrometheusMetrics",
    "Metric",
    "get_prometheus_metrics",
]