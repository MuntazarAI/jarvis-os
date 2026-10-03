"""IntelligenceLoop: the bounded cognitive cycle for JARVIS.

One cycle: ingest -> normalize -> world update -> recall -> neural ->
reason -> predict -> plan -> policy -> act -> verify -> observe -> learn.
Every stage is typed, traced, failure-isolated, and policy-gated at the
action boundary.

The loop NEVER runs unbounded autonomy: max_cycles bounds every run(),
each cycle has a timeout, and externally meaningful actions pass the
caller's PolicyEngine before execution.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Mapping


class LoopState(str, Enum):
    START = "start"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"
    TIMEOUT = "timeout"


STAGES = (
    "ingest", "normalize", "world", "recall", "neural",
    "reason", "predict", "plan", "policy", "act", "verify",
    "observe", "learn",
)


@dataclass
class StageResult:
    stage: str
    ok: bool = True
    detail: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    duration_ms: float = 0.0


@dataclass
class CycleRecord:
    cycle_id: str
    started_at: float
    ended_at: float = 0.0
    stages: list[StageResult] = field(default_factory=list)
    action_taken: str = ""
    policy_allowed: bool | None = None
    failed_stage: str = ""

    @property
    def ok(self) -> bool:
        return not self.failed_stage

    def to_dict(self) -> dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_ms": round((self.ended_at - self.started_at) * 1000.0, 2) if self.ended_at else 0.0,
            "ok": self.ok,
            "failed_stage": self.failed_stage,
            "action_taken": self.action_taken,
            "policy_allowed": self.policy_allowed,
            "stages": [
                {"stage": s.stage, "ok": s.ok, "error": s.error,
                 "duration_ms": round(s.duration_ms, 2), "detail": s.detail}
                for s in self.stages
            ],
        }


ActionExecutor = Callable[[str, Mapping[str, Any]], dict[str, Any]]
"""Executes an authorized typed action. Returns a result dict. Runs ONLY
after PolicyEngine approval; the loop never calls this otherwise."""


class IntelligenceLoop:
    """Bounded, observable cognitive cycle over injected subsystems.

    All subsystem hooks are optional callables: the loop degrades safely
    when a subsystem is absent or fails. ``policy_check`` and ``executor``
    are the only path to real action, and ``executor`` is invoked only
    when ``policy_check`` explicitly allows.
    """

    def __init__(
        self,
        *,
        normalize: Callable[[Any], dict[str, Any]] | None = None,
        world_update: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        recall: Callable[[dict[str, Any]], list[dict[str, Any]]] | None = None,
        neural_step: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        reason: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        predict: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        plan: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        policy_check: Callable[[str, Mapping[str, Any]], tuple[bool, str]] | None = None,
        executor: ActionExecutor | None = None,
        verify: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        observe: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        learn: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        max_history: int = 200,
        dry_run: bool = False,
        neural_checkpoint: Callable[[], Any] | None = None,
        neural_restore: Callable[[Any], None] | None = None,
    ) -> None:
        self.normalize = normalize
        self.world_update = world_update
        self.recall = recall
        self.neural_step = neural_step
        self.reason = reason
        self.predict = predict
        self.plan = plan
        self.policy_check = policy_check
        self.executor = executor
        self.verify = verify
        self.observe = observe
        self.learn = learn
        self.state = LoopState.START
        self.history: list[CycleRecord] = []
        self.max_history = max_history
        self.total_cycles = 0
        self.total_failures = 0
        self.total_timeouts = 0
        self.dry_run = bool(dry_run)
        if self.dry_run and executor is not None:
            raise ValueError("dry-run loops must not bind an executor")
        # Optional neural state preservation for dry-run replay: when both
        # are set, a dry-run cycle checkpoints the live network before the
        # first stage and restores it afterwards, so replay never advances
        # live neural/learning state.
        self.neural_checkpoint = neural_checkpoint
        self.neural_restore = neural_restore

    # -- lifecycle ------------------------------------------------------
    def start(self) -> None:
        if self.state in (LoopState.RUNNING, LoopState.PAUSED):
            return
        self.state = LoopState.RUNNING

    def pause(self) -> None:
        if self.state is LoopState.RUNNING:
            self.state = LoopState.PAUSED

    def resume(self) -> None:
        if self.state is LoopState.PAUSED:
            self.state = LoopState.RUNNING

    def stop(self) -> None:
        self.state = LoopState.STOPPED

    def sandbox(self) -> "IntelligenceLoop":
        """Return a dry-run clone: pure hooks shared, every side-effecting
        hook replaced by a recording stub, no executor bound.

        The sandbox never touches world state, spatial memory, policy audit,
        approvals, persistent memory, learning state, devices, network, or
        filesystem. Used by snapshot replay and dry-run reasoning.
        """
        def _stub(_ctx: Any = None) -> dict[str, Any]:
            return {"dry_run": True, "skipped": "side effects disabled"}

        def _recall_stub(_normalized: dict[str, Any]) -> list[dict[str, Any]]:
            return []

        return IntelligenceLoop(
            normalize=self.normalize,
            world_update=_stub,
            recall=_recall_stub,
            neural_step=self.neural_step,
            reason=self.reason,
            predict=_stub,
            plan=self.plan,
            policy_check=None,
            executor=None,
            verify=_stub,
            observe=_stub,
            learn=_stub,
            max_history=self.max_history,
            dry_run=True,
            neural_checkpoint=self.neural_checkpoint,
            neural_restore=self.neural_restore,
        )

    # -- cycles ---------------------------------------------------------
    # Timeout contract (honest, no threads):
    # - deadlines use time.monotonic() and are checked before AND after
    #   every stage;
    # - once the boundary is crossed, NO further stage runs: in particular
    #   the act stage can never execute after a timeout;
    # - the failure is deterministic (failed_stage + timeout detail) and the
    #   loop enters TIMEOUT state; run() stops scheduling new cycles.
    # Residual limitation (documented, not hidden): a synchronous hook that
    # never returns cannot be preempted without threads. The guarantee is
    # that nothing else runs afterwards and the timeout is recorded.
    def run(self, events: list[Any], *, max_cycles: int = 10,
            timeout_s: float = 30.0) -> list[CycleRecord]:
        """Run at most max_cycles over the given events. Bounded always.

        timeout_s bounds the whole run (monotonic clock). Each cycle also
        receives the remaining budget so a single slow cycle cannot push the
        run past its deadline unnoticed.
        """
        if max_cycles <= 0:
            raise ValueError("max_cycles must be positive")
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        self.start()
        records: list[CycleRecord] = []
        run_deadline = time.monotonic() + timeout_s
        for event in events[:max_cycles]:
            if self.state is not LoopState.RUNNING:
                break
            remaining = run_deadline - time.monotonic()
            if remaining <= 0:
                self.state = LoopState.TIMEOUT
                self.total_timeouts += 1
                break
            record = self.cycle_once(event, timeout_s=remaining)
            records.append(record)
            if record.failed_stage and "timeout" in record.failed_stage:
                break
        if self.state is LoopState.RUNNING:
            self.state = LoopState.PAUSED
        return records

    def cycle_once(self, event: Any, *, timeout_s: float | None = None,
                   stage_timeout_s: float | None = None) -> CycleRecord:
        """Run one bounded cycle. timeout_s bounds the whole cycle;
        stage_timeout_s bounds any single stage (defaults to timeout_s)."""
        if timeout_s is not None and timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        cycle_id = f"cyc-{uuid.uuid4().hex[:12]}"
        record = CycleRecord(cycle_id=cycle_id, started_at=time.time())
        deadline = (time.monotonic() + timeout_s) if timeout_s is not None else None
        stage_budget = stage_timeout_s if stage_timeout_s is not None else timeout_s
        context: dict[str, Any] = {"cycle_id": cycle_id, "raw_event": event}
        if deadline is not None:
            # Cooperative hooks may check this themselves.
            context["deadline_monotonic"] = deadline

        checkpoint: Any = None
        if self.dry_run and self.neural_checkpoint is not None:
            try:
                checkpoint = self.neural_checkpoint()
            except Exception:
                checkpoint = None
        try:
            for stage in STAGES:
                if self.state not in (LoopState.RUNNING, LoopState.START):
                    break
                if deadline is not None and time.monotonic() > deadline:
                    self._timeout(record, stage, timeout_s or 0.0, "deadline crossed before stage")
                    break
                started = time.perf_counter()
                try:
                    result = self._run_stage(stage, context)
                    elapsed = (time.perf_counter() - started) * 1000.0
                    if stage_budget is not None and elapsed > stage_budget * 1000.0:
                        self._timeout(record, stage, stage_budget, "stage exceeded budget",
                                      detail=result)
                        break
                    if deadline is not None and time.monotonic() > deadline:
                        self._timeout(record, stage, timeout_s or 0.0,
                                      "deadline crossed during stage", detail=result)
                        break
                    record.stages.append(StageResult(stage=stage, ok=True,
                                                    detail=result, duration_ms=elapsed))
                except Exception as exc:  # failure isolation per stage
                    elapsed = (time.perf_counter() - started) * 1000.0
                    record.stages.append(StageResult(stage=stage, ok=False,
                                                    error=f"{type(exc).__name__}: {exc}"[:300],
                                                    duration_ms=elapsed))
                    record.failed_stage = stage
                    break
        finally:
            if checkpoint is not None and self.neural_restore is not None:
                try:
                    self.neural_restore(checkpoint)
                except Exception:
                    pass

        record.ended_at = time.time()
        action = context.get("action") or {}
        record.action_taken = str(action.get("action", ""))[:120]
        if "policy_allowed" in context:
            record.policy_allowed = bool(context["policy_allowed"])
        self.total_cycles += 1
        if record.failed_stage:
            self.total_failures += 1
        self.history.append(record)
        if len(self.history) > self.max_history:
            del self.history[:len(self.history) - self.max_history]
        return record

    def _timeout(self, record: CycleRecord, stage: str, budget_s: float,
                 reason: str, detail: dict[str, Any] | None = None) -> None:
        record.stages.append(StageResult(
            stage=stage, ok=False,
            error=f"timeout: {reason} (budget_s={budget_s})",
            detail={"timeout": True, **(detail or {})}))
        record.failed_stage = f"timeout:{stage}"
        self.state = LoopState.TIMEOUT
        self.total_timeouts += 1

    def _run_stage(self, stage: str, context: dict[str, Any]) -> dict[str, Any]:
        if stage == "ingest":
            return {"accepted": context.get("raw_event") is not None}
        if stage == "normalize":
            if self.normalize is None:
                return {"skipped": True}
            normalized = self.normalize(context.get("raw_event"))
            context["normalized"] = normalized
            return {"keys": sorted(normalized.keys())[:20]}
        if stage == "world":
            if self.world_update is None:
                return {"skipped": True}
            update = self.world_update(context.get("normalized", {}))
            context["world"] = update
            return {"updated": bool(update)}
        if stage == "recall":
            if self.recall is None:
                return {"skipped": True}
            memories = self.recall(context.get("normalized", {}))
            context["memories"] = memories[:10]
            return {"recalled": len(context["memories"])}
        if stage == "neural":
            if self.neural_step is None:
                return {"skipped": True}
            signals = self.neural_step(context.get("normalized", {}))
            context["neural"] = signals
            return {"signals": sorted(signals.keys())[:20]}
        if stage == "reason":
            if self.reason is None:
                return {"skipped": True}
            conclusion = self.reason(context)
            context["conclusion"] = conclusion
            return {"concluded": bool(conclusion)}
        if stage == "predict":
            if self.predict is None:
                return {"prediction": "NO_PREDICTION", "skipped": True}
            prediction = self.predict(context)
            context["prediction"] = prediction
            return {"predicted": bool(prediction)
                    and prediction.get("prediction") != "NO_PREDICTION"}
        if stage == "plan":
            if self.plan is None:
                return {"skipped": True}
            action = self.plan(context)
            context["action"] = action
            args = action.get("args", {})
            # Keys only: values may carry secrets and records persist.
            return {"action": str(action.get("action", ""))[:120],
                    "args_keys": sorted(map(str, args.keys()))[:12]
                    if isinstance(args, dict) else []}
        if stage == "policy":
            action = context.get("action") or {}
            name = str(action.get("action", ""))
            if not name:
                return {"skipped": "no action proposed"}
            if self.policy_check is None:
                context["policy"] = {"allowed": False, "reason": "no policy bound (fail closed)"}
                context["policy_allowed"] = False
                return {"allowed": False, "reason": "no policy bound"}
            allowed, reason = self.policy_check(name, action.get("args", {}))
            context["policy"] = {"allowed": bool(allowed), "reason": reason[:300]}
            record_stage = self._current_record_policy(context, bool(allowed))
            return {"allowed": bool(allowed), "reason": reason[:300], **record_stage}
        if stage == "act":
            if self.dry_run:
                # Defense in depth: dry-run loops are constructed without an
                # executor, but even if one were attached, this stage must
                # never execute it.
                return {"dry_run": True, "skipped": "dry-run: actions disabled"}
            policy = context.get("policy") or {}
            if not policy.get("allowed"):
                return {"skipped": "policy denied or absent"}
            if self.executor is None:
                return {"skipped": "no executor bound"}
            action = context.get("action") or {}
            result = self.executor(str(action.get("action", "")), action.get("args", {}))
            context["result"] = result
            return {"ok": bool(result.get("ok", True))}
        if stage == "verify":
            action = context.get("action") or {}
            if not str(action.get("action", "")):
                return {"skipped": "no action taken"}
            if self.verify is None:
                return {"verdict": "UNKNOWN", "skipped": True}
            verdict = self.verify(context)
            context["verification"] = verdict
            return {"verdict": str(verdict.get("verdict", "UNKNOWN"))[:32]}
        if stage == "observe":
            if self.observe is None:
                return {"skipped": True}
            observation = self.observe(context)
            context["observation"] = observation
            return {"observed": bool(observation)}
        if stage == "learn":
            if self.learn is None:
                return {"skipped": True}
            update = self.learn(context)
            return {"learned": bool(update)}
        raise ValueError(f"unknown stage: {stage}")

    @staticmethod
    def _current_record_policy(context: dict[str, Any], allowed: bool) -> dict[str, Any]:
        context["policy_allowed"] = allowed
        return {}

    def status(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "total_cycles": self.total_cycles,
            "total_failures": self.total_failures,
            "total_timeouts": self.total_timeouts,
            "history": len(self.history),
            "dry_run": self.dry_run,
        }
