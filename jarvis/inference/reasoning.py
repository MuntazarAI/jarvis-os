"""Deductive, inductive, abductive and red-team reasoning."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from ..core.types import Confidence, now


@dataclass
class Deduction:
    observation: str
    hypotheses: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    eliminated: dict[str, str] = field(default_factory=dict)
    remaining: list[str] = field(default_factory=list)
    confidence: Confidence = Confidence.UNKNOWN
    premises: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation": self.observation,
            "hypotheses": self.hypotheses,
            "evidence": self.evidence,
            "eliminated": self.eliminated,
            "remaining": self.remaining,
            "confidence": self.confidence.value,
            "premises": self.premises,
        }


class DeductiveReasoner:
    """Explicit premises, elimination only with distinguishing evidence."""

    CAUSES = {
        "wet": ["rain", "water spill", "cleaning", "condensation"],
        "cold": ["air conditioning", "window open", "power loss", "low heating"],
        "slow": ["cpu saturation", "disk bottleneck", "network latency", "memory pressure"],
        "error": ["bad input", "missing dependency", "permission denied", "race condition"],
    }

    def deduce(self, observation: str, evidence: list[str] | None = None,
               hypotheses: list[str] | None = None) -> Deduction:
        evidence = evidence or []
        lowered = observation.lower()
        key = next((k for k in self.CAUSES if k in lowered), None)
        candidates = list(hypotheses or (self.CAUSES.get(key, []) if key else []))
        result = Deduction(
            observation=observation,
            hypotheses=candidates,
            evidence=evidence,
            premises=[f"Observation: {observation}"] + [f"Evidence: {e}" for e in evidence],
        )
        ev_low = " | ".join(evidence).lower()
        for candidate in candidates:
            verdict, why = self._test(candidate, key, ev_low)
            if verdict:
                result.eliminated[candidate] = why
        result.remaining = [c for c in candidates if c not in result.eliminated]
        total = max(1, len(candidates))
        result.confidence = Confidence.from_score(len(result.remaining) / total)
        return result

    @staticmethod
    def _test(candidate: str, key: str | None, evidence: str) -> tuple[bool, str]:
        markers = {
            "rain": ("weather", "forecast", "outdoor", "umbrella"),
            "water spill": ("near", "kitchen", "bathroom", "leak", "mop"),
            "cleaning": ("mop", "sponge", "spray", "wiped"),
            "condensation": ("cold", "fridge", "humid", "morning", "glass"),
            "air conditioning": ("ac", "thermostat", "cool"),
            "window open": ("window", "draught", "draft", "curtain"),
            "cpu saturation": ("cpu", "load", "top", "100%"),
            "disk bottleneck": ("disk", "iowait", "disk", "full"),
            "network latency": ("network", "ping", "latency", "packet"),
            "memory pressure": ("memory", "oom", "swap", "ram"),
            "bad input": ("validation", "invalid", "malformed", "400"),
            "missing dependency": ("import", "module", "not found", "install"),
            "permission denied": ("permission", "denied", "eacces", "sudo"),
            "race condition": ("race", "concurrent", "lock", "thread"),
        }.get(candidate, (candidate.split()[0],))
        hits = [m for m in markers if m in evidence]
        if not hits:
            return False, ""
        if key == "wet" and candidate == "rain" and "indoor" in evidence:
            return True, "indoor location conflicts with rain"
        return False, ""

    def premises_explicit(self, deduction: Deduction) -> list[str]:
        return deduction.premises


@dataclass
class Induction:
    observations: list[str] = field(default_factory=list)
    pattern: str = ""
    hypothesis: str = ""
    sample_size: int = 0
    context_diversity: int = 0
    counterexamples: list[str] = field(default_factory=list)
    confidence: Confidence = Confidence.UNKNOWN
    caveats: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "observations": self.observations,
            "pattern": self.pattern,
            "hypothesis": self.hypothesis,
            "sample_size": self.sample_size,
            "context_diversity": self.context_diversity,
            "counterexamples": self.counterexamples,
            "confidence": self.confidence.value,
            "caveats": self.caveats,
        }


class InductiveReasoner:
    """Generalizes from recurrence while controlling for sample size and context."""

    def induce(self, observations: list[str]) -> Induction:
        out = Induction(observations=list(observations), sample_size=len(observations))
        if len(observations) < 2:
            out.caveats.append("fewer than two observations: no pattern can be established")
            return out
        tokens = [set(re.findall(r"[a-z]{3,}", o.lower())) for o in observations]
        common = set.intersection(*tokens) if tokens else set()
        out.pattern = " ".join(sorted(common)) if common else ""
        if not out.pattern:
            out.caveats.append("no shared tokens across observations")
            return out
        contexts = {self._context(o) for o in observations}
        out.context_diversity = len(contexts)
        out.hypothesis = f"Pattern observed across {len(observations)} instances: {out.pattern}"
        freq = Counter(t for ts in tokens for t in ts)
        top = {t for t, _ in freq.most_common(3)}
        out.counterexamples = [
            o for o, ts in zip(observations, tokens) if not (top & ts)
        ]
        score = min(1.0, len(observations) / 6.0)
        score *= min(1.0, len(contexts) / 3.0)
        if len(observations) < 3:
            score *= 0.6
            out.caveats.append("small sample")
        if out.counterexamples:
            score *= 0.7
            out.caveats.append("counterexamples present")
        out.confidence = Confidence.from_score(score)
        return out

    @staticmethod
    def _context(text: str) -> str:
        lowered = text.lower()
        for marker in ("morning", "afternoon", "evening", "night"):
            if marker in lowered:
                return marker
        for marker in ("monday", "tuesday", "wednesday", "thursday", "friday", "weekend"):
            if marker in lowered:
                return marker
        return "unspecified"


@dataclass
class Abduction:
    candidates: list[str] = field(default_factory=list)
    best: str = ""
    coverage: float = 0.0
    simplicity: float = 0.0
    assumptions: list[str] = field(default_factory=list)
    alternatives_retained: list[str] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)
    confidence: Confidence = Confidence.LOW

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidates": self.candidates,
            "best": self.best,
            "coverage": round(self.coverage, 4),
            "simplicity": round(self.simplicity, 4),
            "assumptions": self.assumptions,
            "alternatives_retained": self.alternatives_retained,
            "missing_evidence": self.missing_evidence,
            "confidence": self.confidence.value,
        }


class AbductiveReasoner:
    """Best explanation search. Best is not proven."""

    def best_explanation(self, evidence: list[str], candidates: list[str]) -> Abduction:
        out = Abduction(candidates=list(candidates))
        if not candidates:
            return out
        ev_tokens = [set(re.findall(r"[a-z]{3,}", e.lower())) for e in evidence]
        scores: list[tuple[str, float, float]] = []
        for cand in candidates:
            cand_tokens = set(re.findall(r"[a-z]{3,}", cand.lower()))
            if not cand_tokens:
                scores.append((cand, 0.0, 0.0))
                continue
            coverage = (
                sum(len(cand_tokens & t) / len(cand_tokens) for t in ev_tokens) / len(ev_tokens)
                if ev_tokens
                else 0.0
            )
            simplicity = 1.0 / (1.0 + math.log1p(len(cand_tokens)))
            scores.append((cand, coverage, simplicity))
        scores.sort(key=lambda s: -(0.75 * s[1] + 0.25 * s[2]))
        out.best = scores[0][0]
        out.coverage = scores[0][1]
        out.simplicity = scores[0][2]
        out.alternatives_retained = [s[0] for s in scores[1:]]
        out.assumptions = [
            f"assumes '{out.best}' is the intended referent of the evidence"
        ]
        out.missing_evidence = self._missing(evidence, candidates)
        gap = scores[0][1] - (scores[1][1] if len(scores) > 1 else 0.0)
        out.confidence = Confidence.from_score(min(0.95, scores[0][1] + gap * 0.4))
        return out

    @staticmethod
    def _missing(evidence: list[str], candidates: list[str]) -> list[str]:
        joined = " ".join(evidence).lower()
        out: list[str] = []
        for cand in candidates:
            tokens = set(re.findall(r"[a-z]{4,}", cand.lower()))
            if tokens and not (tokens & set(re.findall(r"[a-z]{4,}", joined))):
                out.append(f"no evidence referencing '{cand}'")
        return out


@dataclass
class RedTeamReview:
    challenge_questions: list[str] = field(default_factory=list)
    strongest_counter: str = ""
    disconfirming_evidence: list[str] = field(default_factory=list)
    revised_hypothesis: str = ""
    original_confidence: Confidence = Confidence.UNKNOWN
    revised_confidence: Confidence = Confidence.UNKNOWN
    weak_assumptions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "challenge_questions": self.challenge_questions,
            "strongest_counter": self.strongest_counter,
            "disconfirming_evidence": self.disconfirming_evidence,
            "revised_hypothesis": self.revised_hypothesis,
            "original_confidence": self.original_confidence.value,
            "revised_confidence": self.revised_confidence.value,
            "weak_assumptions": self.weak_assumptions,
        }


class RedTeamReasoner:
    """Adversarial review of JARVIS's own conclusions."""

    CHALLENGES = [
        "What if I am wrong?",
        "What evidence contradicts this?",
        "What alternative explanation exists?",
        "What information is missing?",
        "Am I confusing correlation with causation?",
        "Am I relying on an unreliable assumption?",
        "What evidence would change this conclusion?",
    ]

    def review(self, hypothesis: str, confidence: Confidence,
               evidence: list[str], alternatives: list[str]) -> RedTeamReview:
        review = RedTeamReview(
            challenge_questions=list(self.CHALLENGES),
            original_confidence=confidence,
            revised_hypothesis=hypothesis,
            revised_confidence=confidence,
        )
        if alternatives:
            review.strongest_counter = alternatives[0]
            review.revised_confidence = Confidence.from_score(
                max(0.05, confidence.numeric * 0.7)
            )
        if len(evidence) < 2:
            review.weak_assumptions.append("conclusion rests on a single evidence item")
            review.revised_confidence = Confidence.from_score(
                min(0.4, confidence.numeric * 0.6)
            )
        low_rel = [e for e in evidence if "assume" in e.lower() or "probably" in e.lower()]
        for item in low_rel:
            review.weak_assumptions.append(f"soft evidence: {item}")
        review.disconfirming_evidence = self._seek_disconfirming(hypothesis, evidence)
        if review.disconfirming_evidence:
            review.revised_confidence = Confidence.from_score(
                max(0.05, review.revised_confidence.numeric * 0.8)
            )
        return review

    @staticmethod
    def _seek_disconfirming(hypothesis: str, evidence: list[str]) -> list[str]:
        out: list[str] = []
        for e in evidence:
            low = e.lower()
            if any(w in low for w in ("except", "unless", "however", "but not", "failed once")):
                out.append(e)
        return out

    def counterfactual(self, statement: str, condition: str) -> dict[str, Any]:
        return {
            "statement": statement,
            "counterfactual": f"If {condition}, then {statement}",
            "note": "Counterfactuals are unverified reasoning aids, not predictions.",
        }


