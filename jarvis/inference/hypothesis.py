"""Hypothesis engine and lab: competing explanations, Bayesian updating, falsification."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core.types import Confidence, Hypothesis, now
from .evidence import EvidenceEngine


@dataclass
class HypothesisRecord:
    hypotheses: list[Hypothesis] = field(default_factory=list)
    distinguishing_evidence: list[str] = field(default_factory=list)
    updated_at: float = field(default_factory=now)

    @property
    def best(self) -> Hypothesis | None:
        return max(self.hypotheses, key=lambda h: h.probability) if self.hypotheses else None

    def ranked(self) -> list[Hypothesis]:
        return sorted(self.hypotheses, key=lambda h: -h.probability)

    def to_dict(self) -> dict[str, Any]:
        return {
            "hypotheses": [h.to_dict() for h in self.ranked()],
            "distinguishing_evidence": self.distinguishing_evidence,
            "best": self.best.claim if self.best else None,
            "best_probability": round(self.best.probability, 4) if self.best else 0.0,
            "updated_at": self.updated_at,
        }


class HypothesisEngine:
    """Retains multiple competing explanations. Never collapses to one story."""

    def __init__(self, limit: int = 5) -> None:
        self.limit = limit
        self.active: dict[str, Hypothesis] = {}
        self.history: list[Hypothesis] = []

    def propose(self, claim: str, prior: float = 0.4, assumptions: list[str] | None = None) -> Hypothesis:
        hyp = Hypothesis(
            claim=claim,
            probability=prior,
            assumptions=assumptions or [],
            disconfirming_test=self._default_test(claim),
        )
        self.active[hyp.hypothesis_id] = hyp
        self.history.append(hyp)
        if len(self.active) > self.limit:
            oldest = min(self.active.values(), key=lambda h: h.created_at)
            self.active.pop(oldest.hypothesis_id, None)
        return hyp

    @staticmethod
    def _default_test(claim: str) -> str:
        return f"Find an observation that would be inconsistent with: {claim}"

    def support(self, hyp_id: str, evidence_summary: str, weight: float = 0.15) -> Hypothesis | None:
        hyp = self.active.get(hyp_id)
        if not hyp:
            return None
        hyp.supporting.append(evidence_summary)
        hyp.probability = min(0.98, hyp.probability + weight)
        hyp.updated_at = now()
        return hyp

    def contradict(self, hyp_id: str, evidence_summary: str, weight: float = 0.25) -> Hypothesis | None:
        hyp = self.active.get(hyp_id)
        if not hyp:
            return None
        hyp.against.append(evidence_summary)
        hyp.probability = max(0.02, hyp.probability - weight)
        hyp.updated_at = now()
        return hyp

    def add_missing(self, hyp_id: str, item: str) -> Hypothesis | None:
        hyp = self.active.get(hyp_id)
        if not hyp:
            return None
        if item not in hyp.missing:
            hyp.missing.append(item)
        return hyp

    def bayesian_update(
        self, observations: list[tuple[str, float]], evidence_engine: EvidenceEngine | None = None
    ) -> HypothesisRecord:
        """Update probabilities from likelihood-weighted evidence.

        Each observation is (summary, likelihood_ratio). Alternatives are
        penalized proportionally so probabilities stay normalized.
        """
        record = self._record()
        if not record.hypotheses:
            return record
        for hyp in record.hypotheses:
            delta = 0.0
            for summary, likelihood in observations:
                if summary in hyp.against:
                    delta -= 0.1 * likelihood
                elif summary in hyp.supporting:
                    delta += 0.1 * likelihood
                else:
                    delta += 0.02 * likelihood - 0.03
            hyp.probability = max(0.02, min(0.98, hyp.probability + delta))
            hyp.updated_at = now()
        self._normalize()
        record.updated_at = now()
        return self._record()

    def _normalize(self) -> None:
        total = sum(h.probability for h in self.active.values())
        if total <= 0:
            for hyp in self.active.values():
                hyp.probability = 1.0 / len(self.active)
            return
        for hyp in self.active.values():
            hyp.probability = round(hyp.probability / total, 6)

    def distinguishing_evidence(self) -> list[str]:
        """Evidence that would separate the current top hypotheses."""
        # NOTE: rank directly from active state. Never call _record() here —
        # _record() calls this method, so that would recurse forever.
        top = sorted(self.active.values(), key=lambda h: -h.probability)[:2]
        if len(top) < 2:
            return []
        out: list[str] = []
        a, b = top
        only_a = [s for s in a.supporting if s not in b.supporting]
        only_b = [s for s in b.supporting if s not in a.supporting]
        if only_a:
            out.append(f"Check: {only_a[0]} — would support '{a.claim}' over '{b.claim}'")
        if only_b:
            out.append(f"Check: {only_b[0]} — would support '{b.claim}' over '{a.claim}'")
        if not out:
            out.append(
                f"Current evidence cannot distinguish '{a.claim}' from '{b.claim}'"
            )
        return out

    def falsifiable_tests(self) -> list[str]:
        return [h.disconfirming_test for h in self._record().ranked() if h.disconfirming_test]

    def what_would_change_my_mind(self, hyp_id: str) -> list[str]:
        hyp = self.active.get(hyp_id)
        if not hyp:
            return []
        reasons: list[str] = []
        if hyp.against:
            reasons.append(f"Existing contradicting evidence: {', '.join(hyp.against[:3])}")
        reasons.append(hyp.disconfirming_test or "No disconfirming test defined yet")
        if hyp.missing:
            reasons.append(f"Missing information: {', '.join(hyp.missing[:3])}")
        return reasons

    def resolve(self, hyp_id: str, status: str = "confirmed") -> Hypothesis | None:
        hyp = self.active.get(hyp_id)
        if hyp:
            hyp.status = status
            self.active.pop(hyp_id, None)
        return hyp

    def _record(self) -> HypothesisRecord:
        return HypothesisRecord(
            hypotheses=list(self.active.values()),
            distinguishing_evidence=self.distinguishing_evidence(),
        )

    def report(self) -> dict[str, Any]:
        return self._record().to_dict()

    def confidence(self) -> Confidence:
        record = self._record()
        best = record.best
        if not best:
            return Confidence.UNKNOWN
        margin = best.probability - (
            record.ranked()[1].probability if len(self.active) > 1 else 0.0
        )
        return Confidence.from_score(min(0.99, best.probability + margin * 0.3))


class HypothesisLab:
    """Experiment and verification planning built on hypotheses."""

    def __init__(self, engine: HypothesisEngine) -> None:
        self.engine = engine
        self.experiments: list[dict[str, Any]] = []

    def plan(self, claim: str) -> dict[str, Any]:
        plan = {
            "claim": claim,
            "verification_actions": self._actions_for(claim),
            "safe": True,
            "expected_duration": 30.0,
            "result": None,
        }
        self.experiments.append(plan)
        return plan

    @staticmethod
    def _actions_for(claim: str) -> list[str]:
        lowered = claim.lower()
        if any(w in lowered for w in ("disk", "memory", "cpu", "slow", "performance")):
            return [
                "Capture system telemetry snapshot",
                "Compare against baseline window",
                "Check for recent process or config change",
            ]
        if any(w in lowered for w in ("network", "connection", "offline", "timeout")):
            return [
                "Test connectivity to affected endpoint",
                "Inspect interface state and routes",
                "Review recent network errors in logs",
            ]
        if any(w in lowered for w in ("file", "missing", "deleted", "config")):
            return [
                "Verify path exists",
                "Check recent modification timestamps",
                "Search system logs for related operations",
            ]
        return [
            "Gather direct observation of the claim",
            "Search for contradicting evidence",
            "Record remaining unknowns",
        ]

    def record_result(self, index: int, result: Any) -> dict[str, Any]:
        if index < 0 or index >= len(self.experiments):
            raise IndexError("no such experiment")
        self.experiments[index]["result"] = result
        self.experiments[index]["completed_at"] = now()
        return self.experiments[index]

    def predict(self, hyp_id: str, prediction: str) -> HypothesisEngine:
        hyp = self.engine.active.get(hyp_id)
        if hyp:
            hyp.missing.append(f"Untested prediction: {prediction}")
        return self.engine

    def reality_check(self, statement: str) -> dict[str, Any]:
        """Flag claims that are unfalsifiable or overreaching."""
        lowered = statement.lower()
        red_flags: list[str] = []
        if any(w in lowered for w in ("always", "never", "definitely", "certainly")):
            red_flags.append("absolute claim — look for a counterexample")
        if any(w in lowered for w in ("obviously", "clearly", "of course")):
            red_flags.append("assumes the conclusion")
        if any(w in lowered for w in ("mind reading", "can tell you what", "i know you")):
            red_flags.append("unsupported mind-reading claim")
        return {
            "statement": statement,
            "falsifiable": not red_flags,
            "red_flags": red_flags,
            "verdict": "unsupported" if red_flags else "acceptable",
        }
