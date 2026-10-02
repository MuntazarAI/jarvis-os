"""Mission proposals 3.4 — evidence-backed suggestions awaiting approval.

A proposal NEVER executes anything. Approval only permits Mission
creation via MissionManager; execution still flows Mission → Objective
→ Dot → Task → Orchestrator → PolicyEngine → approval → tool.

Lifecycle: DRAFT → PROPOSED → APPROVED → CONVERTED (mission created)
                     ↘ REJECTED / IGNORED / EXPIRED / CANCELLED (archived)
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..core.types import new_id, now

PROPOSAL_SCHEMA_VERSION = 1


class ProposalStatus(str, Enum):
    DRAFT = "draft"
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    IGNORED = "ignored"
    EXPIRED = "expired"
    CONVERTED = "converted"
    CANCELLED = "cancelled"


PROPOSAL_TRANSITIONS: dict[ProposalStatus, frozenset[ProposalStatus]] = {
    ProposalStatus.DRAFT: frozenset({ProposalStatus.PROPOSED,
                                     ProposalStatus.CANCELLED}),
    ProposalStatus.PROPOSED: frozenset({ProposalStatus.APPROVED,
                                        ProposalStatus.REJECTED,
                                        ProposalStatus.IGNORED,
                                        ProposalStatus.EXPIRED,
                                        ProposalStatus.CANCELLED}),
    ProposalStatus.APPROVED: frozenset({ProposalStatus.CONVERTED,
                                        ProposalStatus.CANCELLED,
                                        ProposalStatus.EXPIRED}),
    ProposalStatus.REJECTED: frozenset(),
    ProposalStatus.IGNORED: frozenset(),
    ProposalStatus.EXPIRED: frozenset(),
    ProposalStatus.CONVERTED: frozenset(),
    ProposalStatus.CANCELLED: frozenset(),
}

PROPOSAL_TERMINAL = frozenset({ProposalStatus.REJECTED, ProposalStatus.IGNORED,
                               ProposalStatus.EXPIRED, ProposalStatus.CONVERTED,
                               ProposalStatus.CANCELLED})


class InvalidProposalTransition(Exception):
    """Illegal proposal lifecycle transition attempted."""


def validate_proposal_transition(from_status: ProposalStatus,
                                 to_status: ProposalStatus) -> None:
    if to_status not in PROPOSAL_TRANSITIONS[from_status]:
        raise InvalidProposalTransition(
            f"proposal cannot move {from_status.value} → {to_status.value}")


def proposal_dedup_key(source: str, goal: str, blocker: str = "",
                       kind: str = "") -> str:
    """Deterministic identity: same source+goal+blocker ⇒ same proposal."""
    raw = f"{source}|{goal.strip().lower()}|{blocker.strip().lower()}|{kind}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


@dataclass
class MissionProposal:
    proposal_id: str = field(default_factory=lambda: new_id("prop"))
    title: str = ""
    description: str = ""
    reason: str = ""
    source: str = ""  # goal|blocked-mission|blocked-objective|failure|
    # capability-gap|world-change|event|schedule|user-request
    source_refs: list[str] = field(default_factory=list)
    goal_refs: list[str] = field(default_factory=list)
    world_refs: list[str] = field(default_factory=list)
    event_refs: list[str] = field(default_factory=list)
    mission_template: dict[str, Any] = field(default_factory=dict)
    suggested_objectives: list[dict[str, Any]] = field(default_factory=list)
    suggested_dots: list[str] = field(default_factory=list)
    priority: int = 5
    confidence: float = 0.5
    uncertainty: list[str] = field(default_factory=list)
    impact: str = "medium"  # low|medium|high
    urgency: float = 0.5
    relevance: float = 0.5
    novelty: float = 0.5
    score: float = 0.0
    score_factors: dict[str, float] = field(default_factory=dict)
    created_at: float = field(default_factory=now)
    expires_at: float | None = None
    status: ProposalStatus = ProposalStatus.DRAFT
    dedup_key: str = ""
    evidence_refs: list[str] = field(default_factory=list)
    converted_mission_id: str = ""
    version: int = 1
    provenance: dict[str, Any] = field(default_factory=dict)

    def transition(self, to_status: ProposalStatus) -> None:
        validate_proposal_transition(self.status, to_status)
        self.status = to_status
        self.version += 1

    @property
    def expired(self) -> bool:
        return self.expires_at is not None and now() >= self.expires_at

    def to_dict(self) -> dict[str, Any]:
        data = dict(self.__dict__)
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MissionProposal":
        status = data.get("status", "draft")
        try:
            parsed = ProposalStatus(status)
        except ValueError:
            parsed = ProposalStatus.DRAFT
        return cls(
            proposal_id=data.get("proposal_id", new_id("prop")),
            title=data.get("title", ""),
            description=data.get("description", ""),
            reason=data.get("reason", ""),
            source=data.get("source", ""),
            source_refs=list(data.get("source_refs", [])),
            goal_refs=list(data.get("goal_refs", [])),
            world_refs=list(data.get("world_refs", [])),
            event_refs=list(data.get("event_refs", [])),
            mission_template=dict(data.get("mission_template", {})),
            suggested_objectives=list(data.get("suggested_objectives", [])),
            suggested_dots=list(data.get("suggested_dots", [])),
            priority=int(data.get("priority", 5)),
            confidence=float(data.get("confidence", 0.5)),
            uncertainty=list(data.get("uncertainty", [])),
            impact=data.get("impact", "medium"),
            urgency=float(data.get("urgency", 0.5)),
            relevance=float(data.get("relevance", 0.5)),
            novelty=float(data.get("novelty", 0.5)),
            score=float(data.get("score", 0.0)),
            score_factors=dict(data.get("score_factors", {})),
            created_at=data.get("created_at", now()),
            expires_at=data.get("expires_at"),
            status=parsed,
            dedup_key=data.get("dedup_key", ""),
            evidence_refs=list(data.get("evidence_refs", [])),
            converted_mission_id=data.get("converted_mission_id", ""),
            version=int(data.get("version", 1)),
            provenance=dict(data.get("provenance", {})))


def score_proposal(urgency: float, relevance: float, novelty: float,
                   confidence: float, recurrence: float = 0.0,
                   weights: dict[str, float] | None = None) -> tuple[float, dict[str, float]]:
    """Bounded deterministic score in [0, 1] with exposed factors.

    No ML, no subjective importance: weighted mean of the four inputs.
    Weights default to 1.0 and are clamped to [0.5, 1.5] when supplied.
    """
    weights = weights or {}
    bounded = {k: max(0.5, min(1.5, float(weights.get(k, 1.0))))
               for k in ("urgency", "relevance", "novelty", "confidence")}
    factors = {
        "urgency": max(0.0, min(1.0, urgency)) * bounded["urgency"],
        "relevance": max(0.0, min(1.0, relevance)) * bounded["relevance"],
        "novelty": max(0.0, min(1.0, novelty)) * bounded["novelty"],
        "confidence": max(0.0, min(1.0, confidence)) * bounded["confidence"],
    }
    if recurrence:
        factors["recurrence"] = max(0.0, min(1.0, recurrence))
    total = sum(factors.values()) / len(factors)
    return round(max(0.0, min(1.0, total)), 4), factors
