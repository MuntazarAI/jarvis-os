"""
JARVIS-OS Prometheus Metrics Module
Provides application-level metrics for monitoring
"""

from __future__ import annotations

import time
import functools
from typing import Callable, Any, Optional, Dict
from contextlib import contextmanager
from dataclasses import dataclass, field
from collections import defaultdict
import threading

try:
    from prometheus_client import Counter, Gauge, Histogram, Summary, CollectorRegistry, generate_latest
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False


@dataclass
class MetricsRegistry:
    """Thread-safe metrics registry."""
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _counters: Dict[str, Any] = field(default_factory=dict)
    _gauges: Dict[str, Any] = field(default_factory=dict)
    _histograms: Dict[str, Any] = field(default_factory=dict)
    _summaries: Dict[str, Any] = field(default_factory=dict)
    _registry: Optional[Any] = None

    def __post_init__(self):
        if PROMETHEUS_AVAILABLE:
            self._registry = CollectorRegistry()

    def _get_or_create(self, dict_: Dict, key: str, factory: Callable) -> Any:
        with self._lock:
            if key not in dict_:
                dict_[key] = factory()
            return dict_[key]

    def counter(self, name: str, description: str, labels: Optional[Dict[str, str]] = None) -> Any:
        """Get or create a counter."""
        if not PROMETHEUS_AVAILABLE:
            return _NoOpMetric()

        label_keys = tuple(sorted(labels.keys())) if labels else ()
        key = (name, label_keys)

        def factory():
            return Counter(name, description, label_keys, registry=self._registry)

        counter = self._get_or_create(self._counters, key, factory)
        if labels:
            return counter.labels(**labels)
        return counter

    def gauge(self, name: str, description: str, labels: Optional[Dict[str, str]] = None) -> Any:
        """Get or create a gauge."""
        if not PROMETHEUS_AVAILABLE:
            return _NoOpMetric()

        label_keys = tuple(sorted(labels.keys())) if labels else ()
        key = (name, label_keys)

        def factory():
            return Gauge(name, description, label_keys, registry=self._registry)

        gauge = self._get_or_create(self._gauges, key, factory)
        if labels:
            return gauge.labels(**labels)
        return gauge

    def histogram(self, name: str, description: str, buckets: Optional[tuple] = None,
                  labels: Optional[Dict[str, str]] = None) -> Any:
        """Get or create a histogram."""
        if not PROMETHEUS_AVAILABLE:
            return _NoOpMetric()

        label_keys = tuple(sorted(labels.keys())) if labels else ()
        key = (name, label_keys)

        def factory():
            return Histogram(name, description, label_keys, buckets=buckets, registry=self._registry)

        hist = self._get_or_create(self._histograms, key, factory)
        if labels:
            return hist.labels(**labels)
        return hist

    def summary(self, name: str, description: str, labels: Optional[Dict[str, str]] = None) -> Any:
        """Get or create a summary."""
        if not PROMETHEUS_AVAILABLE:
            return _NoOpMetric()

        label_keys = tuple(sorted(labels.keys())) if labels else ()
        key = (name, label_keys)

        def factory():
            return Summary(name, description, label_keys, registry=self._registry)

        summ = self._get_or_create(self._summaries, key, factory)
        if labels:
            return summ.labels(**labels)
        return summ

    def generate_latest(self) -> bytes:
        """Generate Prometheus exposition format."""
        if not PROMETHEUS_AVAILABLE or not self._registry:
            return b"# Prometheus client not available\n"
        return generate_latest(self._registry)


class _NoOpMetric:
    """No-op metric for when prometheus_client is not available."""
    def inc(self, *args, **kwargs): pass
    def dec(self, *args, **kwargs): pass
    def set(self, *args, **kwargs): pass
    def observe(self, *args, **kwargs): pass
    def labels(self, *args, **kwargs): return self
    def time(self): return _NoOpTimer()


class _NoOpTimer:
    def __enter__(self): return self
    def __exit__(self, *args): pass


# Global metrics registry
registry = MetricsRegistry()


# =============================================================================
# Pre-defined JARVIS-OS Metrics
# =============================================================================

# System metrics
system_cpu = registry.gauge("jarvis_system_cpu_percent", "System CPU usage percent")
system_memory = registry.gauge("jarvis_system_memory_percent", "System memory usage percent")
system_disk = registry.gauge("jarvis_system_disk_percent", "System disk usage percent")

# JARVIS-OS core metrics
jarvis_status = registry.gauge("jarvis_status", "JARVIS-OS overall status (1=healthy, 0.5=degraded, 0=unhealthy)")
jarvis_uptime = registry.gauge("jarvis_uptime_seconds", "JARVIS-OS uptime in seconds")
jarvis_subsystems_active = registry.gauge("jarvis_subsystems_active", "Number of active subsystems")
jarvis_subsystems_total = registry.gauge("jarvis_subsystems_total", "Total number of subsystems")

