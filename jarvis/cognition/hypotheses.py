"""Hypotheses + uncertainty engine (5.0).

Ranked candidate explanations with supporting/contradicting evidence.
The top hypothesis is NEVER presented as true — only as the current
best candidate with explicit confidence and missing evidence.

Uncertainty states: KNOWN | LIKELY | UNCERTAIN | CONTRADICTED |
UNKNOWN. Uncertain input stays uncertain; nothing here forces a
binary answer.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from .beliefs import clamp_confidence


class Uncertainty(str, Enum):
    KNOWN = "known"
    LIKELY = "likely"
    UNCERTAIN = "uncertain"
    CONTRADICTED = "contradicted"
    UNKNOWN = "unknown"


class HypothesisStatus(str, Enum):
    CANDIDATE = "candidate"
    LEADING = "leading"
    CONFIRMED = "confirmed"
    RULED_OUT = "ruled_out"
    STALE = "stale"


class HypothesisError(ValueError):
    """Malformed hypothesis or engine misuse."""


def _utcnow() -> float:
    return time.time()


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


@dataclass
class Hypothesis:
    hypothesis_id: str = field(default_factory=lambda: _new_id("hyp"))
    statement: str = ""
    supporting: list[str] = field(default_factory=list)
    contradicting: list[str] = field(default_factory=list)
    confidence: float = 0.5
    required_evidence: list[str] = field(default_factory=list)
    status: HypothesisStatus = HypothesisStatus.CANDIDATE
    provenance: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        if isinstance(self.status, str):
            try:
                self.status = HypothesisStatus(self.status)
            except ValueError:
                raise HypothesisError(f"invalid status: {self.status!r}")
        if not self.statement or len(self.statement) > 500:
            raise HypothesisError("statement must be 1..500 chars")
        self.confidence = clamp_confidence(self.confidence)
        if len(self.supporting) > 20 or len(self.contradicting) > 20:
            raise HypothesisError("too much evidence (cap 20 per side)")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data

    @property
    def uncertainty(self) -> Uncertainty:
        if self.contradicting and self.supporting:
            return Uncertainty.CONTRADICTED
        if self.confidence >= 0.8 and self.supporting:
            return Uncertainty.KNOWN
        if self.confidence >= 0.5:
            return Uncertainty.LIKELY
        if self.confidence > 0.2:
            return Uncertainty.UNCERTAIN
        return Uncertainty.UNKNOWN


@dataclass
class UnresolvedQuestion:
    question: str
    answers_from: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=_utcnow)


class HypothesisEngine:
    """Deterministic ranked hypothesis generation."""

    def __init__(self, max_hypotheses: int = 8) -> None:
        self.max_hypotheses = max(1, max_hypotheses)
        self.metrics: dict[str, int] = {"generated": 0, "ruled_out": 0}

    def generate(self, observations: list[dict[str, Any]],
                 context: dict[str, Any] | None = None,
                 goal: str = "") -> list[Hypothesis]:
        """Rank candidates from observations. Deterministic, bounded."""
        context = dict(context or {})
        candidates: list[Hypothesis] = []
        for obs in observations[:20]:
            if not isinstance(obs, dict):
                continue
            text = str(obs.get("summary", obs.get("text", "")))[:200]
            if not text:
                continue
            source = str(obs.get("source", "unknown"))[:80]
            candidates.append(Hypothesis(
                statement=f"observation explains goal: {text[:120]}",
                supporting=[str(obs.get("observation_id",
                                        obs.get("event_id", "")))[:64]],
                confidence=min(0.6, 0.3 + 0.1 * len(text) / 100.0),
                required_evidence=["independent corroboration"],
                provenance={"origin": "hypothesis-engine",
                            "source": source,
                            "goal": goal[:120]}))
        for key in ("cpu high", "memory high", "disk full", "offline"):
            if goal and key.split()[0] in goal.lower():
                candidates.append(Hypothesis(
                    statement=f"candidate cause: {key}",
                    supporting=["goal keyword match"],
                    confidence=0.4,
                    required_evidence=[f"metric confirming {key}"],
                    provenance={"origin": "hypothesis-engine",
                                "heuristic": "keyword"}))
        ranked = sorted(candidates,
                        key=lambda h: (h.confidence, h.statement),
                        reverse=True)[:self.max_hypotheses]
        for position, hypothesis in enumerate(ranked):
            hypothesis.status = HypothesisStatus.LEADING \
                if position == 0 else HypothesisStatus.CANDIDATE
        self.metrics["generated"] += len(ranked)
        return ranked

    def rule_out(self, hypothesis: Hypothesis, evidence: str) -> Hypothesis:
        """Mark ruled out WITH counter-evidence (never silently)."""
        hypothesis.status = HypothesisStatus.RULED_OUT
        hypothesis.contradicting.append(evidence[:200])
        self.metrics["ruled_out"] += 1
        return hypothesis

    def missing_evidence(self,
                         hypotheses: list[Hypothesis]) -> list[str]:
        """Union of blocking evidence needs across candidates."""
        needed: list[str] = []
        for hypothesis in hypotheses:
            for item in hypothesis.required_evidence:
                if item not in needed:
                    needed.append(item)
        return needed[:20]


__all__ = [
    "Hypothesis",
    "HypothesisEngine",
    "HypothesisError",
    "HypothesisStatus",
    "Uncertainty",
    "UnresolvedQuestion",
]
