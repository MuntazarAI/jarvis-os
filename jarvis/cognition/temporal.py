"""Temporal, causal, and counterfactual reasoning (5.0).

Timelines represent sequences (before/after/during/overlap, duration,
frequency, recurrence) WITHOUT inferring causality. Causal promotion
requires explicit evidence through staged statuses. Counterfactuals
are labeled HYPOTHETICAL computations over copied state — they can
never touch live systems.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class CausalStatus(str, Enum):
    CORRELATION = "correlation"
    TEMPORAL_ASSOCIATION = "temporal_association"
    CAUSE_CANDIDATE = "cause_candidate"
    VERIFIED_CAUSE = "verified_cause"
    UNKNOWN = "unknown"


class TemporalError(ValueError):
    """Malformed timeline or causal structure."""


def _utcnow() -> float:
    return time.time()


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


@dataclass
class TimelineEvent:
    event_id: str = field(default_factory=lambda: _new_id("tev"))
    label: str = ""
    at: float = field(default_factory=_utcnow)
    duration_s: float = 0.0
    source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.label:
            raise TemporalError("timeline event needs a label")


@dataclass
class Timeline:
    events: list[TimelineEvent] = field(default_factory=list)
    max_events: int = 200

    def add(self, label: str, *, at: float = 0.0,
            duration_s: float = 0.0, source: str = "") -> TimelineEvent:
        event = TimelineEvent(label=label[:200], at=at or _utcnow(),
                              duration_s=max(0.0, duration_s),
                              source=source[:80])
        self.events.append(event)
        del self.events[:-self.max_events]
        return event

    def order(self) -> list[TimelineEvent]:
        return sorted(self.events, key=lambda e: (e.at, e.event_id))

    def relations(self) -> list[dict[str, Any]]:
        """before/after/overlap/during pairs. Sequence only, no causes."""
        ordered = self.order()
        out: list[dict[str, Any]] = []
        for first, second in zip(ordered, ordered[1:]):
            if second.at < first.at:
                relation = "overlap"
            elif second.at - first.at <= max(first.duration_s, 1.0):
                relation = "during"
            else:
                relation = "after"
            out.append({"first": first.label, "second": second.label,
                        "relation": relation,
                        "gap_s": round(second.at - first.at, 2)})
        return out

    def frequency(self, label: str, window_s: float = 3600.0,
                  at: float = 0.0) -> dict[str, Any]:
        """Count + rate of a label in a trailing window."""
        now = at or _utcnow()
        hits = [e for e in self.events
                if e.label == label and now - e.at <= window_s]
        return {"label": label, "count": len(hits), "window_s": window_s,
                "rate_per_hour": round(len(hits) * 3600.0 / window_s, 3)}


@dataclass
class CausalLink:
    cause: str
    effect: str
    status: CausalStatus = CausalStatus.CORRELATION
    evidence: list[str] = field(default_factory=list)
    mechanism: str = ""
    link_id: str = field(default_factory=lambda: _new_id("csl"))

    def __post_init__(self) -> None:
        if isinstance(self.status, str):
            try:
                self.status = CausalStatus(self.status)
            except ValueError:
                raise TemporalError(f"invalid status: {self.status!r}")
        if not self.cause or not self.effect:
            raise TemporalError("causal link needs cause and effect")


class CausalEngine:
    """Staged promotion: temporal links start low, evidence promotes."""

    def __init__(self) -> None:
        self.links: dict[str, CausalLink] = {}
        self.metrics: dict[str, int] = {"links": 0, "promotions": 0}

    def propose(self, cause: str, effect: str, *,
                temporal: bool = False,
                evidence: list[str] | None = None) -> CausalLink:
        link = CausalLink(
            cause=cause[:200], effect=effect[:200],
            status=CausalStatus.TEMPORAL_ASSOCIATION if temporal
            else CausalStatus.CORRELATION,
            evidence=[str(e)[:200] for e in (evidence or [])][:10])
        self.links[link.link_id] = link
        self.metrics["links"] += 1
        return link

    def promote(self, link_id: str, to: CausalStatus, *,
                evidence: str = "", mechanism: str = "") -> CausalLink:
        """Promote exactly one stage per call, with fresh evidence.

        VERIFIED_CAUSE additionally requires a stated mechanism.
        Temporal links can never jump straight to verified.
        """
        link = self.links.get(link_id)
        if link is None:
            raise TemporalError(f"unknown causal link: {link_id}")
        order = [CausalStatus.CORRELATION,
                 CausalStatus.TEMPORAL_ASSOCIATION,
                 CausalStatus.CAUSE_CANDIDATE, CausalStatus.VERIFIED_CAUSE]
        if link.status == CausalStatus.UNKNOWN or to not in order:
            raise TemporalError("invalid promotion target")
        current = order.index(link.status)
        if order.index(to) != current + 1:
            raise TemporalError("promotion must advance exactly one stage")
        if not evidence:
            raise TemporalError("promotion requires fresh evidence")
        if to == CausalStatus.VERIFIED_CAUSE and not mechanism:
            raise TemporalError("verified cause requires a mechanism")
        link.status = to
        link.evidence.append(evidence[:200])
        if mechanism:
            link.mechanism = mechanism[:300]
        self.metrics["promotions"] += 1
        return link


@dataclass
class Counterfactual:
    """A hypothetical: labeled, bounded, side-effect free by construction
    (it only holds dicts — callers must pass COPIES of live state)."""
    question: str
    hypothetical_change: dict[str, Any] = field(default_factory=dict)
    predicted_state: dict[str, Any] = field(default_factory=dict)
    risks: list[str] = field(default_factory=list)
    uncertainty: list[str] = field(default_factory=list)
    label: str = "HYPOTHETICAL"
    counterfactual_id: str = field(default_factory=lambda: _new_id("ctf"))

    def __post_init__(self) -> None:
        if not self.question:
            raise TemporalError("counterfactual needs a question")
        if self.label != "HYPOTHETICAL":
            raise TemporalError("counterfactual label is fixed")


def evaluate_counterfactual(question: str, base_state: dict[str, Any],
                            change: dict[str, Any]) -> Counterfactual:
    """Pure-dict hypothetical evaluation. No I/O, no execution."""
    if not isinstance(base_state, dict) or not isinstance(change, dict):
        raise TemporalError("counterfactual needs dict state and change")
    predicted = dict(base_state)
    applied, unknown = [], []
    for key, value in list(change.items())[:20]:
        if key in predicted:
            predicted[key] = value
            applied.append(str(key)[:80])
        else:
            unknown.append(str(key)[:80])
    risks = [f"unknown key {key}: no basis for prediction"
             for key in unknown]
    return Counterfactual(
        question=question[:300],
        hypothetical_change={str(k)[:80]: str(v)[:200]
                             for k, v in list(change.items())[:20]},
        predicted_state={str(k)[:80]: str(v)[:200]
                         for k, v in list(predicted.items())[:30]},
        risks=risks,
        uncertainty=["hypothetical only: not observed", *risks][:10])


__all__ = [
    "CausalEngine",
    "CausalLink",
    "CausalStatus",
    "Counterfactual",
    "TemporalError",
    "Timeline",
    "TimelineEvent",
    "evaluate_counterfactual",
]
