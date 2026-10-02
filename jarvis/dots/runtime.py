"""Dot runtime — one bounded activation of a persistent Dot.

Flow per activation:
  emergency-stop check → load state → find or create TaskEngine task →
  validate workspace paths → scan event content for injections →
  Orchestrator.run (existing budgets/policy/approvals) →
  record evidence → update progress → checkpoint → persist.

The runtime never executes tools itself, never approves anything, and
never spawns threads. Uncertain or interrupted work is recorded as
uncertain/failed — never as completed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from ..core.types import TaskState, now
from .manager import DotManager
from .model import Checkpoint, Dot, DotStatus

ROLE_TEAMS = {
    "coder": "coding",
    "coding": "coding",
    "researcher": "research",
    "research": "research",
    "debugger": "debugging",
    "debugging": "debugging",
    "computer": "computer",
    "analyst": "decision",
    "planner": "decision",
}


@dataclass
class RuntimeContext:
    """Live subsystems for one activation. Orchestrator is required."""

    orchestrator: Any = None
    tasks: Any = None
    palace: Any = None
    world_registry: Any = None
    policy: Any = None


@dataclass
class ActivationResult:
    dot_id: str
    outcome: str  # completed | waiting | blocked | needs_approval | failed
    reason: str = ""
    task_id: str = ""
    task_state: str = ""
    evidence_refs: list[str] = field(default_factory=list)
    trace_refs: list[str] = field(default_factory=list)
    uncertain: bool = False
    at: float = field(default_factory=now)

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def _workspace_allows(workspace: dict[str, Any], text: str) -> tuple[bool, str]:
    """Refuse goals referencing absolute paths outside the Dot workspace."""
    root = (workspace or {}).get("root", "")
    if not root:
        return True, ""
    import re
    for path in re.findall(r"(?<![\w~])/(?:[\w.\-]+/)*[\w.\-]+", text):
        try:
            if os.path.commonpath([root, path]) != root:
                return False, f"path outside workspace: {path}"
        except ValueError:
            return False, f"unresolvable path: {path}"
    return True, ""


def _scan_event_content(event: dict[str, Any]) -> tuple[bool, str]:
    """Injection scan on the triggering event. Untrusted ≠ executable."""
    try:
        from ..security.guards import scan_injection
    except Exception:
        return True, ""
    text = f"{event.get('summary', '')} {event.get('entity', '')}"
    result = scan_injection(text)
    if not result.get("clean", True):
        return False, f"injection markers in trigger: {result.get('verdict')}"
    return True, ""


class DotRuntime:
    """Executes one bounded Dot activation."""

    def __init__(self, manager: DotManager) -> None:
        self.manager = manager

    def activate(self, dot: Dot, reason: str, ctx: RuntimeContext,
                 event: dict[str, Any] | None = None,
                 max_tool_calls: int = 6,
                 max_runtime_s: float = 90.0) -> ActivationResult:
        """Run one activation. Returns an outcome; persists a checkpoint."""
        deps = self.manager.deps
        policy = ctx.policy or getattr(deps, "policy", None)
        if policy is not None:
            try:
                if policy._emergency_stop():
                    return self._finish(
                        dot, "blocked", "emergency stop engaged",
                        task_id="", uncertain=False)
            except Exception:
                pass
        if ctx.orchestrator is None:
            return self._finish(dot, "failed",
                                "no orchestrator bound", uncertain=False)
        allowed, why = _workspace_allows(dot.workspace, dot.goal)
        if not allowed:
            return self._finish(dot, "blocked", why, uncertain=False)
        if event is not None:
            clean, why_scan = _scan_event_content(event)
            if not clean:
                return self._finish(dot, "blocked", why_scan, uncertain=False)
        task = self._active_task(dot, ctx, reason)
        if task is None:
            return self._finish(dot, "failed",
                                "no TaskEngine available", uncertain=False)
        team = ROLE_TEAMS.get((dot.role or "").lower())
        try:
            from ..agents.orchestrator import Budgets
            budgets = Budgets(max_agents=4, max_tool_calls=max_tool_calls,
                              max_runtime_s=max_runtime_s)
        except Exception:
            budgets = None
        try:
            out = ctx.orchestrator.run(
                dot.goal, team=team, depth=2, task_id=task.task_id,
                budgets=budgets, parent_id=dot.dot_id)
        except Exception as exc:
            return self._finish(dot, "failed",
                                f"orchestrator error: {type(exc).__name__}: {exc}",
                                task_id=task.task_id, uncertain=True)
        return self._settle(dot, task.task_id, out, ctx)

    # -- internals ---------------------------------------------------
    def _active_task(self, dot: Dot, ctx: RuntimeContext, reason: str):
        tasks = ctx.tasks or getattr(self.manager.deps, "tasks", None)
        if tasks is None:
            return None
        for task_id in dot.task_ids:
            task = tasks.tasks.get(task_id)
            if task is not None and task.state not in (
                    TaskState.COMPLETED, TaskState.FAILED,
                    TaskState.CANCELLED):
                return task
        task = tasks.register(dot.goal or dot.name, priority=dot.priority)
        dot.task_ids.append(task.task_id)
        if reason:
            task.history.append(
                {"event": f"dot-owned: {reason}", "at": now()})
        return task

    def _settle(self, dot: Dot, task_id: str, out: dict[str, Any],
                ctx: RuntimeContext) -> ActivationResult:
        evidence = self._collect_evidence(out)
        trace_refs = []
        if out.get("run_id"):
            trace_refs.append(str(out["run_id"]))
        if task_id:
            trace_refs.append(task_id)
        dot.evidence_refs.extend(
            ref for ref in evidence if ref not in dot.evidence_refs)
        dot.trace_refs.extend(
            ref for ref in trace_refs if ref not in dot.trace_refs)
        failure = str(out.get("failure", "") or "")
        ok = bool(out.get("ok", False))
        needs_approval = "approval" in failure.lower()
        tasks = ctx.tasks or getattr(self.manager.deps, "tasks", None)
        task_state = ""
        if tasks is not None:
            task = tasks.tasks.get(task_id)
            if task is not None:
                task_state = task.state.value
        if needs_approval:
            outcome, target = "needs_approval", DotStatus.NEEDS_APPROVAL
        elif ok:
            outcome, target = "completed", DotStatus.COMPLETED
            dot.progress = 1.0
        elif task_state in ("waiting", "blocked"):
            outcome, target = "waiting", DotStatus.WAITING
        elif "uncertain" in failure.lower() or not failure:
            outcome, target = "blocked", DotStatus.BLOCKED
        else:
            outcome, target = "failed", DotStatus.FAILED
        if outcome == "failed":
            dot.failures.append(failure or "orchestrator reported failure")
        try:
            dot.transition(target)
        except Exception:
            # Status already terminal (e.g. checkpointed earlier): record
            # the outcome without rewriting lifecycle history.
            pass
        self._checkpoint(dot, task_id, task_state, outcome,
                         evidence, trace_refs, failure,
                         uncertain=(outcome in ("failed", "blocked")
                                    and not failure))
        self._remember(dot, ctx, outcome, failure, evidence)
        self.manager.persist()
        return ActivationResult(
            dot_id=dot.dot_id, outcome=outcome,
            reason=failure or f"dot {target.value}",
            task_id=task_id, task_state=task_state,
            evidence_refs=list(dot.evidence_refs[-8:]),
            trace_refs=list(dot.trace_refs[-8:]),
            uncertain=(outcome in ("failed", "blocked") and not failure))

    def _finish(self, dot: Dot, outcome: str, reason: str,
                task_id: str = "", uncertain: bool = False) -> ActivationResult:
        self._checkpoint(dot, task_id, "", outcome, [], [], reason,
                         uncertain=uncertain)
        self.manager.persist()
        return ActivationResult(dot_id=dot.dot_id, outcome=outcome,
                                reason=reason, task_id=task_id,
                                uncertain=uncertain)

    def _collect_evidence(self, out: dict[str, Any]) -> list[str]:
        refs: list[str] = []
        result = out.get("result") or {}
        if isinstance(result, dict):
            for key in ("evidence", "citations", "artifacts"):
                value = result.get(key)
                if isinstance(value, list):
                    refs.extend(str(v)[:160] for v in value[:8])
        for conflict in out.get("conflicts", []) or []:
            refs.append(f"conflict: {str(conflict)[:120]}")
        return refs

    def _checkpoint(self, dot: Dot, task_id: str, task_state: str,
                    outcome: str, evidence: list[str], traces: list[str],
                    failure: str, uncertain: bool) -> Checkpoint:
        checkpoint = Checkpoint(
            dot_id=dot.dot_id, status=dot.status.value, task_id=task_id,
            task_state=task_state,
            completed_work=[f"activation outcome: {outcome}"],
            pending_work=[] if outcome == "completed" else [dot.goal],
            evidence_refs=list(evidence[-8:]),
            operation_refs=list(traces[-8:]),
            budgets={"max_tool_calls": 6},
            failures=[failure] if failure else [],
            uncertain=uncertain)
        dot.checkpoint = checkpoint.to_dict()
        return checkpoint

    def _remember(self, dot: Dot, ctx: RuntimeContext, outcome: str,
                  failure: str, evidence: list[str]) -> None:
        palace = ctx.palace or getattr(self.manager.deps, "palace", None)
        if palace is None:
            return
        try:
            if outcome == "completed":
                mem = palace.store_fact(
                    f"dot {dot.name} completed: {dot.goal[:120]}",
                    source="dots", importance=0.6,
                    metadata={"dot_id": dot.dot_id, "origin": "system"})
            else:
                mem = palace.remember(
                    f"dot {dot.name} activation {outcome}: "
                    f"{(failure or dot.goal)[:120]}",
                    tier="short_term", source="dots", importance=0.4,
                    metadata={"dot_id": dot.dot_id, "origin": "system"})
            dot.memory_refs.append(mem.id)
        except Exception:
            pass
