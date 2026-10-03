"""Bounded deterministic learning engine (4.4).

Not a neural trainer: a deterministic adaptive updater. It consumes
evaluated experiences and produces belief adjustments, contradiction
records, recurring patterns, and memory-consolidation proposals —
every update carrying reason, evidence, old/new values, provenance.

Structural safety: this module imports NO policy, device, transport,
or permission code. It cannot grant, trust, authorize, or execute.
It reads experiences/beliefs/memories and writes beliefs/memories
(through the palace API) and nothing else.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .beliefs import BeliefStatus, BeliefStore, clamp_confidence
from .experience import (
    Experience,
    OutcomeEvaluation,
    OutcomeState,
    PredictionEvaluation,
    PredictionVerdict,
)

# Documented heuristic weights (tuned for stability, not science):
# each success/failure moves confidence by STEP, scaled by evidence
# strength and source reliability, clamped to [CONF_MIN, CONF_MAX].
CONF_STEP = 0.05
CONF_MIN = 0.05
CONF_MAX = 0.95
PATTERN_MIN_OCCURRENCES = 3
MAX_PATTERNS = 100


@dataclass
class LearningUpdate:
    kind: str  # confidence|contradiction|pattern|reliability|consolidation
    target: str
    old_value: Any = None
    new_value: Any = None
    reason: str = ""
    evidence_refs: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass
class LearningReport:
    experience_id: str
    updates: list[LearningUpdate] = field(default_factory=list)
    learned: bool = False
    reasons: list[str] = field(default_factory=list)


class LearningEngine:
    """Deterministic experience -> belief/memory updates."""

    def __init__(self, beliefs: BeliefStore | None = None) -> None:
        self.beliefs = beliefs
        self.metrics: dict[str, int] = {
            "experiences": 0, "updates": 0, "contradictions": 0,
            "patterns": 0, "consolidations": 0, "skipped": 0,
        }

    # -- main entry ------------------------------------------------------

    def learn_from_outcome(self, experience: Experience,
                           evaluation: OutcomeEvaluation,
                           *, by: str = "learning-engine") -> LearningReport:
        """One bounded pass over an evaluated experience."""
        report = LearningReport(experience_id=experience.experience_id)
        if experience.privacy_class == "private":
            report.reasons.append("private experience: never learned")
            self.metrics["skipped"] += 1
            return report
        if not evaluation.should_learn:
            report.reasons.append("evaluation says nothing to learn")
            self.metrics["skipped"] += 1
            return report
        if self.beliefs is None:
            report.reasons.append("no belief store bound")
            self.metrics["skipped"] += 1
            return report
        self.metrics["experiences"] += 1
        self._learn_prediction_accuracy(experience, evaluation, report,
                                       by=by)
        self._learn_action_outcome(experience, evaluation, report, by=by)
        report.learned = bool(report.updates)
        self.metrics["updates"] += len(report.updates)
        return report

    # -- prediction accuracy -----------------------------------------------

    def _learn_prediction_accuracy(self, experience: Experience,
                                   evaluation: OutcomeEvaluation,
                                   report: LearningReport, by: str) -> None:
        for prediction in experience.evaluations:
            if prediction.verdict == PredictionVerdict.CORRECT:
                self._nudge_experience_confidence(
                    experience, +1, prediction, report, by,
                    "prediction verified correct")
            elif prediction.verdict == PredictionVerdict.INCORRECT:
                self._nudge_experience_confidence(
                    experience, -1, prediction, report, by,
                    "prediction verified incorrect")
            elif prediction.verdict == PredictionVerdict.PARTIAL:
                self._record_contradiction_like(
                    experience, prediction, report, by)

    def _nudge_experience_confidence(self, experience: Experience,
                                     direction: int,
                                     prediction: PredictionEvaluation,
                                     report: LearningReport, by: str,
                                     reason: str) -> None:
        assert self.beliefs is not None
        statement = f"prediction '{prediction.prediction_id}' is reliable"
        matches = [b for b in self.beliefs.find(limit=1000)
                   if b.statement == statement
                   and b.status in (BeliefStatus.ACTIVE,
                                    BeliefStatus.WEAKENED)]
        belief = matches[0] if matches else self.beliefs.upsert(
            statement, 0.5, evidence=[experience.experience_id],
            sources=["prediction"], provenance={"origin": "learning"})
        strength = 0.5 + 0.5 * (prediction.confidence_before or 0.5)
        step = CONF_STEP * strength * (1 if direction > 0 else -1)
        old, new = belief.confidence, belief.confidence + step
        new = max(CONF_MIN, min(CONF_MAX, new))
        if self.beliefs.adjust(
                belief.belief_id, new, reason=reason,
                evidence=experience.experience_id, by=by):
            report.updates.append(LearningUpdate(
                kind="confidence", target=belief.belief_id,
                old_value=round(old, 4), new_value=round(new, 4),
                reason=reason,
                evidence_refs=[experience.experience_id],
                provenance={"by": by}))

    def _record_contradiction_like(self, experience: Experience,
                                   prediction: PredictionEvaluation,
                                   report: LearningReport, by: str) -> None:
        assert self.beliefs is not None
        statement = f"prediction '{prediction.prediction_id}' is reliable"
        for belief in self.beliefs.find(limit=1000):
            if belief.statement != statement:
                continue
            if self.beliefs.contradict(
                    belief.belief_id, experience.experience_id, by=by):
                report.updates.append(LearningUpdate(
                    kind="contradiction", target=belief.belief_id,
                    reason="partial prediction: mixed evidence preserved",
                    evidence_refs=[experience.experience_id],
                    provenance={"by": by}))
                self.metrics["contradictions"] += 1
            return

    # -- action outcomes -----------------------------------------------------

    def _learn_action_outcome(self, experience: Experience,
                              evaluation: OutcomeEvaluation,
                              report: LearningReport, by: str) -> None:
        assert self.beliefs is not None
        if evaluation.action_succeeded is True:
            self._record_pattern_candidate(
                experience, "action-succeeded", report, by)
        elif evaluation.action_succeeded is False:
            self._record_pattern_candidate(
                experience, "action-failed", report, by)
            self._weaken_stale_beliefs(experience, report, by)

    def _weaken_stale_beliefs(self, experience: Experience,
                              report: LearningReport, by: str) -> None:
        assert self.beliefs is not None
        for ref in experience.belief_refs[:5]:
            belief = self.beliefs.get(ref)
            if belief is None or belief.status != BeliefStatus.ACTIVE:
                continue
            old = belief.confidence
            new = max(CONF_MIN, old - CONF_STEP)
            if self.beliefs.adjust(
                    ref, new, reason="supporting action failed",
                    evidence=experience.experience_id, by=by):
                if new <= 0.3 and belief.status == BeliefStatus.ACTIVE:
                    self.beliefs.set_status(
                        ref, BeliefStatus.WEAKENED,
                        reason="repeated failure pressure", by=by)
                report.updates.append(LearningUpdate(
                    kind="confidence", target=ref,
                    old_value=round(old, 4), new_value=round(new, 4),
                    reason="supporting action failed",
                    evidence_refs=[experience.experience_id],
                    provenance={"by": by}))

    # -- patterns --------------------------------------------------------------

    def _record_pattern_candidate(self, experience: Experience, kind: str,
                                  report: LearningReport, by: str) -> None:
        assert self.beliefs is not None
        key = (f"pattern:{kind}:"
               f"{experience.outcome.value}")
        matches = [b for b in self.beliefs.find(limit=1000)
                   if b.statement == key]
        if matches:
            belief = matches[0]
            count = int(str(belief.provenance.get("occurrences", "1"))
                        if isinstance(belief.provenance.get("occurrences"),
                                      str) else belief.provenance.get(
                                          "occurrences", 1))
            belief.provenance["occurrences"] = count + 1
            belief.provenance["last_seen"] = experience.timestamp
            if experience.experience_id not in belief.evidence_refs:
                belief.evidence_refs.append(experience.experience_id)
                belief.evidence_refs = belief.evidence_refs[-20:]
            belief.revision += 1
            self.beliefs.save()
            if count + 1 >= PATTERN_MIN_OCCURRENCES:
                report.updates.append(LearningUpdate(
                    kind="pattern", target=belief.belief_id,
                    old_value=count, new_value=count + 1,
                    reason=f"recurring {kind} x{count + 1}",
                    evidence_refs=[experience.experience_id],
                    provenance={"by": by}))
                self.metrics["patterns"] += 1
            return
        self.beliefs.upsert(
            key, 0.5, evidence=[experience.experience_id],
            sources=["learning"],
            provenance={"origin": "learning", "occurrences": 1,
                        "kind": kind})

    # -- consolidation proposals ---------------------------------------------------

    def consolidation_proposals(self, min_confidence: float = 0.8,
                                limit: int = 20) -> list[dict[str, Any]]:
        """Beliefs eligible for durable semantic memory.

        Criteria (ALL required): ACTIVE, confidence >= threshold,
        >= 2 evidence refs, not already promoted. The caller (memory
        layer) decides; this only proposes.
        """
        if self.beliefs is None:
            return []
        out: list[dict[str, Any]] = []
        for belief in self.beliefs.find(status="active", limit=1000):
            if belief.confidence < min_confidence:
                continue
            if belief.privacy_class in ("sensitive", "private"):
                continue
            if len(belief.evidence_refs) < 2:
                continue
            if belief.provenance.get("promoted_to_memory"):
                continue
            out.append({"belief_id": belief.belief_id,
                        "statement": belief.statement,
                        "confidence": belief.confidence,
                        "evidence_refs": list(belief.evidence_refs)})
            if len(out) >= limit:
                break
        return out

    def mark_promoted(self, belief_id: str, memory_id: str) -> bool:
        """Record that a belief became durable memory (no content move)."""
        if self.beliefs is None:
            return False
        belief = self.beliefs.get(belief_id)
        if belief is None:
            return False
        belief.provenance["promoted_to_memory"] = memory_id[:64]
        belief.updated_at = time.time()
        belief.revision += 1
        self.beliefs.save()
        self.metrics["consolidations"] += 1
        return True

    # -- source reliability ----------------------------------------------------------

    def note_source_outcome(self, source: str, correct: bool) -> float:
        """Bounded reliability nudge per verified outcome."""
        if self.beliefs is None:
            return 0.5
        current = self.beliefs.reliability(source)
        new = max(CONF_MIN, min(CONF_MAX,
                                current + (CONF_STEP if correct
                                           else -CONF_STEP)))
        self.beliefs.note_reliability(source, new)
        return new


__all__ = [
    "LearningEngine",
    "LearningReport",
    "LearningUpdate",
    "CONF_STEP",
    "CONF_MIN",
    "CONF_MAX",
    "PATTERN_MIN_OCCURRENCES",
]
