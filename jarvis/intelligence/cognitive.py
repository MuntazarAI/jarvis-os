"""Cognitive contract + supervisor for the 4.3 cognitive loop (4.3).

The :class:`IntelligenceLoop` remains the bounded cycle engine. This
module adds what a *system* needs around it:

- typed contract objects for every lifecycle stage (all carry
  correlation IDs, timestamps, provenance, and explicit uncertainty);
- :class:`CognitiveSupervisor`, the single conductor: dedup, state
  machine, persistence, replay, and observability. It coordinates
  existing subsystems (memory, world, reasoner, planner, policy,
  DeviceCommandService, audit) and implements none of them;
- :class:`CycleStore`, an append-only JSONL record of cycles.

Honesty rules (enforced, tested): uncertainty is never converted to
certainty (``NO_DECISION`` / ``NO_PREDICTION`` / ``UNKNOWN`` are first
class results); replay never executes physical actions (it uses the
loop's dry-run sandbox); duplicate events never re-execute.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from .loop import CycleRecord, IntelligenceLoop

CYCLES_FILENAME = "cognitive-cycles.jsonl"
MAX_EVENT_IDS = 1000
MAX_LINE_BYTES = 128 * 1024


class CognitiveStage(str, Enum):
    IDLE = "idle"
    OBSERVING = "observing"
    CONTEXTUALIZING = "contextualizing"
    REASONING = "reasoning"
    PREDICTING = "predicting"
    PLANNING = "planning"
    WAITING_AUTHORIZATION = "waiting_authorization"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    LEARNING = "learning"
    COMPLETED = "completed"
    FAILED = "failed"


#: Legal lifecycle transitions. Recovery/replan re-enters REASONING only
#: from FAILED-explicit states via a fresh event, never silently.
TRANSITIONS: dict[CognitiveStage, set[CognitiveStage]] = {
    CognitiveStage.IDLE: {CognitiveStage.OBSERVING},
    CognitiveStage.OBSERVING: {CognitiveStage.CONTEXTUALIZING,
                               CognitiveStage.FAILED},
    CognitiveStage.CONTEXTUALIZING: {CognitiveStage.REASONING,
                                     CognitiveStage.FAILED},
    CognitiveStage.REASONING: {CognitiveStage.PREDICTING,
                               CognitiveStage.FAILED},
    CognitiveStage.PREDICTING: {CognitiveStage.PLANNING,
                                CognitiveStage.FAILED},
    CognitiveStage.PLANNING: {CognitiveStage.WAITING_AUTHORIZATION,
                              CognitiveStage.FAILED},
    CognitiveStage.WAITING_AUTHORIZATION: {CognitiveStage.EXECUTING,
                                           CognitiveStage.FAILED},
    CognitiveStage.EXECUTING: {CognitiveStage.VERIFYING,
                               CognitiveStage.FAILED},
    CognitiveStage.VERIFYING: {CognitiveStage.LEARNING,
                               CognitiveStage.FAILED},
    CognitiveStage.LEARNING: {CognitiveStage.COMPLETED,
                              CognitiveStage.FAILED},
    CognitiveStage.COMPLETED: {CognitiveStage.IDLE},
    CognitiveStage.FAILED: {CognitiveStage.IDLE},
}


class CognitiveError(ValueError):
    """Invalid lifecycle transition or malformed cognitive object."""


def check_transition(frm: CognitiveStage, to: CognitiveStage) -> None:
    if to not in TRANSITIONS.get(frm, set()):
        raise CognitiveError(
            f"invalid cognitive transition: {frm.value} -> {to.value}")


def _utcnow() -> float:
    return time.time()


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


# -- contract ------------------------------------------------------------------


@dataclass
class CognitiveEvent:
    event_id: str = field(default_factory=lambda: _new_id("evt"))
    correlation_id: str = ""
    source: str = ""
    type: str = ""
    timestamp: float = field(default_factory=_utcnow)
    payload: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.source:
            raise CognitiveError("event source is required")
        if not self.type:
            raise CognitiveError("event type is required")
        if not self.correlation_id:
            self.correlation_id = self.event_id


@dataclass
class CognitiveFact:
    content: str
    source: str
    confidence: float = 0.5
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CognitiveContext:
    cycle_id: str
    event: CognitiveEvent
    facts: list[CognitiveFact] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


@dataclass
class CognitiveDecision:
    decided: bool = False  # False == NO_DECISION (explicit, honest)
    conclusion: str = ""
    evidence_refs: list[str] = field(default_factory=list)
    confidence: float = 0.0  # never inflated: 0 unless evidenced
    uncertainty: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CognitivePrediction:
    prediction: str = "NO_PREDICTION"
    confidence: float | None = None
    basis: list[str] = field(default_factory=list)
    expires_at: float | None = None

    @property
    def made(self) -> bool:
        return self.prediction != "NO_PREDICTION"


@dataclass
class CognitivePlan:
    goal: str = ""
    steps: list[dict[str, Any]] = field(default_factory=list)
    expected: str = ""
    verification_conditions: dict[str, Any] = field(default_factory=dict)
    recovery: str = ""
    bounded: bool = True


@dataclass
class CognitiveAction:
    action: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    actor: str = "cognitive-loop"
    approval_state: str = ""  # "", "waiting", "approved", "denied"
    command_id: str = ""  # outbox id once parked/delivered (not secret)


@dataclass
class CognitiveResult:
    ok: bool = False
    output: Any = None
    error: str = ""
    correlation_id: str = ""


@dataclass
class CognitiveVerification:
    verdict: str = "UNKNOWN"  # VERIFIED|PARTIALLY_VERIFIED|FAILED|UNKNOWN
    evidence: list[str] = field(default_factory=list)
    expected: str = ""
    observed: str = ""


@dataclass
class CognitiveLearningRecord:
    cycle_id: str
    outcome: str = ""
    memory_id: str = ""
    audit_refs: list[str] = field(default_factory=list)


@dataclass
class CognitiveOutcome:
    """The complete, inspectable result of one supervised cycle."""

    cycle_id: str
    event: CognitiveEvent
    state: CognitiveStage = CognitiveStage.COMPLETED
    stages: list[dict[str, Any]] = field(default_factory=list)
    decision: CognitiveDecision = field(default_factory=CognitiveDecision)
    prediction: CognitivePrediction = field(
        default_factory=CognitivePrediction)
    plan: CognitivePlan = field(default_factory=CognitivePlan)
    action: CognitiveAction = field(default_factory=CognitiveAction)
    policy_allowed: bool | None = None
    result: CognitiveResult = field(default_factory=CognitiveResult)
    verification: CognitiveVerification = field(
        default_factory=CognitiveVerification)
    learning: CognitiveLearningRecord | None = None
    transitions: list[dict[str, Any]] = field(default_factory=list)
    duration_ms: float = 0.0
    replayed: bool = False  # True when produced without physical actions

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["event"] = asdict(self.event)
        data["state"] = self.state.value
        return data


# -- cycle store ---------------------------------------------------------------


class CycleStore:
    """Append-only JSONL record of supervised cycles. Crash-safe reads."""

    def __init__(self, home: str | Path | None) -> None:
        self.home = Path(home) if home else None

    @property
    def path(self) -> Path | None:
        if self.home is None:
            return None
        return self.home / CYCLES_FILENAME

    def append(self, outcome: CognitiveOutcome) -> bool:
        path = self.path
        if path is None:
            return False
        try:
            from .snapshot import scrub
            clean = scrub(outcome.to_dict())
            line = json.dumps(clean, sort_keys=True, default=str)
        except (TypeError, ValueError):
            return False
        if len(line.encode("utf-8")) > MAX_LINE_BYTES:
            return False
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

    def read(self, limit: int = 100) -> list[dict[str, Any]]:
        """Newest-first. Corrupt lines skipped, never fatal."""
        path = self.path
        if path is None or not path.exists():
            return []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out: list[dict[str, Any]] = []
        for raw in reversed(lines[-max(limit, 1):]):
            try:
                item = json.loads(raw)
            except ValueError:
                continue
            if isinstance(item, dict):
                out.append(item)
        return out

    def find(self, cycle_id: str) -> dict[str, Any] | None:
        for item in self.read(limit=10000):
            if item.get("cycle_id") == cycle_id:
                return item
        return None


# -- supervisor ------------------------------------------------------------------


class CognitiveSupervisor:
    """Conductor of the cognitive lifecycle. Coordinates, never implements.

    Owns: an :class:`IntelligenceLoop` engine, a :class:`CycleStore`,
    a bounded duplicate-event set, and the observable stage state
    machine. Memory/world/reasoning/planning/policy/device/audit work
    stays in the subsystems bound to the loop's hooks.
    """

    def __init__(self, loop: IntelligenceLoop, *,
                 home: str | Path | None = None,
                 actor: str = "cognitive-loop") -> None:
        if loop is None:
            raise CognitiveError("supervisor requires a loop engine")
        self.loop = loop
        self.store = CycleStore(home)
        self.actor = actor
        self.stage = CognitiveStage.IDLE
        self.transitions: list[dict[str, Any]] = []
        self._seen_events: list[str] = []
        self.total_cycles = 0
        self.total_duplicates = 0
        self.total_failures = 0

    # -- state machine -----------------------------------------------------

    def _enter(self, stage: CognitiveStage) -> None:
        check_transition(self.stage, stage)
        self.transitions.append({"at": _utcnow(), "from": self.stage.value,
                                 "to": stage.value})
        self.stage = stage

    def _reset(self) -> None:
        if self.stage not in (CognitiveStage.IDLE,
                              CognitiveStage.COMPLETED,
                              CognitiveStage.FAILED):
            raise CognitiveError(
                f"supervisor busy (stage={self.stage.value})")
        if self.stage is not CognitiveStage.IDLE:
            self._enter(CognitiveStage.IDLE)
        self.transitions = []

    # -- events --------------------------------------------------------------

    @staticmethod
    def coerce_event(event: Any) -> CognitiveEvent:
        """Accept CognitiveEvent, SensoryEvent-like, or plain dicts."""
        if isinstance(event, CognitiveEvent):
            if not event.correlation_id:
                event.correlation_id = event.event_id
            return event
        if isinstance(event, dict):
            payload = dict(event.get("payload", {}))
            return CognitiveEvent(
                event_id=str(event.get("event_id", "") or _new_id("evt")),
                correlation_id=str(event.get("correlation_id", "")),
                source=str(event.get("source", "unknown")),
                type=str(event.get("type", event.get("message_type",
                                                     "unknown"))),
                timestamp=float(event.get("timestamp") or _utcnow()),
                payload=payload,
                provenance={"coerced_from": "dict"})
        source = str(getattr(event, "source", "unknown"))
        return CognitiveEvent(
            event_id=str(getattr(event, "event_id", "") or _new_id("evt")),
            correlation_id=str(getattr(event, "correlation_id", "")),
            source=source,
            type=str(getattr(event, "type", "unknown")),
            timestamp=float(getattr(event, "timestamp", 0.0) or _utcnow()),
            payload=dict(getattr(event, "payload", {}) or {}),
            provenance={"coerced_from": type(event).__name__})

    def _is_duplicate(self, event: CognitiveEvent) -> bool:
        if event.event_id in self._seen_events:
            self.total_duplicates += 1
            return True
        self._seen_events.append(event.event_id)
        del self._seen_events[:-MAX_EVENT_IDS]
        return False

    # -- cycles ----------------------------------------------------------------

    def process(self, event: Any, *, timeout_s: float = 30.0,
                dry_run: bool = False) -> CognitiveOutcome:
        """Run one supervised cycle. Dry-run replays without action."""
        started = time.perf_counter()
        cognitive_event = self.coerce_event(event)
        if self._is_duplicate(cognitive_event):
            return CognitiveOutcome(
                cycle_id=f"dup-{cognitive_event.event_id[:16]}",
                event=cognitive_event, state=CognitiveStage.COMPLETED,
                duration_ms=0.0, replayed=True)
        self._reset()
        engine = self.loop.sandbox() if dry_run else self.loop
        outcome = CognitiveOutcome(
            cycle_id="", event=cognitive_event, replayed=dry_run)
        try:
            self._enter(CognitiveStage.OBSERVING)
            record = self._run_engine(engine, cognitive_event, timeout_s)
            outcome.cycle_id = record.cycle_id
            self._map_record(record, outcome)
            if record.failed_stage:
                try:
                    self._enter(CognitiveStage.FAILED)
                except CognitiveError:
                    pass
                outcome.state = CognitiveStage.FAILED
                self.total_failures += 1
            else:
                self._enter(CognitiveStage.COMPLETED)
                outcome.state = CognitiveStage.COMPLETED
        except CognitiveError:
            raise
        except Exception as exc:
            outcome.state = CognitiveStage.FAILED
            outcome.stages.append({"stage": self.stage.value, "ok": False,
                                   "error": f"{type(exc).__name__}: {exc}"[:300]})
            try:
                self._enter(CognitiveStage.FAILED)
            except CognitiveError:
                pass
            self.total_failures += 1
        outcome.duration_ms = round((time.perf_counter() - started) * 1000.0, 2)
        outcome.transitions = list(self.transitions)
        self.total_cycles += 1
        try:
            self.store.append(outcome)
        except Exception:
            pass
        return outcome

    def _run_engine(self, engine: IntelligenceLoop,
                    event: CognitiveEvent, timeout_s: float) -> CycleRecord:
        engine.start()
        # The engine owns per-stage timeouts; the supervisor owns the
        # lifecycle walk below via the mapped record.
        self._enter(CognitiveStage.CONTEXTUALIZING)
        self._enter(CognitiveStage.REASONING)
        self._enter(CognitiveStage.PREDICTING)
        self._enter(CognitiveStage.PLANNING)
        self._enter(CognitiveStage.WAITING_AUTHORIZATION)
        record = engine.cycle_once(event.payload, timeout_s=timeout_s)
        self._enter(CognitiveStage.EXECUTING)
        self._enter(CognitiveStage.VERIFYING)
        self._enter(CognitiveStage.LEARNING)
        return record

    def _map_record(self, record: CycleRecord,
                    outcome: CognitiveOutcome) -> None:
        outcome.stages = [
            {"stage": s.stage, "ok": s.ok, "error": s.error,
             "duration_ms": round(s.duration_ms, 2), "detail": s.detail}
            for s in record.stages
        ]
        by_stage = {s.stage: s for s in record.stages}
        reason_detail = by_stage.get("reason").detail \
            if by_stage.get("reason") else {}
        outcome.decision = CognitiveDecision(
            decided=bool(reason_detail.get("concluded")),
            conclusion=str(reason_detail.get("summary", ""))[:500],
            evidence_refs=list(reason_detail.get("evidence_refs", []) or []),
            confidence=float(reason_detail.get("confidence", 0.0) or 0.0),
            uncertainty=list(reason_detail.get("uncertainty", []) or []),
            metadata={"mode": str(reason_detail.get("mode", ""))[:80]})
        prediction_detail = by_stage.get("predict").detail \
            if by_stage.get("predict") else {}
        outcome.prediction = CognitivePrediction(
            prediction=str(prediction_detail.get("prediction",
                                                 "NO_PREDICTION"))[:500],
            confidence=prediction_detail.get("confidence"),
            basis=list(prediction_detail.get("basis", []) or []))
        plan_detail = by_stage.get("plan").detail \
            if by_stage.get("plan") else {}
        action_detail = self._action_from_record(record)
        outcome.plan = CognitivePlan(
            goal=str(action_detail.get("reason", ""))[:300],
            steps=[outcome_action(action_detail)],
            expected=str(action_detail.get("expected", ""))[:300],
            verification_conditions=dict(
                action_detail.get("verification_conditions", {}) or {}),
            recovery=str(action_detail.get("recovery", ""))[:300])
        policy_detail = by_stage.get("policy").detail \
            if by_stage.get("policy") else {}
        outcome.action = CognitiveAction(
            action=record.action_taken,
            args=dict(action_detail.get("args", {}) or {}),
            actor=self.actor,
            approval_state=self._approval_state(record, policy_detail),
            command_id=self._command_ref(record))
        outcome.policy_allowed = record.policy_allowed
        result_detail = by_stage.get("act").detail \
            if by_stage.get("act") else {}
        outcome.result = CognitiveResult(
            ok=bool(result_detail.get("ok", record.ok)),
            output=result_detail.get("output", result_detail.get("result")),
            error=str(result_detail.get("error", ""))[:500],
            correlation_id=record.cycle_id)
        verify_detail = by_stage.get("verify").detail \
            if by_stage.get("verify") else {}
        outcome.verification = CognitiveVerification(
            verdict=str(verify_detail.get("verdict", "UNKNOWN"))[:32],
            evidence=list(verify_detail.get("evidence", []) or []),
            expected=str(verify_detail.get("expected", ""))[:300],
            observed=str(verify_detail.get("observed", ""))[:300])
        learn_detail = by_stage.get("learn").detail \
            if by_stage.get("learn") else {}
        if learn_detail.get("stored") or learn_detail.get("learned"):
            outcome.learning = CognitiveLearningRecord(
                cycle_id=record.cycle_id,
                outcome=("ok" if outcome.result.ok else "failed"),
                memory_id=str(learn_detail.get("memory_id", ""))[:64],
                audit_refs=[])
        if record.failed_stage:
            outcome.state = CognitiveStage.FAILED

    @staticmethod
    def _action_from_record(record: CycleRecord) -> dict[str, Any]:
        for stage in record.stages:
            if stage.stage == "plan":
                detail = stage.detail
                if isinstance(detail, dict):
                    return detail
        return {}

    @staticmethod
    @staticmethod
    def _command_ref(record: CycleRecord) -> str:
        for stage in record.stages:
            if stage.stage == "act" and isinstance(stage.detail, dict):
                ref = str(stage.detail.get("command_ref", ""))
                if ref:
                    return ref[:64]
        return ""

    @staticmethod
    def _approval_state(record: CycleRecord,
                        policy_detail: dict[str, Any]) -> str:
        if not record.action_taken:
            return ""
        for stage in record.stages:
            if stage.stage == "act" and isinstance(stage.detail, dict) \
                    and stage.detail.get("waiting_approval"):
                return "waiting"
        if record.policy_allowed is False:
            reason = str(policy_detail.get("reason", ""))
            if "needs approval" in reason or "approval" in reason:
                return "waiting"
            return "denied"
        if record.policy_allowed is True:
            return "approved"
        return ""

    # -- replay / observability --------------------------------------------------

    def replay(self, cycle_id: str) -> CognitiveOutcome:
        """Re-run a stored cycle's event through the dry-run sandbox.

        Physical actions can never execute: the sandbox binds no
        executor and disables the act stage by construction.
        """
        stored = self.store.find(cycle_id)
        if stored is None:
            raise CognitiveError(f"unknown cycle: {cycle_id}")
        payload = (stored.get("event") or {}).get("payload", {})
        outcome = self.process(payload, dry_run=True)
        outcome.cycle_id = f"replay-{cycle_id}"
        return outcome

    def inspect(self, cycle_id: str) -> dict[str, Any] | None:
        stored = self.store.find(cycle_id)
        if stored is not None:
            return stored
        for record in self.loop.history:
            if record.cycle_id == cycle_id:
                return record.to_dict()
        return None

    def failures(self, limit: int = 50) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for item in self.store.read(limit=1000):
            stages = item.get("stages", [])
            bad = [s for s in stages if isinstance(s, dict)
                   and not s.get("ok", True)]
            if bad or item.get("state") == "failed":
                out.append(item)
                if len(out) >= limit:
                    break
        return out

    def status(self) -> dict[str, Any]:
        return {
            "stage": self.stage.value,
            "total_cycles": self.total_cycles,
            "total_duplicates": self.total_duplicates,
            "total_failures": self.total_failures,
            "transitions": len(self.transitions),
            "loop": self.loop.status(),
            "stored_cycles": len(self.store.read(limit=100000)),
        }


def outcome_action(action_detail: dict[str, Any]) -> dict[str, Any]:
    """Single planned step projection for the outcome plan view."""
    return {"action": str(action_detail.get("action", ""))[:120],
            "args_keys": sorted(map(str, (action_detail.get("args")
                                          or {}).keys()))[:12]}


__all__ = [
    "CognitiveSupervisor",
    "CognitiveStage",
    "CognitiveEvent",
    "CognitiveContext",
    "CognitiveFact",
    "CognitiveDecision",
    "CognitivePrediction",
    "CognitivePlan",
    "CognitiveAction",
    "CognitiveResult",
    "CognitiveVerification",
    "CognitiveLearningRecord",
    "CognitiveOutcome",
    "CycleStore",
    "CognitiveError",
    "check_transition",
    "TRANSITIONS",
    "outcome_action",
]
