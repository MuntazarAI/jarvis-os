"""Contradiction detection, timeline reconstruction, gap analysis, question strategy."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..core.types import Contradiction, Confidence, now


NEGATION = re.compile(r"\b(not|no longer|never|stopped|disabled|removed|failed|cannot|can't)\b", re.I)
NUMBER = re.compile(r"\b(\d+(?:\.\d+)?)\s*(%|ms|s|mb|gb|kb|usd|inr|dollars?|seconds?|minutes?|hours?|days?)?\b", re.I)


@dataclass
class Claim:
    speaker: str
    claim: str
    timestamp: float = field(default_factory=now)
    context: str = ""
    evidence_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "speaker": self.speaker,
            "claim": self.claim,
            "timestamp": self.timestamp,
            "context": self.context,
            "evidence_ids": self.evidence_ids,
        }


class ContradictionDetector:
    """Reports conflicts precisely. Never labels a contradiction as a lie."""

    ALTERNATIVE_CAUSES = [
        "memory error",
        "misunderstanding",
        "typo",
        "missing context",
        "different interpretation",
        "genuine contradiction",
    ]

    def __init__(self) -> None:
        self.contradictions: list[Contradiction] = []

    def detect(self, a: Claim, b: Claim) -> Contradiction | None:
        if a.timestamp == b.timestamp and a.claim == b.claim:
            return None
        kind = self._classify(a.claim, b.claim, a, b)
        if not kind:
            return None
        ctr = Contradiction(
            source_a=f"{a.speaker}@{a.timestamp:.0f}",
            source_b=f"{b.speaker}@{b.timestamp:.0f}",
            statement_a=a.claim,
            statement_b=b.claim,
            kind=kind,
            confidence=self._confidence(a, b, kind),
        )
        self.contradictions.append(ctr)
        return ctr

    @staticmethod
    def _classify(text_a: str, text_b: str, a: Claim, b: Claim) -> str:
        low_a, low_b = text_a.lower(), text_b.lower()
        neg_a, neg_b = bool(NEGATION.search(low_a)), bool(NEGATION.search(low_b))
        overlap = set(re.findall(r"[a-z]{4,}", low_a)) & set(re.findall(r"[a-z]{4,}", low_b))
        if neg_a != neg_b and overlap:
            return "direct"
        nums_a = NUMBER.findall(text_a)
        nums_b = NUMBER.findall(text_b)
        if nums_a and nums_b and [n[0] for n in nums_a] != [n[0] for n in nums_b] and overlap:
            return "numerical"
        if overlap and ("is in" in low_a or "at " in low_a) and ("is in" in low_b or "at " in low_b):
            return "location"
        if abs(a.timestamp - b.timestamp) > 0 and overlap and ("because" in low_a or "because" in low_b):
            return "changing_explanation"
        return ""

    @staticmethod
    def _confidence(a: Claim, b: Claim, kind: str) -> float:
        base = {"direct": 0.75, "numerical": 0.7, "location": 0.6, "changing_explanation": 0.5}.get(kind, 0.6)
        if a.speaker == b.speaker:
            base -= 0.15
        return max(0.1, round(base, 3))

    def alternative_causes(self, ctr: Contradiction) -> list[str]:
        causes = [c for c in self.ALTERNATIVE_CAUSES if c != "genuine contradiction"]
        if ctr.kind == "numerical":
            causes.insert(0, "rounding or unit mismatch")
        if ctr.kind == "changing_explanation":
            causes.insert(0, "new information became available")
        return causes

    def smallest_verification(self, ctr: Contradiction) -> str:
        subject = " ".join(
            sorted(set(re.findall(r"[a-z]{4,}", ctr.statement_a.lower()))
                   & set(re.findall(r"[a-z]{4,}", ctr.statement_b.lower())))
        ) or "the conflicting detail"
        return f"Ask one confirming question about: {subject}"

    def report(self, ctr: Contradiction) -> str:
        return (
            f"CONFLICT ({ctr.kind}, confidence {ctr.confidence})\n"
            f"  {ctr.source_a}: {ctr.statement_a}\n"
            f"  {ctr.source_b}: {ctr.statement_b}\n"
            f"  Possible causes: {', '.join(self.alternative_causes(ctr))}\n"
            f"  Smallest verification: {self.smallest_verification(ctr)}\n"
            "  Note: this is a reported conflict, not a conclusion about honesty."
        )


@dataclass
class TimelineEvent:
    timestamp: float
    event: str
    source: str = "unknown"
    confidence: float = 0.7
    location: str = ""
    participants: list[str] = field(default_factory=list)
    uncertainty: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "time_range": [self.timestamp - self.uncertainty, self.timestamp + self.uncertainty],
            "event": self.event,
            "source": self.source,
            "confidence": self.confidence,
            "location": self.location,
            "participants": self.participants,
        }


class Timeline:
    """Event reconstruction preserving uncertain timestamps as ranges."""

    def __init__(self, tolerance: float = 1.0) -> None:
        self.tolerance = tolerance
        self.events: list[TimelineEvent] = []

    def add(self, event: str, timestamp: float, source: str = "unknown",
            confidence: float = 0.7, location: str = "",
            participants: list[str] | None = None, uncertainty: float = 0.0) -> TimelineEvent:
        te = TimelineEvent(
            timestamp=timestamp, event=event, source=source, confidence=confidence,
            location=location, participants=participants or [], uncertainty=uncertainty,
        )
        self.events.append(te)
        self.events.sort(key=lambda e: e.timestamp)
        return te

    def anomalies(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for prev, nxt in zip(self.events, self.events[1:]):
            delta = nxt.timestamp - prev.timestamp
            if delta < -self.tolerance:
                out.append({"kind": "impossible_sequence", "a": prev.event, "b": nxt.event, "delta": delta})
            elif delta > 3600:
                out.append({"kind": "missing_interval", "a": prev.event, "b": nxt.event, "seconds": delta})
        return out

    def overlaps(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for i, a in enumerate(self.events):
            for b in self.events[i + 1:]:
                if a.timestamp > b.timestamp + self.tolerance:
                    break
                if abs(a.timestamp - b.timestamp) <= self.tolerance and a.event != b.event:
                    out.append({"a": a.event, "b": b.event, "at": a.timestamp})
        return out

    def render(self) -> str:
        return "\n".join(
            f"  {e.timestamp:.0f} — {e.event} (source: {e.source}, confidence: {e.confidence})"
            for e in self.events
        )

    def window(self, start: float, end: float) -> list[TimelineEvent]:
        return [e for e in self.events if start <= e.timestamp <= end]

    def most_certain(self, n: int = 3) -> list[TimelineEvent]:
        return sorted(self.events, key=lambda e: -e.confidence)[:n]

    def weakest_link(self) -> TimelineEvent | None:
        return min(self.events, key=lambda e: e.confidence) if self.events else None


class InformationGapDetector:
    """Identifies what is missing and how it could change the conclusion."""

    STATES = ("known", "unknown", "uncertain", "conflicting", "needs_verification")

    def __init__(self) -> None:
        self.states: dict[str, str] = {}

    def mark(self, item: str, state: str) -> None:
        if state not in self.STATES:
            raise ValueError(f"state must be one of {self.STATES}")
        self.states[item] = state

    def analyze(self, decision: str, available: list[str], required: list[str],
                impact: dict[str, float] | None = None) -> dict[str, Any]:
        impact = impact or {}
        missing = [r for r in required if r not in available]
        prioritized = sorted(missing, key=lambda m: -impact.get(m, 0.5))
        return {
            "decision": decision,
            "required_to_decide": required,
            "available": available,
            "missing": missing,
            "high_impact_unknowns": prioritized[:3],
            "could_change_conclusion": bool(prioritized),
            "note": "Gaps are stated explicitly. Gaps are never filled with invented facts.",
        }

    def known(self) -> list[str]:
        return [k for k, v in self.states.items() if v == "known"]

    def unknown(self) -> list[str]:
        return [k for k, v in self.states.items() if v in ("unknown", "needs_verification")]

    def conflicting(self) -> list[str]:
        return [k for k, v in self.states.items() if v == "conflicting"]


class QuestionStrategy:
    """Generates the minimum question that resolves uncertainty."""

    def __init__(self) -> None:
        self.asked: list[dict[str, Any]] = []

    def generate(
        self,
        goal: str,
        required: list[str],
        known: list[str],
        unknown_variable: str = "",
    ) -> dict[str, Any]:
        var = unknown_variable or (required[0] if required else "the missing detail")
        qtype = self._classify(var)
        question = self._phrase(var, goal)
        plan = {
            "goal": goal,
            "information_required": required,
            "known": known,
            "unknown_variable": var,
            "best_question": question,
            "question_type": qtype,
            "expected_answers": ["a concrete value", "an explicit 'unknown'", "a pointer to where to look"],
            "safeguards": [
                "neutral wording",
                "no coercion",
                "single question only",
                "does not presuppose the answer",
            ],
        }
        self.asked.append(plan)
        return plan

    @staticmethod
    def _classify(variable: str) -> str:
        v = variable.lower()
        if any(w in v for w in ("time", "when", "date", "deadline")):
            return "timeline"
        if any(w in v for w in ("who", "person", "author")):
            return "evidence"
        if "verify" in v or "confirm" in v:
            return "verification"
        if any(w in v for w in ("why", "cause", "reason")):
            return "alternative_explanation"
        return "clarifying"

    @staticmethod
    def _phrase(variable: str, goal: str) -> str:
        cleaned = variable.strip().rstrip("?")
        return f"Could you tell me about {cleaned} so I can {goal}?"

    def answered(self, question: str, answer: str) -> None:
        for plan in self.asked:
            if plan["best_question"] == question:
                plan["answer"] = answer
                plan["answered_at"] = now()

    def pending(self) -> list[dict[str, Any]]:
        return [p for p in self.asked if "answer" not in p]


def deception_guard() -> dict[str, Any]:
    """The standing limitations on any deception analysis."""
    return {
        "limitations": [
            "Body language alone cannot reliably determine whether someone is lying.",
            "A single behavior is not proof of deception.",
            "Stress or discomfort is not equivalent to dishonesty.",
        ],
        "allowed_phrases": [
            "evidence consistent with X",
            "evidence inconsistent with Y",
            "the available evidence is insufficient",
        ],
        "prohibited_claims": [
            "person is lying",
            "person is deceptive",
            "person is faking",
            "I can read your mind",
        ],
    }


def safe_deception_analysis(
    internal_consistency: float,
    external_consistency: float,
    contradictions: list[Contradiction],
) -> dict[str, Any]:
    """Analyze consistency without inferring dishonesty."""
    guard = deception_guard()
    findings: list[str] = []
    if internal_consistency < 0.7:
        findings.append("evidence inconsistent with internal consistency")
    if external_consistency < 0.7:
        findings.append("evidence inconsistent with external sources")
    for c in contradictions:
        findings.append(f"conflict between {c.source_a} and {c.source_b}: {c.kind}")
    if not findings:
        return {
            "verdict": "the available evidence is insufficient to indicate any inconsistency",
            "findings": [],
            "confidence": Confidence.LOW.value,
            "limitations": guard["limitations"],
            "alternative_explanations": [
                "memory error", "stress or fatigue", "changing circumstances",
                "different interpretation", "incomplete context",
            ],
        }
    return {
        "verdict": "; ".join(findings),
        "findings": findings,
        "confidence": Confidence.MEDIUM.value if len(findings) > 1 else Confidence.LOW.value,
        "limitations": guard["limitations"],
        "alternative_explanations": [
            "memory error", "misunderstanding", "typo", "missing context",
            "different interpretation", "stress or fatigue", "environment change",
        ],
        "note": "This describes evidence inconsistency only. No conclusion about honesty.",
    }
