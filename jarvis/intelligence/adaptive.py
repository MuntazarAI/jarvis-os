"""Adaptive intelligence primitives for JARVIS 5.0.

This module adds bounded, deterministic intelligence infrastructure around the
existing cognitive loop.  It deliberately does not execute tools, grant
permissions, or mutate the existing policy boundary.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _now() -> float:
    return time.time()


def _confidence(value: float) -> float:
    value = float(value)
    if not math.isfinite(value):
        return 0.0
    return max(0.0, min(1.0, value))


class EvidenceStatus(str, Enum):
    KNOWN = "known"
    LIKELY = "likely"
    UNCERTAIN = "uncertain"
    CONTRADICTED = "contradicted"
    UNKNOWN = "unknown"


class BeliefStatus(str, Enum):
    ACTIVE = "active"
    WEAKENED = "weakened"
    CONTRADICTED = "contradicted"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"
    UNKNOWN = "unknown"


class CausalStatus(str, Enum):
    CORRELATION = "correlation"
    TEMPORAL_ASSOCIATION = "temporal_association"
    CAUSE_CANDIDATE = "cause_candidate"
    VERIFIED_CAUSE = "verified_cause"
    UNKNOWN = "unknown"


class DecisionMode(str, Enum):
    ACT = "act"
    ASK = "ask"
    WAIT = "wait"
    EXPLAIN = "explain"
    STOP = "stop"
    ESCALATE = "escalate"


@dataclass(frozen=True)
class Evidence:
    content: str
    source: str
    confidence: float = 0.5
    timestamp: float = field(default_factory=_now)
    evidence_id: str = field(default_factory=lambda: _id("ev"))
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "confidence", _confidence(self.confidence))


@dataclass
class Belief:
    proposition: str
    confidence: float = 0.5
    evidence: list[Evidence] = field(default_factory=list)
    status: BeliefStatus = BeliefStatus.ACTIVE
    freshness_s: float | None = None
    contradictions: list[str] = field(default_factory=list)
    belief_id: str = field(default_factory=lambda: _id("belief"))

    def __post_init__(self) -> None:
        self.confidence = _confidence(self.confidence)

    @property
    def evidence_status(self) -> EvidenceStatus:
        if self.status is BeliefStatus.CONTRADICTED:
            return EvidenceStatus.CONTRADICTED
        if not self.evidence:
            return EvidenceStatus.UNKNOWN
        if self.confidence >= 0.85:
            return EvidenceStatus.KNOWN
        if self.confidence >= 0.6:
            return EvidenceStatus.LIKELY
        return EvidenceStatus.UNCERTAIN

    def add_evidence(self, item: Evidence, *, supports: bool = True) -> None:
        self.evidence.append(item)
        weight = item.confidence
        if supports:
            self.confidence = _confidence(self.confidence + (1.0 - self.confidence) * weight * 0.25)
            if self.status in {BeliefStatus.UNKNOWN, BeliefStatus.WEAKENED}:
                self.status = BeliefStatus.ACTIVE
        else:
            self.contradictions.append(item.evidence_id)
            self.confidence = _confidence(self.confidence * (1.0 - 0.5 * weight))
            self.status = BeliefStatus.CONTRADICTED if self.confidence < 0.25 else BeliefStatus.WEAKENED


@dataclass(frozen=True)
class Hypothesis:
    statement: str
    supporting: tuple[str, ...] = ()
    contradicting: tuple[str, ...] = ()
    confidence: float = 0.0
    required_evidence: tuple[str, ...] = ()
    hypothesis_id: str = field(default_factory=lambda: _id("hyp"))

    def __post_init__(self) -> None:
        object.__setattr__(self, "confidence", _confidence(self.confidence))


@dataclass(frozen=True)
class InformationRequest:
    question: str
    source: str
    expected_information_gain: float
    cost: float = 1.0
    risk: float = 0.0
    request_id: str = field(default_factory=lambda: _id("info"))

    @property
    def utility(self) -> float:
        cost = max(0.01, float(self.cost))
        risk = max(0.0, float(self.risk))
        return self.expected_information_gain / cost - risk


@dataclass(frozen=True)
class Goal:
    description: str
    success_criteria: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    risk: float = 0.0
    goal_id: str = field(default_factory=lambda: _id("goal"))


@dataclass(frozen=True)
class PlanStep:
    description: str
    prerequisites: tuple[str, ...] = ()
    expected: str = ""
    verification: str = ""
    risk: float = 0.0
    reversible: bool = True
    step_id: str = field(default_factory=lambda: _id("step"))


@dataclass(frozen=True)
class Plan:
    goal_id: str
    steps: tuple[PlanStep, ...]
    bounded: bool = True
    plan_id: str = field(default_factory=lambda: _id("plan"))


@dataclass(frozen=True)
class Prediction:
    statement: str
    confidence: float
    basis: tuple[str, ...] = ()
    prediction_id: str = field(default_factory=lambda: _id("pred"))
    created_at: float = field(default_factory=_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "confidence", _confidence(self.confidence))


@dataclass(frozen=True)
class Outcome:
    status: str
    observed: str
    expected: str = ""
    prediction_error: float = 0.0
    verified: bool = False
    timestamp: float = field(default_factory=_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "prediction_error", _confidence(abs(self.prediction_error)))


@dataclass(frozen=True)
class Experience:
    observation: str
    context: Mapping[str, Any]
    belief_ids: tuple[str, ...]
    prediction: Prediction | None
    decision: str
    outcome: Outcome
    experience_id: str = field(default_factory=lambda: _id("exp"))
    created_at: float = field(default_factory=_now)


class ExperienceStore:
    """Bounded append-only JSONL experience store.

    Historical experiences are never overwritten. Secrets should already be
    classified upstream; this store additionally strips obvious key names.
    """

    _SECRET_KEYS = {"password", "passwd", "token", "secret", "api_key", "private_key"}

    def __init__(self, home: str | Path | None, *, max_records: int = 5000) -> None:
        self.home = Path(home) if home else None
        self.max_records = max(1, min(int(max_records), 100_000))

    @property
    def path(self) -> Path | None:
        return None if self.home is None else self.home / "experiences.jsonl"

    @classmethod
    def _scrub(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            return {
                str(k): "[REDACTED]" if str(k).lower() in cls._SECRET_KEYS else cls._scrub(v)
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [cls._scrub(v) for v in value[:100]]
        if isinstance(value, str):
            return value[:4000]
        return value

    def append(self, experience: Experience) -> bool:
        path = self.path
        if path is None:
            return False
        payload = self._scrub(asdict(experience))
        line = json.dumps(payload, sort_keys=True, default=str)
        if len(line.encode("utf-8")) > 128 * 1024:
            return False
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
            self._compact()
            return True
        except OSError:
            return False

    def _compact(self) -> None:
        path = self.path
        if path is None or not path.exists():
            return
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
            if len(lines) > self.max_records:
                path.write_text("\n".join(lines[-self.max_records:]) + "\n", encoding="utf-8")
        except OSError:
            return

    def read(self, limit: int = 100) -> list[dict[str, Any]]:
        path = self.path
        if path is None or not path.exists():
            return []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        result: list[dict[str, Any]] = []
        for raw in reversed(lines[-max(1, min(limit, self.max_records)):]):
            try:
                item = json.loads(raw)
            except ValueError:
                continue
            if isinstance(item, dict):
                result.append(item)
        return result


class HypothesisEngine:
    """Deterministic hypothesis ranking; it never turns hypotheses into facts."""

    def generate(
        self,
        observations: Sequence[Evidence],
        candidates: Sequence[str],
        *,
        max_hypotheses: int = 5,
    ) -> list[Hypothesis]:
        obs = list(observations)[:100]
        out: list[Hypothesis] = []
        for statement in candidates[:max(1, min(max_hypotheses, 20))]:
            text = statement.strip()
            if not text:
                continue
            support = [e.evidence_id for e in obs if self._matches(text, e.content)]
            contradiction = [e.evidence_id for e in obs if not self._matches(text, e.content)]
            score = 0.0
            if obs:
                score = sum(obs[i].confidence for i in range(len(support))) / len(obs)
            score = _confidence(score)
            out.append(Hypothesis(
                statement=text,
                supporting=tuple(support[:20]),
                contradicting=tuple(contradiction[:20]),
                confidence=score,
            ))
        return sorted(out, key=lambda h: (-h.confidence, h.statement))[:max_hypotheses]

    @staticmethod
    def _matches(statement: str, content: str) -> bool:
        tokens = {t for t in statement.lower().split() if len(t) > 2}
        haystack = content.lower()
        return bool(tokens) and sum(1 for token in tokens if token in haystack) >= max(1, len(tokens) // 3)


class InformationGatherer:
    """Selects the safest high-utility observation; it does not execute it."""

    def choose(self, requests: Iterable[InformationRequest]) -> InformationRequest | None:
        candidates = list(requests)[:100]
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda item: (item.utility, item.expected_information_gain, -item.risk),
        )


class GoalInterpreter:
    """Converts a high-level goal into a bounded, inspectable goal contract."""

    def interpret(
        self,
        description: str,
        *,
        constraints: Sequence[str] = (),
        success_criteria: Sequence[str] = (),
        risk: float = 0.0,
    ) -> Goal:
        text = " ".join(str(description).split())[:1000]
        if not text:
            raise ValueError("goal description is required")
        return Goal(
            description=text,
            constraints=tuple(str(x)[:300] for x in constraints[:20]),
            success_criteria=tuple(str(x)[:300] for x in success_criteria[:20]),
            risk=_confidence(risk),
        )


class PlanCritic:
    """Static plan review. It never executes plan steps."""

    def review(self, plan: Plan) -> tuple[bool, list[str]]:
        problems: list[str] = []
        if not plan.bounded:
            problems.append("plan is unbounded")
        if not plan.steps:
            problems.append("plan has no steps")
        if len(plan.steps) > 100:
            problems.append("plan exceeds step budget")
        ids = {step.step_id for step in plan.steps}
        for step in plan.steps:
            if any(req not in ids for req in step.prerequisites):
                problems.append(f"missing prerequisite for {step.step_id}")
            if not step.verification:
                problems.append(f"missing verification for {step.step_id}")
            if not math.isfinite(step.risk) or not 0.0 <= step.risk <= 1.0:
                problems.append(f"invalid risk for {step.step_id}")
        return not problems, problems


class LearningEngine:
    """Updates evidence-derived statistics only.

    Security policy, permissions, trust and secrets are intentionally outside
    this API.
    """

    def prediction_error(self, prediction: Prediction | None, outcome: Outcome) -> float:
        if prediction is None:
            return 0.0
        return _confidence(abs(prediction.confidence - (1.0 if outcome.verified else 0.0)))

    def update_belief(self, belief: Belief, outcome: Outcome) -> Belief:
        weight = max(0.05, 1.0 - self.prediction_error(None, outcome))
        if outcome.verified:
            belief.confidence = _confidence(belief.confidence + (1 - belief.confidence) * 0.2 * weight)
        else:
            belief.confidence = _confidence(belief.confidence * (1 - 0.2 * weight))
            if belief.confidence < 0.25:
                belief.status = BeliefStatus.WEAKENED
        return belief


class AdaptiveIntelligence:
    """Small deterministic facade used by higher-level cognitive code."""

    def __init__(self, experience_store: ExperienceStore | None = None) -> None:
        self.experiences = experience_store
        self.hypotheses = HypothesisEngine()
        self.information = InformationGatherer()
        self.goals = GoalInterpreter()
        self.critic = PlanCritic()
        self.learning = LearningEngine()

    def digest(
        self,
        observation: str,
        *,
        evidence: Sequence[Evidence] = (),
        candidate_hypotheses: Sequence[str] = (),
        goal: str = "",
    ) -> dict[str, Any]:
        evidence_list = list(evidence)[:100]
        hypotheses = self.hypotheses.generate(evidence_list, candidate_hypotheses)
        result: dict[str, Any] = {
            "observation": str(observation)[:4000],
            "hypotheses": [asdict(h) for h in hypotheses],
            "status": EvidenceStatus.UNKNOWN.value if not evidence_list else hypotheses[0].evidence_status.value if hypotheses else EvidenceStatus.UNCERTAIN.value,
        }
        if goal:
            result["goal"] = asdict(self.goals.interpret(goal))
        return result


def capability_fingerprint(capabilities: Mapping[str, bool]) -> str:
    normalized = {str(k): bool(v) for k, v in sorted(capabilities.items())}
    return hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest()[:16]
