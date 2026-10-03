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
    metadata: dict[str, Any] = field(default_factory=dict)

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
                 actor: str = "cognitive-loop",
                 enable_learning: bool = True) -> None:
        if loop is None:
            raise CognitiveError("supervisor requires a loop engine")
        self.loop = loop
        self.store = CycleStore(home)
        self.actor = actor
        self.enable_learning = bool(enable_learning)
        self.stage = CognitiveStage.IDLE
        self.transitions: list[dict[str, Any]] = []
        self._seen_events: list[str] = []
        self.total_cycles = 0
        self.total_duplicates = 0
        self.total_failures = 0
        self.total_experiences = 0
        self.total_learning_failures = 0
        # Lazily built learning stack (home-backed when available).
        self._experience_store: Any = None
        self._beliefs: Any = None
        self._learner: Any = None
        self._world: Any = None
        self._palace: Any = None
        self._dots: Any = None
        self._neural: Any = None
        self._neural_init_done = False
        self._home = Path(home) if home else None

    def bind_learning(self, *, world: Any = None, palace: Any = None,
                      dots: Any = None, neural: Any = None) -> None:
        """Attach live subsystems for learning (world/palace/dots).

        The engine's own hooks stay untouched; learning reads through
        these references only. Pass neural=False to disable, None for
        a default bounded signal, or an object with compute()/adjust().
        """
        self._world = world
        self._palace = palace
        self._dots = dots
        if neural is not None:
            self._neural = neural if neural is not False else None
            self._neural_init_done = True
            return
        self._neural_init_done = False

    def _ensure_neural(self) -> None:
        if getattr(self, "_neural_init_done", False):
            return
        self._neural_init_done = True
        try:
            from ..cognition.neural import NeuralSignal
            self._neural = NeuralSignal()
        except Exception:
            self._neural = None

    def _learning_stack(self) -> tuple[Any, Any, Any]:
        """Lazily construct (experience store, beliefs, learner)."""
        if self._experience_store is None:
            from ..cognition.experience import ExperienceStore
            from ..cognition.beliefs import BeliefStore
            from ..cognition.learning import LearningEngine
            beliefs = BeliefStore(self._home)
            self._experience_store = ExperienceStore(self._home)
            self._beliefs = beliefs
            self._learner = LearningEngine(beliefs)
        return self._experience_store, self._beliefs, self._learner

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
            beliefs = self._consult_beliefs(cognitive_event)
            if beliefs:
                payload = dict(cognitive_event.payload or {})
                payload["beliefs"] = beliefs[:3]
                cognitive_event.payload = payload
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
        if (self.enable_learning and not dry_run
                and not outcome.replayed
                and outcome.state == CognitiveStage.COMPLETED):
            try:
                self._learn_from_outcome(outcome)
            except Exception as exc:
                # Defense in depth: even a bug inside the learning
                # path itself must never corrupt a completed outcome.
                self.total_learning_failures += 1
                try:
                    outcome.stages.append(
                        {"stage": "learn", "ok": False,
                         "error": f"learning failed: "
                                  f"{type(exc).__name__}"[:200]})
                except Exception:
                    pass
        return outcome

    def _consult_beliefs(self, event: CognitiveEvent) -> list[dict[str, Any]]:
        """Form beliefs: public/local belief matches enrich the event.

        Runs inside CONTEXTUALIZING (no new lifecycle state). Only
        public/local beliefs are ever injected; sensitive/private stay
        out of the cycle. Best-effort, never raises.
        """
        try:
            _, beliefs, _ = self._learning_stack()
            query = str((event.payload or {}).get("text", ""))[:300]
            if not query:
                return []
            found = []
            for belief in beliefs.search(query, limit=3,
                                         min_confidence=0.3):
                if belief.privacy_class in ("sensitive", "private"):
                    continue
                found.append({"statement": belief.statement,
                              "confidence": belief.confidence,
                              "belief_id": belief.belief_id})
            return found
        except Exception:
            return []

    def _learn_from_outcome(self, outcome: CognitiveOutcome) -> None:
        """Build experience, evaluate, learn, mirror. Isolated: learning
        failure is recorded on the outcome and never corrupts it."""
        try:
            from ..cognition import integration as cog_integration
            from ..cognition.experience import (
                EvidenceRef,
                Experience,
                OutcomeEvaluator,
                OutcomeState,
            )
            store, beliefs, learner = self._learning_stack()
            event = outcome.event
            experience = Experience(
                cycle_id=outcome.cycle_id,
                outcome=self._outcome_state_of(outcome),
                confidence=float(outcome.decision.confidence or 0.0),
                observation_refs=[EvidenceRef(
                    kind="event", ref_id=event.event_id,
                    note=f"{event.source}:{event.type}")],
                provenance={"supervisor": True,
                            "policy_allowed": outcome.policy_allowed,
                            "verification": outcome.verification.verdict},
                privacy_class="local")
            evaluation = OutcomeEvaluator.evaluate(
                prediction_made=outcome.prediction.made,
                expected=outcome.prediction.prediction,
                actual=outcome.verification.observed,
                action_ok=outcome.result.ok
                if outcome.action.action else None,
                verification=outcome.verification.verdict,
                evidence_count=len(experience.observation_refs) + (
                    1 if outcome.decision.decided else 0))
            stored = store.append(experience)
            if not stored:
                return
            self.total_experiences += 1
            report = learner.learn_from_outcome(
                experience, evaluation, by="cognitive-supervisor")
            if self._neural is not None and outcome.prediction.made:
                self._apply_neural_signal(outcome, experience)
            dot_id = ""
            if isinstance(event.payload, dict):
                dot_id = str(event.payload.get("dot_id", ""))[:64]
            cog_integration.mirror_experience(
                experience, evaluation, dots=self._dots,
                world=self._world, dot_id=dot_id)
            if report.learned:
                outcome.learning = CognitiveLearningRecord(
                    cycle_id=outcome.cycle_id,
                    outcome=f"learned {len(report.updates)} update(s)",
                    audit_refs=[u.target[:32] for u in report.updates[:5]])
        except Exception as exc:
            self.total_learning_failures += 1
            try:
                outcome.stages.append(
                    {"stage": "learn", "ok": False,
                     "error": f"learning failed: {type(exc).__name__}"[:200]})
            except Exception:
                pass

    @staticmethod
    def _outcome_state_of(outcome: CognitiveOutcome) -> "OutcomeState":
        from ..cognition.experience import OutcomeState
        if not outcome.action.action:
            return OutcomeState.NO_ACTION
        if not outcome.decision.decided:
            return OutcomeState.NO_DECISION
        verdict = outcome.verification.verdict
        if verdict == "VERIFIED":
            return OutcomeState.SUCCESS
        if verdict == "PARTIALLY_VERIFIED":
            return OutcomeState.PARTIAL
        if verdict == "FAILED":
            return OutcomeState.FAILED
        return OutcomeState.UNKNOWN

    def _apply_neural_signal(self, outcome: CognitiveOutcome,
                             experience: Any) -> None:
        """Optional bounded confidence nudge, fully provenanced."""
        try:
            self._ensure_neural()
            neural = self._neural
            if neural is None or not getattr(neural, "available", False):
                return
            from ..cognition.neural import feature_vector
            features = feature_vector(
                outcome.result.ok,
                float(outcome.decision.confidence or 0.0),
                len(experience.observation_refs or []) + 1,
                0.5, True, False,
                outcome.verification.verdict not in ("VERIFIED", "FAILED"),
                outcome.verification.verdict == "VERIFIED")
            computed = neural.compute(features)
            adjusted = neural.adjust(
                float(outcome.prediction.confidence or 0.5),
                float(computed.get("signal", 0.0)))
            outcome.prediction.confidence = adjusted
            outcome.prediction.metadata = {
                "neural_adjusted": True,
                "neural_signal": computed.get("signal", 0.0),
                "neural_spikes": computed.get("spikes", 0)}
        except Exception:
            pass

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
        payload: dict[str, Any] = {
            "stage": self.stage.value,
            "total_cycles": self.total_cycles,
            "total_duplicates": self.total_duplicates,
            "total_failures": self.total_failures,
            "total_experiences": self.total_experiences,
            "total_learning_failures": self.total_learning_failures,
            "transitions": len(self.transitions),
            "loop": self.loop.status(),
        }
        try:
            payload["stored_cycles"] = len(self.store.read(limit=100000))
        except Exception:
            payload["stored_cycles"] = 0
        try:
            store, _, learner = self._learning_stack()
            payload["stored_experiences"] = store.count()
            payload["learning_metrics"] = dict(
                getattr(learner, "metrics", {}))
        except Exception:
            payload["stored_experiences"] = 0
            payload["learning_metrics"] = {}
        return payload


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
