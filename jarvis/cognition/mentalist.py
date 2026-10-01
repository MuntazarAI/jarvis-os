"""Mentalist mode: evidence-gated analysis with a strict display contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core.types import CognitiveReport, Confidence, Contradiction, Evidence, Hypothesis, Observation
from ..inference.analysis import (
    Claim,
    ContradictionDetector,
    InformationGapDetector,
    QuestionStrategy,
    Timeline,
    safe_deception_analysis,
)
from ..inference.evidence import EvidenceEngine
from ..inference.hypothesis import HypothesisEngine
from ..inference.reasoning import (
    AbductiveReasoner,
    DeductiveReasoner,
    InductiveReasoner,
    MetaReasoner,
    RedTeamReasoner,
)


@dataclass
class Baseline:
    speech: dict[str, Any] = field(default_factory=dict)
    behavior: dict[str, Any] = field(default_factory=dict)
    environment: dict[str, Any] = field(default_factory=dict)
    conversation: dict[str, Any] = field(default_factory=dict)
    samples: int = 0

    def update(self, sample: dict[str, Any]) -> None:
        for key in ("speech", "behavior", "environment", "conversation"):
            for attr, value in sample.get(key, {}).items():
                bucket = getattr(self, key).setdefault(attr, {})
                bucket[str(value)] = bucket.get(str(value), 0) + 1
        self.samples += 1

    def deviations(self, sample: dict[str, Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if self.samples < 2:
            return [{"note": "insufficient baseline samples — no deviation call made"}]
        for key in ("speech", "behavior", "environment", "conversation"):
            for attr, value in sample.get(key, {}).items():
                bucket = getattr(self, key).get(attr, {})
                if not bucket:
                    continue
                common = max(bucket, key=bucket.get)
                if str(value) != common:
                    out.append({
                        "dimension": f"{key}.{attr}",
                        "baseline": common,
                        "observed": value,
                        "note": "deviation is not deception — corroboration required",
                    })
        return out


class MentalistMode:
    """Observe → baseline → memory → timeline → hypotheses → verify.

    Prohibited: unsupported conclusions as facts, mind-reading claims,
    intent inference without evidence.
    """

    DISPLAY_SECTIONS = (
        "Observations", "Evidence", "Hypotheses", "Alternatives",
        "Unknown", "Confidence", "Next test",
    )

    def __init__(self) -> None:
        self.evidence = EvidenceEngine()
        self.hypotheses = HypothesisEngine()
        self.contradictions = ContradictionDetector()
        self.timeline = Timeline()
        self.gaps = InformationGapDetector()
        self.questions = QuestionStrategy()
        self.baseline = Baseline()
        self.red_team = RedTeamReasoner()
        self.meta = MetaReasoner()
        self._observations: list[Observation] = []

    # -- operating sequence ------------------------------------------------
    def observe(self, content: str, **kw: Any) -> Observation:
        obs = Observation(kind=kw.pop("kind", "note"), content=content, **kw)
        self._observations.append(obs)
        return obs

    def record_facts(self, observations: list[Observation]) -> list[Evidence]:
        out = []
        for obs in observations:
            out.append(self.evidence.from_observation(obs))
        return out

    def establish_baseline(self, samples: list[dict[str, Any]]) -> Baseline:
        for sample in samples:
            self.baseline.update(sample)
        return self.baseline

    def check_deviation(self, sample: dict[str, Any]) -> list[dict[str, Any]]:
        return self.baseline.deviations(sample)

    def build_timeline(self, events: list[tuple[str, float, str]]) -> Timeline:
        for text, ts, source in events:
            self.timeline.add(text, ts, source)
        return self.timeline

    def hypothesize(self, claims: list[str]) -> list[Hypothesis]:
        return [self.hypotheses.propose(c) for c in claims]

    def find_contradictions(self, claims: list[Claim]) -> list[Contradiction]:
        found: list[Contradiction] = []
        for i, a in enumerate(claims):
            for b in claims[i + 1:]:
                ctr = self.contradictions.detect(a, b)
                if ctr:
                    found.append(ctr)
        return found

    def ask(self, goal: str, required: list[str], known: list[str]) -> dict[str, Any]:
        return self.questions.generate(goal, required, known)

    def verify(self, statement: str) -> dict[str, Any]:
        from ..inference.hypothesis import HypothesisLab
        return HypothesisLab(self.hypotheses).reality_check(statement)

    def update(self, hyp_id: str, supporting: str = "", against: str = "") -> None:
        if supporting:
            self.hypotheses.support(hyp_id, supporting)
        if against:
            self.hypotheses.contradict(hyp_id, against)

    # -- reasoning helpers -------------------------------------------------
    def deduce(self, observation: str, evidence: list[str]) -> Any:
        return DeductiveReasoner().deduce(observation, evidence)

    def induce(self, observations: list[str]) -> Any:
        return InductiveReasoner().induce(observations)

    def abduce(self, evidence: list[str], candidates: list[str]) -> Any:
        return AbductiveReasoner().best_explanation(evidence, candidates)

    def red_team_review(self, hypothesis: str, confidence: Confidence,
                        evidence: list[str], alternatives: list[str]) -> Any:
        return self.red_team.review(hypothesis, confidence, evidence, alternatives)

    def deception_check(self, internal: float, external: float,
                        contradictions: list[Contradiction]) -> dict[str, Any]:
        return safe_deception_analysis(internal, external, contradictions)

    # -- report --------------------------------------------------------------
    def report(self, unknowns: list[str] | None = None, next_test: str = "") -> CognitiveReport:
        hyps = self.hypotheses.report()
        best_prob = hyps.get("best_probability", 0.0)
        return CognitiveReport(
            observations=list(self._observations),
            evidence=[i.evidence for i in self.evidence.items.values()],
            hypotheses=self.hypotheses._record().ranked(),
            contradictions=list(self.contradictions.contradictions),
            unknowns=unknowns if unknowns is not None else self.gaps.unknown(),
            alternatives=[h.claim for h in self.hypotheses._record().ranked()[1:]],
            confidence=Confidence.from_score(best_prob),
            next_test=next_test or self._suggest_test(),
            baseline={"samples": self.baseline.samples},
            deviations=[],
        )

    def _suggest_test(self) -> str:
        dist = self.hypotheses.distinguishing_evidence()
        if dist:
            return dist[0]
        pending = self.questions.pending()
        if pending:
            return pending[0]["best_question"]
        return "Collect one more direct observation before concluding."

    def render(self, **kw: Any) -> str:
        lines = ["MENTALIST MODE — evidence-gated analysis"]
        lines.append(self.report(**kw).render())
        lines.append("Safeguards: no mind-reading claims; deviations are not deception;")
        lines.append("conflicts are reported, never labeled as lies.")
        return "\n".join(lines)