class MetaReasoner:
    """Assumption, bias and confidence self-audit."""

    BIASES = {
        "confirmation": ["confirms", "as expected", "just as i thought"],
        "anchoring": ["first", "initially", "at first"],
        "overconfidence": ["definitely", "certainly", "obviously", "always", "never"],
        "underconfidence": ["maybe", "possibly", "i think", "not sure"],
    }

    def audit(self, text: str, confidence: Confidence, assumptions: list[str]) -> dict[str, Any]:
        lowered = text.lower()
        detected: list[str] = []
        for bias, markers in self.BIASES.items():
            hits = [m for m in markers if m in lowered]
            if hits:
                detected.append(f"{bias}: {', '.join(hits)}")
        if confidence == Confidence.HIGH and len(assumptions) > 3:
            detected.append("high confidence with many unexamined assumptions")
        if confidence == Confidence.LOW and not assumptions:
            detected.append("low confidence with no stated assumptions — under-reasoned")
        return {
            "detected_biases": detected,
            "assumptions": assumptions,
            "unknowns": [],
            "confidence": confidence.value,
            "questions": [
                "Why do I believe this?",
                "What am I assuming?",
                "What don't I know?",
                "What could I be missing?",
                "What would change my conclusion?",
            ],
            "reviewed_at": now(),
        }

    def record_unknown(self, audit: dict[str, Any], unknown: str) -> dict[str, Any]:
        audit["unknowns"].append(unknown)
        return audit
