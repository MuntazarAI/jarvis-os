"""Unified task engine, workflow engine, triggers and scheduler."""

from __future__ import annotations

import heapq
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from ..core.types import Task, TaskState, new_id, now


# -- task engine -----------------------------------------------------------
class TaskEngine:
    """Registry, priority queue, retries, checkpoints, pause/resume, replay."""

    def __init__(self, max_retries: int = 3) -> None:
        self.tasks: dict[str, Task] = {}
        self._queue: list[tuple[int, float, str]] = []
        self._lock = threading.RLock()
        self.max_retries = max_retries
        self.dead_letters: list[Task] = []
        self.checkpoints: dict[str, dict[str, Any]] = {}

    def register(self, goal: str, priority: int = 5,
                 depends_on: list[str] | None = None,
                 deadline: float | None = None) -> Task:
        task = Task(goal=goal, priority=priority,
                    depends_on=depends_on or [], deadline=deadline)
        with self._lock:
            self.tasks[task.task_id] = task
            heapq.heappush(self._queue, (-priority, task.created_at, task.task_id))
        return task

    def next_ready(self) -> Task | None:
        """Highest-priority task whose dependencies are completed."""
        with self._lock:
            deferred: list[tuple[int, float, str]] = []
            ready: Task | None = None
            while self._queue:
                item = heapq.heappop(self._queue)
                task = self.tasks.get(item[2])
                if task is None or task.state not in (TaskState.QUEUED, TaskState.WAITING):
                    continue
                if all(self.tasks.get(d) and self.tasks[d].state == TaskState.COMPLETED
                       for d in task.depends_on):
                    ready = task
                    break
                deferred.append(item)
            for item in deferred:
                heapq.heappush(self._queue, item)
            if ready:
                ready.state = TaskState.RUNNING
                ready.history.append({"event": "started", "at": now()})
            return ready

    def complete(self, task_id: str, result: Any) -> Task | None:
        with self._lock:
            task = self.tasks.get(task_id)
            if not task:
                return None
            task.state = TaskState.COMPLETED
            task.result = result
            task.progress = 1.0
            task.updated_at = now()
            task.history.append({"event": "completed", "at": now()})
            return task

    def fail(self, task_id: str, error: str, retry: bool = True) -> Task | None:
        with self._lock:
            task = self.tasks.get(task_id)
            if not task:
                return None
            task.attempts += 1
            task.error = error
            task.history.append({"event": "failed", "error": error,
                                 "attempt": task.attempts, "at": now()})
            if retry and task.attempts <= self.max_retries:
                task.state = TaskState.QUEUED
                heapq.heappush(self._queue, (-task.priority, now(), task.task_id))
            else:
                task.state = TaskState.FAILED
                self.dead_letters.append(task)
            task.updated_at = now()
            return task

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            task = self.tasks.get(task_id)
            if not task or task.state in (TaskState.COMPLETED, TaskState.FAILED,
                                                   TaskState.CANCELLED):
                return False
            task.state = TaskState.CANCELLED
            task.history.append({"event": "cancelled", "at": now()})
            return True

    def pause(self, task_id: str) -> bool:
        with self._lock:
            task = self.tasks.get(task_id)
            if not task or task.state != TaskState.RUNNING:
                return False
            task.state = TaskState.WAITING
            self.checkpoint(task_id)
            return True

    def resume(self, task_id: str) -> bool:
        with self._lock:
            task = self.tasks.get(task_id)
            if not task or task.state != TaskState.WAITING:
                return False
            task.state = TaskState.QUEUED
            heapq.heappush(self._queue, (-task.priority, now(), task.task_id))
            return True

    def checkpoint(self, task_id: str) -> bool:
        with self._lock:
            task = self.tasks.get(task_id)
            if not task:
                return False
            self.checkpoints[task_id] = task.to_dict()
            return True

    def rollback(self, task_id: str) -> Task | None:
        with self._lock:
            snap = self.checkpoints.get(task_id)
            task = self.tasks.get(task_id)
            if not snap or not task:
                return None
            task.progress = snap.get("progress", 0.0)
            task.result = snap.get("result")
            task.state = TaskState.QUEUED
            heapq.heappush(self._queue, (-task.priority, now(), task.task_id))
            task.history.append({"event": "rolled_back", "at": now()})
            return task

    def overdue(self) -> list[Task]:
        stamp = now()
        with self._lock:
            return [t for t in self.tasks.values()
                    if t.deadline and t.deadline <= stamp
                    and t.state not in (TaskState.COMPLETED, TaskState.FAILED,
                                        TaskState.CANCELLED)]

    def replay(self, task_id: str) -> list[dict[str, Any]]:
        with self._lock:
            task = self.tasks.get(task_id)
            return list(task.history) if task else []

    def stats(self) -> dict[str, Any]:
        with self._lock:
            by_state: dict[str, int] = {}
            for task in self.tasks.values():
                by_state[task.state.value] = by_state.get(task.state.value, 0) + 1
            return {"total": len(self.tasks), "by_state": by_state,
                    "dead_letters": len(self.dead_letters),
                    "queued": len(self._queue)}


