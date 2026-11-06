"""
Distributed Tracing — JARVIS-OS trace correlation.

Provides OpenTelemetry-compatible distributed tracing for agent→DOT→OMNINET→
neural call chains. All traces are stored locally and can be exported to
Jaeger or Zipkin-compatible backends.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from ..core.logging import get_module_logger

log = get_module_logger(__name__)


@dataclass
class Span:
    """A distributed trace span."""
    trace_id: str
    span_id: str
    parent_span_id: str | None
    operation_name: str
    start_time: float
    end_time: float | None = None
    status: str = "in_progress"  # in_progress, ok, error
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Trace:
    """A distributed trace containing multiple spans."""
    trace_id: str
    root_span_id: str
    spans: dict[str, Span] = field(default_factory=dict)
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None


class DistributedTracing:
    """
    Distributed Tracing — trace correlation across JARVIS-OS subsystems.

    Provides OpenTelemetry-compatible trace IDs, span creation, and
    trace export. All traces are stored locally. No external tracing
    backend is required; traces can be exported to Jaeger/Zipkin.
    """

    def __init__(self) -> None:
        self.traces: dict[str, Trace] = {}
        self.active_spans: dict[str, Span] = {}  # span_id -> span
        self._initialized = False

    def initialize(self) -> dict[str, Any]:
        """Initialize the distributed tracing subsystem."""
        self._initialized = True
        return {
            "status": "operational",
            "subsystem": "distributed_tracing",
            "format": "opentelemetry_compatible",
        }

    def start_trace(self, operation_name: str) -> str:
        """Start a new distributed trace."""
        trace_id = f"trace-{uuid.uuid4().hex[:16]}"
        span_id = f"span-{uuid.uuid4().hex[:16]}"

        trace = Trace(
            trace_id=trace_id,
            root_span_id=span_id,
        )
        span = Span(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=None,
            operation_name=operation_name,
            start_time=time.time(),
        )

        self.traces[trace_id] = trace
        self.active_spans[span_id] = span

        return trace_id

    def start_span(
        self,
        trace_id: str,
        operation_name: str,
        parent_span_id: str | None = None,
    ) -> str:
        """Start a new span within a trace."""
        span_id = f"span-{uuid.uuid4().hex[:16]}"

        span = Span(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            operation_name=operation_name,
            start_time=time.time(),
        )

        trace = self.traces.get(trace_id)
        if trace:
            trace.spans[span_id] = span

        self.active_spans[span_id] = span
        return span_id

    def end_span(
        self,
        span_id: str,
        status: str = "ok",
        attributes: dict[str, Any] | None = None,
    ) -> None:
        """End a span."""
        span = self.active_spans.get(span_id)
        if not span:
            return

        span.end_time = time.time()
        span.status = status
        if attributes:
            span.attributes.update(attributes)

        if span_id in self.active_spans:
            del self.active_spans[span_id]

    def add_span_event(
        self,
        span_id: str,
        event_name: str,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        """Add an event to a span."""
        span = self.active_spans.get(span_id)
        if not span:
            # Check completed spans in traces
            for trace in self.traces.values():
                if span_id in trace.spans:
                    span = trace.spans[span_id]
                    break

        if span:
            span.events.append({
                "name": event_name,
                "timestamp": time.time(),
                "attributes": attributes or {},
            })

    def get_trace(self, trace_id: str) -> Trace | None:
        """Get a trace by ID."""
        return self.traces.get(trace_id)

    def list_traces(self) -> list[Trace]:
        """List all traces."""
        return list(self.traces.values())

    def export_jaeger(self) -> dict[str, Any]:
        """Export traces in Jaeger-compatible format."""
        jaeger_traces = []
        for trace in self.traces.values():
            spans = []
            for span in trace.spans.values():
                spans.append({
                    "traceID": span.trace_id,
                    "spanID": span.span_id,
                    "parentSpanID": span.parent_span_id or "",
                    "operationName": span.operation_name,
                    "startTime": int(span.start_time * 1_000_000),  # microseconds
                    "duration": int((span.end_time or time.time() - span.start_time) * 1_000_000),
                    "tags": [
                        {"key": k, "value": v}
                        for k, v in span.attributes.items()
                    ],
                    "logs": [
                        {
                            "timestamp": int(e["timestamp"] * 1_000_000),
                            "fields": [
                                {"key": k, "value": v}
                                for k, v in (e.get("attributes") or {}).items()
                            ],
                        }
                        for e in span.events
                    ],
                })
            jaeger_traces.append({
                "traceID": trace.trace_id,
                "spans": spans,
            })
        return {"data": jaeger_traces}

    def get_status(self) -> dict[str, Any]:
        """Get subsystem status."""
        return {
            "subsystem": "distributed_tracing",
            "status": "operational" if self._initialized else "offline",
            "traces": len(self.traces),
            "active_spans": len(self.active_spans),
            "format": "opentelemetry_compatible",
            "capabilities": [
                "trace_creation",
                "span_management",
                "event_recording",
                "jaeger_export",
            ],
        }


# Global instance
_tracing: DistributedTracing | None = None


def get_distributed_tracing() -> DistributedTracing:
    """Get or create the global DistributedTracing instance."""
    global _tracing
    if _tracing is None:
        _tracing = DistributedTracing()
    return _tracing


__all__ = [
    "DistributedTracing",
    "Span",
    "Trace",
    "get_distributed_tracing",
]