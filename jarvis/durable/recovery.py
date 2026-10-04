"""Recovery engine (Durable Autonomous Tasks 1.0).

Evidence-based recovery decisions. Every decision is deterministic,
explained, and persisted into the task provenance trail. The engine
never assumes success: unknown stays unknown until verification or
safe re-execution resolves it.
"""

from __future__ import annotations

import time
from typing import Any

from .task import StepState, Task, TaskState

DECISIONS = ("RESUME", "RETRY", "RECONCILE", "REPAIR", "WAIT",
             "CANCEL", "FAIL")


def classify(task: Task, *, now: float = 0.0,
             emergency: bool = False) -> dict[str, Any]:
    """Inspect durable state and report the situation. Pure function."""
    stamp = now or time.time()
    step = next((s for s in task.steps
                 if s.step_id == task.current_step), None)
    info: dict[str, Any] = {
        "task_id": task.task_id, "state": task.state.value,
        "cancel_requested": task.cancel_requested,
        "emergency": emergency,
        "deadline_exceeded": bool(task.deadline and
                                  stamp >= task.deadline),
        "step_id": step.step_id if step else "",
        "step_state": step.state.value if step else "none",
        "attempts": step.attempts if step else 0,
        "verification": step.verification if step else "unknown",
        "has_checkpoint": bool(task.checkpoints),
    }
    return info


def decide(task: Task, info: dict[str, Any],
           policy_ok: bool = True,
           approval_ok: bool = True) -> dict[str, Any]:
    """Choose RESUME/RETRY/RECONCILE/REPAIR/WAIT/CANCEL/FAIL."""
    if info["cancel_requested"]:
        return _decision(task, "CANCEL", "cancellation requested")
    if info["emergency"]:
        return _decision(task, "CANCEL",
                         "emergency stop: no side effects")
    if info["deadline_exceeded"]:
        return _decision(task, "FAIL", "deadline exceeded")
    if not policy_ok:
        return _decision(task, "FAIL", "policy denies recovery")
    if not approval_ok:
        return _decision(task, "WAIT", "approval required")
    verification = info["verification"]
    if verification == "verified":
        return _decision(task, "RESUME",
                         "last step verified: continue")
    if verification in ("failed", "partial"):
        return _decision(task, "RETRY",
                         f"last step {verification}: bounded retry")
    # Unknown: reconcile when a side effect may have happened.
    step_state = info["step_state"]
    attempts = info["attempts"]
    if step_state in ("running",) or attempts > 0:
        return _decision(task, "RECONCILE",
                         "outcome unknown after attempt: verify "
                         "external state first")
    return _decision(task, "RESUME", "no attempts yet: start clean")


def _decision(task: Task, action: str, reason: str) -> dict[str, Any]:
    record = {"action": action, "reason": reason,
              "at": time.time(), "state": task.state.value}
    trail = task.provenance.get("recovery_log")
    if not isinstance(trail, list):
        trail = []
    trail.append(record)
    task.provenance["recovery_log"] = trail[-20:]
    return record


__all__ = ["classify", "decide", "DECISIONS"]