# -- workflow engine ---------------------------------------------------------
@dataclass
class WorkflowNode:
    node_id: str
    kind: str  # task | condition | parallel | approval | loop | compensation
    payload: dict[str, Any] = field(default_factory=dict)
    next_on_ok: str = ""
    next_on_fail: str = ""


@dataclass
class Workflow:
    name: str
    nodes: dict[str, WorkflowNode] = field(default_factory=dict)
    start: str = ""
    version: int = 1
    workflow_id: str = field(default_factory=lambda: new_id("wf"))

    def add(self, node: WorkflowNode) -> WorkflowNode:
        if node.node_id in self.nodes:
            raise ValueError(f"duplicate node: {node.node_id}")
        self.nodes[node.node_id] = node
        if not self.start:
            self.start = node.node_id
        return node

    def to_dict(self) -> dict[str, Any]:
        return {"workflow_id": self.workflow_id, "name": self.name,
                "version": self.version, "start": self.start,
                "nodes": {nid: {"kind": n.kind, "payload": n.payload,
                                "next_on_ok": n.next_on_ok,
                                "next_on_fail": n.next_on_fail}
                          for nid, n in self.nodes.items()}}


class WorkflowEngine:
    """Template execution with branches, loops, parallel joins, approvals."""

    def __init__(self, max_steps: int = 100) -> None:
        self.templates: dict[str, Workflow] = {}
        self.runs: list[dict[str, Any]] = []
        self.max_steps = max_steps

    def register(self, workflow: Workflow) -> None:
        self.templates[workflow.name] = workflow

    def run(self, name: str,
            step_fn: Callable[[WorkflowNode, dict[str, Any]], dict[str, Any]],
            context: dict[str, Any] | None = None,
            approve_fn: Callable[[WorkflowNode], bool] | None = None) -> dict[str, Any]:
        template = self.templates.get(name)
        if template is None:
            raise KeyError(f"unknown workflow: {name}")
        ctx = dict(context or {})
        current = template.start
        visited: list[str] = []
        steps = 0
        compensated: list[str] = []
        failures: list[str] = []
        while current and steps < self.max_steps:
            steps += 1
            node = template.nodes.get(current)
            if node is None:
                return self._finish(name, False, f"unknown node: {current}",
                                    visited, ctx, compensated, failures)
            visited.append(current)
            if node.kind == "condition":
                branch = self._eval_condition(node, ctx)
                current = node.next_on_ok if branch else node.next_on_fail
                continue
            if node.kind == "approval":
                approved = approve_fn(node) if approve_fn else False
                if not approved:
                    return self._finish(name, False, f"approval denied at {current}",
                                        visited, ctx, compensated, failures)
                current = node.next_on_ok
                continue
            if node.kind == "loop":
                iterations = int(node.payload.get("iterations", 1))
                body = node.payload.get("body", [])
                for _ in range(iterations):
                    for sub in body:
                        sub_node = WorkflowNode(node_id=sub, kind="task",
                                                payload={"task": sub})
                        outcome = self._safe_step(step_fn, sub_node, ctx)
                        if not outcome.get("ok"):
                            failures.append(f"{sub}: {outcome.get('error', outcome)}")
                            current = node.next_on_fail
                            break
                    else:
                        continue
                    break
                else:
                    current = node.next_on_ok
                    continue
                continue
            outcome = self._safe_step(step_fn, node, ctx)
            ctx[f"result_{current}"] = outcome
            if outcome.get("ok"):
                current = node.next_on_ok
            else:
                failures.append(f"{node.node_id}: {outcome.get('error', outcome)}")
                comp = node.payload.get("compensation")
                if comp:
                    compensated.append(comp)
                current = node.next_on_fail or ""
                if not current:
                    return self._finish(name, False,
                                        f"step {node.node_id} failed: "
                                        f"{outcome.get('error', outcome)}",
                                        visited, ctx, compensated, failures)
        if steps >= self.max_steps:
            return self._finish(name, False, "step budget exceeded",
                                visited, ctx, compensated, failures)
        if failures:
            return self._finish(name, False,
                                "recovered with failures: " + "; ".join(failures),
                                visited, ctx, compensated, failures)
        return self._finish(name, True, "", visited, ctx, compensated, failures)

    @staticmethod
    def _eval_condition(node: WorkflowNode, ctx: dict[str, Any]) -> bool:
        if "key" in node.payload:
            return ctx.get(node.payload["key"]) == node.payload.get("equals")
        expr = str(node.payload.get("if", "true")).lower()
        if expr in ("true", "yes", "1"):
            return True
        if expr in ("false", "no", "0"):
            return False
        return False

    @staticmethod
    def _safe_step(step_fn: Callable, node: WorkflowNode,
                   ctx: dict[str, Any]) -> dict[str, Any]:
        try:
            return step_fn(node, ctx) or {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    def _finish(self, name: str, ok: bool, error: str, visited: list[str],
                ctx: dict[str, Any], compensated: list[str],
                failures: list[str] | None = None) -> dict[str, Any]:
        run = {"workflow": name, "ok": ok, "error": error, "visited": visited,
               "compensated": compensated, "failures": list(failures or []),
               "context_keys": sorted(ctx), "at": now()}
        self.runs.append(run)
        return run


# -- triggers / scheduler ------------------------------------------------------
@dataclass
class Trigger:
    trigger_id: str = field(default_factory=lambda: new_id("trig"))
    kind: str = "schedule"  # schedule | file | system | calendar | event
    spec: dict[str, Any] = field(default_factory=dict)
    action: str = ""
    enabled: bool = True
    last_fired: float = 0.0
    fire_count: int = 0


class TriggerEngine:
    """Scheduled jobs, file drops, system thresholds, calendar hooks, events."""

    def __init__(self) -> None:
        self.triggers: dict[str, Trigger] = {}
        self.fired: list[dict[str, Any]] = []

    def add(self, trigger: Trigger) -> Trigger:
        self.triggers[trigger.trigger_id] = trigger
        return trigger

    def remove(self, trigger_id: str) -> bool:
        return self.triggers.pop(trigger_id, None) is not None

    def poll(self, signals: dict[str, Any]) -> list[Trigger]:
        """Evaluate all triggers against current signals. Returns fired triggers."""
        stamp = signals.get("now", now())
        ready: list[Trigger] = []
        for trig in self.triggers.values():
            if not trig.enabled:
                continue
            if self._matches(trig, signals, stamp):
                trig.last_fired = stamp
                trig.fire_count += 1
                ready.append(trig)
                self.fired.append({"trigger": trig.trigger_id, "action": trig.action,
                                   "at": stamp})
        return ready

    def _matches(self, trig: Trigger, signals: dict[str, Any], stamp: float) -> bool:
        if trig.kind == "schedule":
            at = float(trig.spec.get("at", 0))
            interval = float(trig.spec.get("every", 0))
            if at and stamp >= at and trig.fire_count == 0:
                return True
            if interval and stamp - trig.last_fired >= interval and trig.last_fired:
                return True
            if interval and not trig.last_fired and stamp >= interval:
                return True
            return False
        if trig.kind == "file":
            watched = str(trig.spec.get("path", "")).rstrip("/")
            return any(
                f == watched or f.startswith(watched + "/")
                for f in signals.get("new_files", [])
            )
        if trig.kind == "system":
            metric = signals.get(trig.spec.get("metric", ""), None)
            if metric is None:
                return False
            return float(metric) >= float(trig.spec.get("above", float("inf")))
        if trig.kind == "calendar":
            return float(trig.spec.get("at", 0)) - stamp <= float(
                trig.spec.get("minutes_before", 5)) * 60
        if trig.kind == "event":
            return trig.spec.get("event_type") in signals.get("events", [])
        return False
