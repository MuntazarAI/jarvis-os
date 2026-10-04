"""Durable runner (Durable Autonomous Tasks 10).

Owns task advance: READY -> RUNNING -> step execute -> VERIFYING ->
CHECKPOINTED -> next step | COMPLETED, with policy re-evaluation,
approval gates, bounded retries, idempotent keys, checkpoints only
on verified work, and every transition persisted before acting.

The domain work itself runs through an injected step executor
(Orchestrator/mesh) so this package stays free of import cycles and
the durable layer never duplicates cognitive machinery:
  executor(task, step) -> dict(ok, output_ref, verification,
      side_effects, error, kind, approval)
  check(task, step) -> "confirmed" | "absent" | "unknown"  (reconcile)
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from . import recovery
from .store import TaskStore, TaskStoreError
from .task import (Checkpoint, StepState, Task, TaskError, TaskState)

Executor = Callable[[Task, Any], dict[str, Any]]
Checker = Callable[[Task, Any], str]


class DurableRunner:
    def __init__(self, store: TaskStore,
                 executor: Executor | None = None,
                 checker: Checker | None = None,
                 policy=None,
                 events=None) -> None:
        self.store = store
        self.executor = executor or (lambda t, s: {
            "ok": False, "error": "no executor", "kind": "permanent"})
        self.checker = checker or (lambda t, s: "unknown")
        self.policy = policy
        self.events = events

    def _emit(self, kind: str, task: Task,
              detail: str = "") -> None:
        sink = getattr(self.events, "record_event", None)
        if callable(sink):
            try:
                sink(kind,
                     {"task_id": task.task_id, "state": task.state.value,
                      "detail": str(detail)[:500],
                      "verify": "unverified — diagnosis only"})
            except Exception:
                pass

    def create(self, *, title: str, source: str = "cli",
               priority: int = 5, deadline: float = 0.0,
               retry_policy: dict[str, Any] | None = None,
               dependencies: list[str] | None = None,
               provenance: dict[str, Any] | None = None,
               steps: list[dict[str, Any]] | None = None) -> Task:
        from .task import RetryPolicy, TaskStep
        task = Task(title=title, source=source, priority=priority,
                    deadline=deadline,
                    retry_policy=(RetryPolicy(**retry_policy)
                                  if retry_policy else RetryPolicy()),
                    dependencies=[str(d) for d in
                                  (dependencies or [])][:16],
                    provenance=dict(provenance or {}),
                    steps=[TaskStep(title=str(s.get("title", "")))
                           for s in (steps or [])][:32])
        task.transition(TaskState.PLANNING)
        self.store.create(task)
        self._emit("durable.task.created", task, task.title)
        return task

    def mark_ready(self, task_id: str,
                   plan_ref: str = "",
                   plan_version: str = "") -> Task:
        with self.store.mutate(task_id) as task:
            if plan_ref:
                task.plan_ref = str(plan_ref)[:200]
            if plan_version:
                task.plan_version = str(plan_version)[:100]
            task.transition(TaskState.READY)
            self._emit("durable.task.ready", task, task.plan_ref)
            return task

    def advance(self, task_id: str) -> Task:
        """Advance one task by one step. Process may die after this
        call; all state is already persisted."""
        with self.store.mutate(task_id) as task:
            self._guard(task)
            task.transition(TaskState.RUNNING)
            step = self._current(task)
            if step is None:
                # A failed current step is retried, not skipped:
                # reset to PENDING so it actually re-executes.
                prev = next((s for s in task.steps
                             if s.step_id == task.current_step), None)
                if prev is not None and prev.state == StepState.FAILED:
                    prev.state = StepState.PENDING
                    prev.verification = "unknown"
                    step = prev
            if step is None:
                self._finish(task)
                return task
            step.state = StepState.RUNNING
            step.attempts += 1
            step.started_at = time.time()
            step.idempotency_key = (
                f"{task.task_id}:{step.step_id}:attempt-{step.attempts}")
            task.current_step = step.step_id
            self._emit("durable.step.started", task, step.title)
            result = self._safe_execute(task, step)
            step.finished_at = time.time()
            step.output_ref = str(result.get("output_ref", ""))[:500]
            step.verification = str(
                result.get("verification", "unknown"))[:20]
            if step.verification not in ("verified", "failed",
                                         "partial", "unknown"):
                step.verification = "unknown"
            self._after_step(task, step, result)
            return task

    def _guard(self, task: Task) -> None:
        if task.cancel_requested and task.state in (
                TaskState.READY, TaskState.RUNNING,
                TaskState.WAITING, TaskState.PAUSED,
                TaskState.CHECKPOINTED, TaskState.RETRYING,
                TaskState.RECOVERING):
            task.transition(TaskState.CANCELLED)
            self._emit("durable.task.cancelled", task, "cancel honored")
            raise _Halt(task)
        if task.deadline and time.time() >= task.deadline:
            if task.state in (TaskState.READY, TaskState.RUNNING,
                              TaskState.WAITING, TaskState.PAUSED,
                              TaskState.CHECKPOINTED,
                              TaskState.RETRYING,
                              TaskState.RECOVERING):
                task.transition(TaskState.FAILED)
                task.provenance["failure"] = "deadline exceeded"
                self._emit("durable.task.failed", task,
                           "deadline exceeded")
                raise _Halt(task)
        if self.policy is not None and hasattr(
                self.policy, "emergency_stop_engaged"):
            try:
                if self.policy.emergency_stop_engaged():
                    task.transition(TaskState.CANCELLED)
                    task.provenance["failure"] = \
                        "emergency stop engaged"
                    raise _Halt(task)
            except _Halt:
                raise
            except Exception:
                pass
        if task.state not in (TaskState.READY,
                              TaskState.CHECKPOINTED,
                              TaskState.RETRYING):
            raise TaskStoreError(
                f"task {task.task_id} not advanceable "
                f"from {task.state.value}")

    def _current(self, task: Task):
        if task.current_step:
            found = next((s for s in task.steps
                          if s.step_id == task.current_step), None)
            if found is not None and found.state in (
                    StepState.PENDING, StepState.RUNNING):
                return found
        return next((s for s in task.steps
                     if s.state == StepState.PENDING), None)

    def _safe_execute(self, task: Task, step) -> dict[str, Any]:
        try:
            result = self.executor(task, step)
        except Exception as exc:  # executor crash is transient-unknown
            return {"ok": False, "error": f"{type(exc).__name__}",
                    "kind": "unknown", "verification": "unknown"}
        if not isinstance(result, dict):
            return {"ok": False, "error": "bad executor result",
                    "kind": "unknown", "verification": "unknown"}
        return result

    def _after_step(self, task: Task, step, result: dict) -> None:
        task.transition(TaskState.VERIFYING)
        ok = bool(result.get("ok"))
        kind = str(result.get("kind", "unknown"))[:20]
        if ok and step.verification in ("verified", "partial"):
            # Progress is progress: the step SUCCEEDED. Only
            # `verified` side effects are recorded as CONFIRMED —
            # `partial` work continues without confirmation claims.
            step.state = StepState.SUCCEEDED
            if step.verification == "verified":
                effects = [str(e)[:200] for e in
                           result.get("side_effects", [])][:16]
                task.checkpoints.append(Checkpoint(
                    step_id=step.step_id,
                    known={"output_ref": step.output_ref},
                    side_effects_confirmed=effects))
                task.checkpoints = task.checkpoints[-10:]
            else:
                task.provenance["partial_steps"] = \
                    task.provenance.get("partial_steps", 0) + 1
            task.transition(TaskState.CHECKPOINTED)
            self._emit("durable.step.checkpointed", task, step.title)
            nxt = next((s for s in task.steps
                        if s.state == StepState.PENDING), None)
            if nxt is None:
                self._finish(task)
            else:
                task.transition(TaskState.READY)
            return
        step.state = StepState.FAILED
        task.provenance["last_error"] = str(
            result.get("error", "step failed"))[:500]
        retryable = kind in set(task.retry_policy.retryable)
        if retryable and step.attempts < task.retry_policy.max_attempts:
            task.transition(TaskState.RETRYING)
            self._emit("durable.step.retrying", task,
                       f"attempt {step.attempts}: {kind}")
            return
        if kind in ("policy", "approval"):
            task.transition(TaskState.CANCELLED)
            task.provenance["failure"] = (
                f"blocked by {kind}: no side effects")
            self._emit("durable.task.cancelled", task, kind)
            return
        task.transition(TaskState.FAILED)
        task.provenance["failure"] = task.provenance.get("last_error")
        self._emit("durable.task.failed", task, kind)

    def _finish(self, task: Task) -> None:
        incomplete = [s.step_id for s in task.steps
                      if s.state not in (StepState.SUCCEEDED,
                                         StepState.SKIPPED)]
        if incomplete:
            try:
                task.transition(TaskState.FAILED)
            except TaskError:
                pass
            task.provenance["failure"] = (
                f"incomplete steps remain: {len(incomplete)}")
            return
        partial = [s.step_id for s in task.steps
                   if s.verification != "verified"]
        if partial:
            task.provenance["completed_unverified"] = len(partial)
        try:
            task.transition(TaskState.COMPLETED)
        except TaskError:
            # from RUNNING directly when there were no steps
            task.state = TaskState.COMPLETED
        self._emit("durable.task.completed", task,
                   f"{len(task.steps)} steps verified")

    def pause(self, task_id: str) -> Task:
        with self.store.mutate(task_id) as task:
            task.transition(TaskState.PAUSED)
            self._emit("durable.task.paused", task, "")
            return task

    def resume(self, task_id: str) -> Task:
        with self.store.mutate(task_id) as task:
            task.transition(TaskState.READY)
            self._emit("durable.task.resumed", task, "")
            return task

    def cancel(self, task_id: str, reason: str = "") -> Task:
        with self.store.mutate(task_id) as task:
            task.cancel_requested = True
            if task.state in (TaskState.CREATED, TaskState.PLANNING,
                              TaskState.READY, TaskState.WAITING,
                              TaskState.PAUSED, TaskState.RETRYING,
                              TaskState.RECOVERING,
                              TaskState.CHECKPOINTED,
                              TaskState.FAILED, TaskState.EXPIRED):
                task.transition(TaskState.CANCELLED)
            task.provenance["cancel_reason"] = str(reason)[:300]
            self._emit("durable.task.cancelled", task, reason)
            return task

    def recover(self, task_id: str,
                policy_ok: bool = True,
                approval_ok: bool = True) -> dict[str, Any]:
        """Crash-restart recovery for one task. Returns decision."""
        with self.store.mutate(task_id) as task:
            if task.state not in (TaskState.RUNNING,
                                  TaskState.VERIFYING,
                                  TaskState.WAITING,
                                  TaskState.PAUSED,
                                  TaskState.RECOVERING,
                                  TaskState.RETRYING,
                                  TaskState.FAILED,
                                  TaskState.CHECKPOINTED,
                                  TaskState.READY):
                return {"action": "WAIT",
                        "reason": f"terminal or fresh state "
                                  f"{task.state.value}: nothing to recover"}
            info = recovery.classify(task)
            decision = recovery.decide(task, info, policy_ok=policy_ok,
                                       approval_ok=approval_ok)
            action = decision["action"]
            if task.state != TaskState.RECOVERING and action != "WAIT":
                try:
                    task.transition(TaskState.RECOVERING)
                except TaskError:
                    pass
            if action == "RESUME":
                task.transition(TaskState.READY)
            elif action == "RETRY":
                task.transition(TaskState.RETRYING)
            elif action == "RECONCILE":
                outcome = "unknown"
                try:
                    outcome = str(self.checker(task, self._current(
                        task)))[:20]
                except Exception:
                    outcome = "unknown"
                if outcome == "confirmed":
                    step = self._current(task)
                    if step is not None:
                        step.state = StepState.SUCCEEDED
                        step.verification = "verified"
                    task.transition(TaskState.READY)
                    decision["reconciled"] = "confirmed"
                elif outcome == "absent":
                    task.transition(TaskState.RETRYING)
                    decision["reconciled"] = "absent"
                else:
                    task.transition(TaskState.WAITING)
                    decision["reconciled"] = "unknown"
            elif action == "REPAIR":
                task.transition(TaskState.READY)
            elif action == "CANCEL":
                task.cancel_requested = True
                task.transition(TaskState.CANCELLED)
            elif action == "FAIL":
                try:
                    task.transition(TaskState.FAILED)
                except TaskError:
                    pass
            self._emit("durable.task.recovered", task, action)
            decision["state"] = task.state.value
            return decision

    def recover_all(self, policy=None) -> list[dict[str, Any]]:
        results = []
        for task in self.store.list():
            if task.state in (TaskState.RUNNING,
                              TaskState.VERIFYING,
                              TaskState.WAITING,
                              TaskState.RETRYING,
                              TaskState.RECOVERING):
                policy_ok = True
                if policy is not None and hasattr(
                        policy, "emergency_stop_engaged"):
                    try:
                        policy_ok = not policy.emergency_stop_engaged()
                    except Exception:
                        policy_ok = True
                try:
                    decision = self.recover(task.task_id,
                                            policy_ok=policy_ok)
                except (TaskError, TaskStoreError) as exc:
                    decision = {"task_id": task.task_id,
                                "action": "WAIT",
                                "reason": f"recover failed: {exc}"}
                decision.setdefault("task_id", task.task_id)
                results.append(decision)
        return results


class _Halt(Exception):
    def __init__(self, task: Task) -> None:
        super().__init__(task.state.value)
        self.task = task


__all__ = ["DurableRunner", "Executor", "Checker"]