# Agent metrics
jarvis_agents_total = registry.gauge("jarvis_agents_total", "Total number of agents")
jarvis_agents_active = registry.gauge("jarvis_agents_active", "Number of active agents")
jarvis_agent_tasks = registry.counter("jarvis_agent_tasks_total", "Total agent tasks executed",
                                       labels={"agent": "", "status": ""})
jarvis_agent_failures = registry.counter("jarvis_agent_failures_total", "Total agent failures",
                                          labels={"agent": "", "error_type": ""})
jarvis_agent_duration = registry.histogram("jarvis_agent_task_duration_seconds",
                                            "Agent task execution duration",
                                            buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60))

# Task queue metrics
jarvis_task_queue_depth = registry.gauge("jarvis_task_queue_depth", "Number of pending tasks in queue")
jarvis_task_queue_enqueued = registry.counter("jarvis_task_queue_enqueued_total", "Tasks enqueued")
jarvis_task_queue_dequeued = registry.counter("jarvis_task_queue_dequeued_total", "Tasks dequeued")
jarvis_task_queue_failed = registry.counter("jarvis_task_queue_failed_total", "Tasks failed")

# Tool metrics
jarvis_tool_calls = registry.counter("jarvis_tool_calls_total", "Total tool calls",
                                      labels={"tool": "", "status": ""})
jarvis_tool_duration = registry.histogram("jarvis_tool_duration_seconds", "Tool execution duration",
                                           buckets=(0.01, 0.05, 0.1, 0.5, 1, 2, 5, 10))

# Model inference metrics
jarvis_inference_requests = registry.counter("jarvis_inference_requests_total", "Inference requests",
                                              labels={"model": "", "status": ""})
jarvis_inference_duration = registry.histogram("jarvis_inference_duration_seconds",
                                                "Inference duration",
                                                buckets=(0.01, 0.05, 0.1, 0.5, 1, 2, 5, 10, 30))
jarvis_inference_tokens = registry.histogram("jarvis_inference_tokens", "Tokens generated",
                                              buckets=(10, 50, 100, 250, 500, 1000, 2000, 4000))

# HTTP metrics
jarvis_http_requests = registry.counter("jarvis_http_requests_total", "HTTP requests",
                                         labels={"method": "", "path": "", "status": ""})
jarvis_http_duration = registry.histogram("jarvis_http_request_duration_seconds",
                                           "HTTP request duration",
                                           buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5))

# Database metrics
jarvis_db_connections = registry.gauge("jarvis_db_connections_active", "Active database connections")
jarvis_db_query_duration = registry.histogram("jarvis_db_query_duration_seconds",
                                               "Database query duration",
                                               buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1))

# Cache metrics
jarvis_cache_hits = registry.counter("jarvis_cache_hits_total", "Cache hits", labels={"cache": ""})
jarvis_cache_misses = registry.counter("jarvis_cache_misses_total", "Cache misses", labels={"cache": ""})


# =============================================================================
# Convenience Functions
# =============================================================================

def record_agent_task(agent: str, status: str, duration: float):
    """Record agent task execution."""
    jarvis_agent_tasks.labels(agent=agent, status=status).inc()
    jarvis_agent_duration.observe(duration)
    if status == "failed":
        jarvis_agent_failures.labels(agent=agent, error_type="unknown").inc()


def record_tool_call(tool: str, status: str, duration: float):
    """Record tool call."""
    jarvis_tool_calls.labels(tool=tool, status=status).inc()
    jarvis_tool_duration.observe(duration)


def record_inference(model: str, status: str, duration: float, tokens: int):
    """Record model inference."""
    jarvis_inference_requests.labels(model=model, status=status).inc()
    jarvis_inference_duration.observe(duration)
    jarvis_inference_tokens.observe(tokens)


def record_http_request(method: str, path: str, status: int, duration: float):
    """Record HTTP request."""
    jarvis_http_requests.labels(method=method, path=path, status=str(status)).inc()
    jarvis_http_duration.observe(duration)


@contextmanager
def measure_time(histogram):
    """Context manager to measure and record execution time."""
    start = time.perf_counter()
    try:
        yield
    finally:
        histogram.observe(time.perf_counter() - start)


def timed(histogram):
    """Decorator to time function execution."""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with measure_time(histogram):
                return func(*args, **kwargs)
        return wrapper
    return decorator


# For ASGI middleware
def get_metrics() -> bytes:
    """Get metrics in Prometheus format."""
    return registry.generate_latest()


# For direct usage
if __name__ == "__main__":
    print(get_metrics().decode())