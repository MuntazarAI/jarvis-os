"""Core value types shared across JARVIS subsystems."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


def now() -> float:
    return time.time()


def new_id(prefix: str = "") -> str:
    token = uuid.uuid4().hex[:16]
    return f"{prefix}-{token}" if prefix else token


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Confidence(str, Enum):
    UNKNOWN = "unknown"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    @property
    def numeric(self) -> float:
        return {
            Confidence.UNKNOWN: 0.0,
            Confidence.LOW: 0.3,
            Confidence.MEDIUM: 0.6,
            Confidence.HIGH: 0.9,
        }[self]

    @classmethod
    def from_score(cls, score: float) -> "Confidence":
        if score < 0.15:
            return cls.UNKNOWN
        if score < 0.45:
            return cls.LOW
        if score < 0.8:
            return cls.MEDIUM
        return cls.HIGH


class RiskLevel(str, Enum):
    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    DESTRUCTIVE = "destructive"

    @property
    def numeric(self) -> float:
        return {
            RiskLevel.SAFE: 0.0,
            RiskLevel.LOW: 0.2,
            RiskLevel.MEDIUM: 0.5,
            RiskLevel.HIGH: 0.75,
            RiskLevel.DESTRUCTIVE: 0.95,
        }[self]

    @classmethod
    def from_score(cls, score: float) -> "RiskLevel":
        if score < 0.1:
            return cls.SAFE
        if score < 0.35:
            return cls.LOW
        if score < 0.6:
            return cls.MEDIUM
        if score < 0.85:
            return cls.HIGH
        return cls.DESTRUCTIVE


class TaskState(str, Enum):
    QUEUED = "queued"
    PLANNING = "planning"
    RUNNING = "running"
    WAITING = "waiting"
    BLOCKED = "blocked"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Modality(str, Enum):
    TEXT = "text"
    VOICE = "voice"
    IMAGE = "image"
    VIDEO = "video"
    SCREEN = "screen"
    CAMERA = "camera"
    DOCUMENT = "document"
    SENSOR = "sensor"
    SYSTEM = "system"


@dataclass
class Provenance:
    """Where a piece of knowledge came from."""

    source: str = "unknown"
    modality: str = Modality.TEXT.value
    locator: str = ""
    reliability: float = 0.5
    session_id: str = ""
    recorded_at: float = field(default_factory=now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Observation:
    """A direct record of what was perceived. No interpretation."""

    kind: str
    content: str
    modality: str = Modality.TEXT.value
    source: str = "user"
    timestamp: float = field(default_factory=now)
    confidence: float = 0.8
    metadata: dict[str, Any] = field(default_factory=dict)
    observation_id: str = field(default_factory=lambda: new_id("obs"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Evidence:
    """An observation promoted to evidence, with provenance."""

    summary: str
    supports: list[str] = field(default_factory=list)
    contradicts: list[str] = field(default_factory=list)
    reliability: float = 0.6
    provenance: Provenance = field(default_factory=Provenance)
    evidence_id: str = field(default_factory=lambda: new_id("ev"))
    timestamp: float = field(default_factory=now)
    expires_at: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["provenance"] = self.provenance.to_dict()
        return data


@dataclass
class Hypothesis:
    """A candidate explanation. Always kept alongside alternatives."""

    claim: str
    probability: float = 0.5
    supporting: list[str] = field(default_factory=list)
    against: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    disconfirming_test: str = ""
    assumptions: list[str] = field(default_factory=list)
    hypothesis_id: str = field(default_factory=lambda: new_id("hyp"))
    created_at: float = field(default_factory=now)
    updated_at: float = field(default_factory=now)
    status: str = "open"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Contradiction:
    """A conflict between two sources."""

    source_a: str
    source_b: str
    statement_a: str
    statement_b: str
    kind: str = "direct"
    resolution: str = ""
    confidence: float = 0.7
    contradiction_id: str = field(default_factory=lambda: new_id("ctr"))
    timestamp: float = field(default_factory=now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Task:
    goal: str
    task_id: str = field(default_factory=lambda: new_id("task"))
    state: TaskState = TaskState.QUEUED
    priority: int = 5
    depends_on: list[str] = field(default_factory=list)
    assigned_agent: str = ""
    steps: list[dict[str, Any]] = field(default_factory=list)
    result: Any = None
    error: str = ""
    progress: float = 0.0
    deadline: float | None = None
    attempts: int = 0
    history: list[dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=now)
    updated_at: float = field(default_factory=now)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["state"] = self.state.value
        return data


@dataclass
class ActionPlan:
    """Pre/post conditioned plan for a tool action."""

    action: str
    args: dict[str, Any] = field(default_factory=dict)
    preconditions: list[str] = field(default_factory=list)
    postconditions: list[str] = field(default_factory=list)
    side_effects: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    resource_requirements: dict[str, Any] = field(default_factory=dict)
    required_permissions: list[str] = field(default_factory=list)
    expected_duration: float = 1.0
    failure_conditions: list[str] = field(default_factory=list)
    recovery_actions: list[str] = field(default_factory=list)
    verification_conditions: list[str] = field(default_factory=list)
    rollback_actions: list[str] = field(default_factory=list)
    risk: RiskLevel = RiskLevel.LOW
    reversibility: bool = True

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["risk"] = self.risk.value
        return data


@dataclass
class CognitiveReport:
    """Mentalist display contract: observations, evidence, hypotheses, unknowns."""

    observations: list[Observation] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    hypotheses: list[Hypothesis] = field(default_factory=list)
    contradictions: list[Contradiction] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    alternatives: list[str] = field(default_factory=list)
    confidence: Confidence = Confidence.UNKNOWN
    next_test: str = ""
    baseline: dict[str, Any] = field(default_factory=dict)
    deviations: list[str] = field(default_factory=list)

    def render(self) -> str:
        lines: list[str] = []
        lines.append("OBSERVATIONS")
        if self.observations:
            for obs in self.observations:
                lines.append(f"  - [{obs.modality}] {obs.content} ({obs.source}, {obs.timestamp:.0f})")
        else:
            lines.append("  (none recorded)")

        lines.append("EVIDENCE")
        if self.evidence:
            for ev in self.evidence:
                lines.append(f"  - {ev.summary} (reliability {ev.reliability:.2f}, {ev.provenance.source})")
        else:
            lines.append("  (none collected)")

        lines.append("HYPOTHESES")
        if self.hypotheses:
            for hyp in self.hypotheses:
                lines.append(f"  - {hyp.claim} [p={hyp.probability:.2f}]")
        else:
            lines.append("  (none)")

        lines.append("ALTERNATIVES")
        if self.alternatives:
            for alt in self.alternatives:
                lines.append(f"  - {alt}")
        else:
            lines.append("  (none retained)")

        if self.contradictions:
            lines.append("CONTRADICTIONS")
            for c in self.contradictions:
                lines.append(f"  - {c.source_a} vs {c.source_b}: {c.statement_a} / {c.statement_b}")

        lines.append("UNKNOWN")
        if self.unknowns:
            for unk in self.unknowns:
                lines.append(f"  - {unk}")
        else:
            lines.append("  (none identified)")

        lines.append(f"CONFIDENCE: {self.confidence.value}")
        lines.append(f"NEXT TEST: {self.next_test or '(none proposed)'}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "observations": [o.to_dict() for o in self.observations],
            "evidence": [e.to_dict() for e in self.evidence],
            "hypotheses": [h.to_dict() for h in self.hypotheses],
            "contradictions": [c.to_dict() for c in self.contradictions],
            "unknowns": self.unknowns,
            "alternatives": self.alternatives,
            "confidence": self.confidence.value,
            "next_test": self.next_test,
            "baseline": self.baseline,
            "deviations": self.deviations,
        }


def dumps(value: Any) -> str:
    return json.dumps(value, default=str, sort_keys=True)
