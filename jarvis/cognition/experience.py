"""Experience contract, evidence model, and durable store (4.4).

An Experience is one completed cognitive episode: what was observed,
believed, predicted, decided, done, and what actually happened —
plus whether the prediction was right. Records are immutable and
append-only; corrections are new evaluation records, never edits.

Evidence is always a *reference* (id + kind + digest) to persisted
data, never a copy of raw media.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

EXPERIENCES_FILENAME = "cognitive-experiences.jsonl"
MAX_LINE_BYTES = 64 * 1024
MAX_INDEX_ENTRIES = 2000
MAX_EVIDENCE_REFS = 20
SCHEMA_VERSION = 1


class OutcomeState(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    NO_ACTION = "no_action"
    NO_DECISION = "no_decision"
    UNKNOWN = "unknown"


class PredictionVerdict(str, Enum):
    CORRECT = "correct"
    INCORRECT = "incorrect"
    PARTIAL = "partial"
    UNRESOLVED = "unresolved"


class ExperienceError(ValueError):
    """Malformed experience or store misuse."""


def _utcnow() -> float:
    return time.time()


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


@dataclass
class EvidenceRef:
    """Pointer to persisted evidence. No payloads, no media."""

    kind: str  # observation|world|memory|prediction|verification|action|event
    ref_id: str
    digest: str = ""
    note: str = ""

    def __post_init__(self) -> None:
        if not self.kind or not self.ref_id:
            raise ExperienceError("evidence needs kind and ref_id")
        self.ref_id = str(self.ref_id)[:128]
        self.digest = str(self.digest)[:128]
        self.note = str(self.note)[:200]


@dataclass
class PredictionEvaluation:
    prediction_id: str = ""
    experience_id: str = ""
    expected: str = ""
    actual: str = ""
    error_type: str = ""  # mismatch|missing_evidence|ambiguous|none
    error_magnitude: float | None = None  # 0..1 when numeric, else None
    verdict: PredictionVerdict = PredictionVerdict.UNRESOLVED
    confidence_before: float | None = None
    confidence_after: float | None = None
    evidence_refs: list[str] = field(default_factory=list)
    evaluated_at: float = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        if isinstance(self.verdict, str):
            self.verdict = PredictionVerdict(self.verdict)
        if self.error_magnitude is not None:
            magnitude = float(self.error_magnitude)
            if not 0.0 <= magnitude <= 1.0:
                raise ExperienceError("error_magnitude must be 0..1")
            self.error_magnitude = magnitude

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["verdict"] = self.verdict.value
        return data


@dataclass
class OutcomeEvaluation:
    """Structured answer: did prediction/action/verification agree?"""

    experience_id: str = ""
    predicted_state_occurred: bool | None = None  # None == not evaluable
    action_succeeded: bool | None = None
    ambiguous: bool = False
    enough_evidence: bool = False
    prediction_error: str = ""  # none|mismatch|missing_evidence|ambiguous
    should_learn: bool = False
    reasons: list[str] = field(default_factory=list)
    evaluated_at: float = field(default_factory=_utcnow)


@dataclass
class Experience:
    experience_id: str = field(default_factory=lambda: _new_id("exp"))
    cycle_id: str = ""
    timestamp: float = field(default_factory=_utcnow)
    duration_ms: float = 0.0
    observation_refs: list[EvidenceRef] = field(default_factory=list)
    context_ref: str = ""
    belief_refs: list[str] = field(default_factory=list)
    prediction_refs: list[str] = field(default_factory=list)
    decision_ref: str = ""
    action_ref: str = ""
    verification_ref: str = ""
    outcome: OutcomeState = OutcomeState.UNKNOWN
    prediction_error: str = ""
    confidence: float = 0.0
    provenance: dict[str, Any] = field(default_factory=dict)
    privacy_class: str = "local"
    evaluations: list[PredictionEvaluation] = field(default_factory=list)
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if isinstance(self.outcome, str):
            try:
                self.outcome = OutcomeState(self.outcome)
            except ValueError:
                raise ExperienceError(f"invalid outcome: {self.outcome!r}")
        if not isinstance(self.timestamp, (int, float)) \
                or self.timestamp <= 0:
            raise ExperienceError("malformed experience timestamp")
        self.confidence = _clamp_confidence(self.confidence)
        if len(self.observation_refs) > MAX_EVIDENCE_REFS:
            raise ExperienceError("too many observation refs")
        for ref in self.observation_refs:
            if isinstance(ref, dict):
                ref = EvidenceRef(**{k: ref[k] for k in
                                     ("kind", "ref_id")
                                     if k in ref})
            if not isinstance(ref, EvidenceRef):
                raise ExperienceError("observation_refs must be EvidenceRef")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["outcome"] = self.outcome.value
        data["observation_refs"] = [
            asdict(r) if isinstance(r, EvidenceRef) else r
            for r in self.observation_refs]
        data["evaluations"] = [
            e.to_dict() if isinstance(e, PredictionEvaluation) else e
            for e in self.evaluations]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Experience":
        if not isinstance(data, dict):
            raise ExperienceError("experience must be an object")
        known = set(cls.__dataclass_fields__)
        clean = {k: v for k, v in data.items() if k in known}
        refs = []
        for item in clean.get("observation_refs", []) or []:
            if isinstance(item, dict):
                try:
                    refs.append(EvidenceRef(
                        kind=str(item.get("kind", "")),
                        ref_id=str(item.get("ref_id", "")),
                        digest=str(item.get("digest", "")),
                        note=str(item.get("note", ""))))
                except ExperienceError:
                    continue
        clean["observation_refs"] = refs
        evaluations = []
        for item in clean.get("evaluations", []) or []:
            if isinstance(item, dict):
                try:
                    evaluations.append(PredictionEvaluation(
                        **{k: v for k, v in item.items()
                           if k in PredictionEvaluation.__dataclass_fields__}))
                except (ExperienceError, TypeError, ValueError):
                    continue
        clean["evaluations"] = evaluations
        return cls(**clean)


def _clamp_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        raise ExperienceError(f"invalid confidence: {value!r}")
    if confidence != confidence:  # NaN
        raise ExperienceError("confidence must not be NaN")
    if confidence in (float("inf"), float("-inf")):
        raise ExperienceError("confidence must be finite")
    if not 0.0 <= confidence <= 1.0:
        raise ExperienceError(f"confidence out of range: {value!r}")
    return confidence


class OutcomeEvaluator:
    """Deterministic outcome evaluation. UNKNOWN stays UNKNOWN."""

    @staticmethod
    def evaluate(*, prediction_made: bool, expected: str = "",
                 actual: str = "", action_ok: bool | None = None,
                 verification: str = "UNKNOWN",
                 evidence_count: int = 0) -> OutcomeEvaluation:
        reasons: list[str] = []
        if verification == "VERIFIED":
            action_succeeded: bool | None = True
            reasons.append("action verified against evidence")
        elif verification == "FAILED":
            action_succeeded = False
            reasons.append("verification failed")
        elif verification == "PARTIALLY_VERIFIED":
            action_succeeded = None
            reasons.append("partial verification: ambiguous")
        else:
            action_succeeded = None
            reasons.append("no verification: outcome unknown")
        if not prediction_made:
            predicted_state_occurred = None
            prediction_error = "missing_evidence"
            reasons.append("no prediction to evaluate")
        elif not expected or not actual:
            predicted_state_occurred = None
            prediction_error = "missing_evidence"
            reasons.append("expected/actual incomplete")
        elif expected.strip().lower() == actual.strip().lower():
            predicted_state_occurred = True
            prediction_error = "none"
            reasons.append("expected state observed")
        elif expected.lower() in actual.lower() or \
                actual.lower() in expected.lower():
            predicted_state_occurred = None
            prediction_error = "ambiguous"
            reasons.append("partial textual overlap: ambiguous")
        else:
            predicted_state_occurred = False
            prediction_error = "mismatch"
            reasons.append("expected state did not occur")
        enough_evidence = evidence_count >= 2
        if not enough_evidence:
            reasons.append("fewer than 2 evidence refs")
        ambiguous = (predicted_state_occurred is None
                     or action_succeeded is None)
        should_learn = enough_evidence and (
            predicted_state_occurred is False
            or action_succeeded is False
            or (predicted_state_occurred is True
                and action_succeeded is True))
        return OutcomeEvaluation(
            predicted_state_occurred=predicted_state_occurred,
            action_succeeded=action_succeeded,
            ambiguous=ambiguous,
            enough_evidence=enough_evidence,
            prediction_error=prediction_error,
            should_learn=should_learn,
            reasons=reasons)


class ExperienceStore:
    """Append-only durable experiences. Immutable history, bounded."""

    def __init__(self, home: str | Path | None,
                 max_index: int = 2000) -> None:
        self.home = Path(home) if home else None
        self.max_index = max_index
        self._index: dict[str, dict[str, Any]] = {}
        self._by_cycle: dict[str, str] = {}

    @property
    def path(self) -> Path | None:
        if self.home is None:
            return None
        return self.home / EXPERIENCES_FILENAME

    def append(self, experience: Experience) -> bool:
        """Idempotent on cycle_id: a second record for the same cycle
        is refused (no duplicate learning). Returns stored or not."""
        if not isinstance(experience, Experience):
            return False
        if experience.cycle_id and experience.cycle_id in self._by_cycle:
            return False
        try:
            from ..intelligence.snapshot import scrub
            clean = scrub(experience.to_dict())
            line = json.dumps(clean, sort_keys=True, default=str)
        except (TypeError, ValueError):
            return False
        if len(line.encode("utf-8")) > MAX_LINE_BYTES:
            return False
        self._index[experience.experience_id] = json.loads(line)
        if experience.cycle_id:
            self._by_cycle[experience.cycle_id] = experience.experience_id
        while len(self._index) > self.max_index:
            oldest = next(iter(self._index))
            record = self._index.pop(oldest)
            cycle = record.get("cycle_id", "")
            if cycle and self._by_cycle.get(cycle) == oldest:
                del self._by_cycle[cycle]
        path = self.path
        if path is None:
            return True
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
                handle.flush()
                try:
                    os.fsync(handle.fileno())
                except OSError:
                    pass
            return True
        except OSError:
            return False

    def get(self, experience_id: str) -> dict[str, Any] | None:
        self._sync_from_disk()
        item = self._index.get(experience_id)
        return dict(item) if item is not None else None

    def find_by_cycle(self, cycle_id: str) -> dict[str, Any] | None:
        self._sync_from_disk()
        experience_id = self._by_cycle.get(cycle_id)
        if experience_id is None:
            return None
        return self.get(experience_id)

    def _sync_from_disk(self, tail_lines: int = 2000) -> None:
        path = self.path
        if path is None or not path.exists():
            return
        try:
            with open(path, "rb") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                handle.seek(max(0, size - tail_lines * 512))
                lines = handle.read().decode(
                    "utf-8", errors="replace").splitlines()
        except OSError:
            return
        for raw in lines[-tail_lines:]:
            try:
                item = json.loads(raw)
            except ValueError:
                continue
            if isinstance(item, dict) and item.get("experience_id"):
                eid = str(item["experience_id"])
                self._index[eid] = item
                if item.get("cycle_id"):
                    self._by_cycle.setdefault(str(item["cycle_id"]), eid)
        while len(self._index) > self.max_index:
            oldest = next(iter(self._index))
            record = self._index.pop(oldest)
            cycle = record.get("cycle_id", "")
            if cycle and self._by_cycle.get(cycle) == oldest:
                del self._by_cycle[cycle]

    def search(self, *, outcome: str = "", modality: str = "",
               error_type: str = "", limit: int = 50,
               since: float = 0.0) -> list[dict[str, Any]]:
        """Bounded filtered retrieval. Never loads more than max_index."""
        self._sync_from_disk()
        out: list[dict[str, Any]] = []
        for item in self._index.values():
            if outcome and item.get("outcome") != outcome:
                continue
            if since and float(item.get("timestamp", 0.0) or 0.0) < since:
                continue
            if modality and modality not in json.dumps(
                    item.get("observation_refs", []), default=str):
                continue
            if error_type and error_type not in (
                    item.get("prediction_error", "") +
                    json.dumps(item.get("evaluations", []), default=str)):
                continue
            out.append(dict(item))
            if len(out) >= max(1, limit):
                break
        out.sort(key=lambda i: float(i.get("timestamp", 0.0) or 0.0),
                 reverse=True)
        return out

    def count(self) -> int:
        self._sync_from_disk()
        return len(self._index)


__all__ = [
    "Experience",
    "ExperienceError",
    "ExperienceStore",
    "EvidenceRef",
    "OutcomeEvaluation",
    "OutcomeEvaluator",
    "OutcomeState",
    "PredictionEvaluation",
    "PredictionVerdict",
]
