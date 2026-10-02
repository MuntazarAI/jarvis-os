"""DotManager — lifecycle, persistence, event routing, recovery.

The manager never executes tools and never bypasses the Orchestrator or
PolicyEngine. It owns Dot state transitions, durable checkpoints, and
matching relevant events to subscribed Dots.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from ..core.types import TaskState, new_id, now
from .model import (
    DOT_SCHEMA_VERSION,
    Checkpoint,
    Dot,
    DotStatus,
    InvalidTransition,
    validate_transition,
)

TERMINAL_STATES = frozenset(
    {DotStatus.COMPLETED, DotStatus.FAILED, DotStatus.STOPPED})
ACTIVE_STATES = frozenset(
    {DotStatus.RUNNING, DotStatus.WAITING})


@dataclass
class DotDependencies:
    """Live subsystems injected by the loop. All optional except tasks."""

    tasks: Any = None
    palace: Any = None
    world_registry: Any = None
    triggers: Any = None
    store: Any = None  # JsonFileWorldStore-like: save(dict)/load() -> dict
    policy: Any = None


def _scrub(value: Any) -> Any:
    """Remove secret-looking material before persistence."""
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items()
                if "password" not in k.lower()
                and "secret" not in k.lower()
                and "token" not in k.lower()
                and "credential" not in k.lower()}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    if isinstance(value, str) and len(value) > 200:
        return value[:200] + "…[truncated]"
    return value


class DotManager:
    """Central Dot lifecycle owner. No threads, no polling, no execution."""

    def __init__(self, deps: DotDependencies | None = None) -> None:
        self.deps = deps or DotDependencies()
        self.dots: dict[str, Dot] = {}
        # (dot_id, fingerprint) pairs already routed and not yet consumed.
        self._pending: dict[str, str] = {}
        if self.deps.store is not None:
            self.load()

    # -- persistence ---------------------------------------------------
    def persist(self) -> None:
        if self.deps.store is None:
            return
        self.deps.store.save({
            "schema_version": DOT_SCHEMA_VERSION,
            "saved_at": now(),
            "dots": {dot_id: _scrub(dot.to_dict())
                     for dot_id, dot in self.dots.items()},
        })

    def load(self) -> int:
        if self.deps.store is None:
            return 0
        try:
            data = self.deps.store.load()
        except Exception:
            return 0
        if not isinstance(data, dict):
            return 0
        count = 0
        for dot_id, raw in (data.get("dots") or {}).items():
            try:
                dot = Dot.from_dict(raw)
            except Exception:
                continue  # corrupt entry skipped, rest recover
            dot.dot_id = dot_id
            self.dots[dot_id] = dot
            count += 1
        return count

    # -- lifecycle -----------------------------------------------------
    def create(self, name: str, goal: str, role: str = "general",
               description: str = "", priority: int = 5,
               workspace: dict[str, Any] | None = None,
               tools: list[str] | None = None,
               skills: list[str] | None = None,
               permissions: list[str] | None = None,
               trigger_subscriptions: list[str] | None = None) -> Dot:
        dot = Dot(name=name, description=description, role=role, goal=goal,
                  priority=priority, workspace=dict(workspace or {}),
                  tools=list(tools or []), skills=list(skills or []),
                  permissions=list(permissions or []),
                  trigger_subscriptions=list(trigger_subscriptions or []))
        self.dots[dot.dot_id] = dot
        dot.transition(DotStatus.READY)
        self._mirror_world(dot, "created")
        self.persist()
        return dot

    def get(self, dot_id: str) -> Dot | None:
        return self.dots.get(dot_id)

    def list(self) -> list[Dot]:
        return sorted(self.dots.values(),
                      key=lambda d: (-d.priority, d.created_at))

    def inspect(self, dot_id: str) -> dict[str, Any] | None:
        dot = self.dots.get(dot_id)
        if dot is None:
            return None
        data = dot.to_dict()
        data["effective_task_states"] = self._task_states(dot)
        return data

    def start(self, dot_id: str, reason: str = "") -> Dot:
        dot = self._require(dot_id)
        if dot.status == DotStatus.CREATED:
            dot.transition(DotStatus.READY)
        if dot.status in (DotStatus.READY, DotStatus.PAUSED):
            target = DotStatus.RUNNING
        elif dot.status in (DotStatus.WAITING, DotStatus.BLOCKED):
            target = DotStatus.RUNNING
        else:
            raise InvalidTransition(
                f"dot {dot_id} in {dot.status.value} cannot start; "
                f"use recover() for terminal states")
        task = self._ensure_task(dot, reason)
        dot.transition(target)
        dot.metadata["last_start_reason"] = reason
        dot.metadata["active_task_id"] = task.task_id if task else ""
        self._mirror_world(dot, "started")
        self.persist()
        return dot

    def pause(self, dot_id: str) -> Dot:
        dot = self._require(dot_id)
        dot.transition(DotStatus.PAUSED)
        self._pause_tasks(dot)
        self.persist()
        return dot

    def resume(self, dot_id: str, reason: str = "") -> Dot:
        dot = self._require(dot_id)
        if dot.status == DotStatus.PAUSED:
            dot.transition(DotStatus.RUNNING)
        elif dot.status in (DotStatus.READY, DotStatus.WAITING,
                            DotStatus.BLOCKED):
            dot.transition(DotStatus.RUNNING)
        else:
            raise InvalidTransition(
                f"dot {dot_id} in {dot.status.value} cannot resume")
        self._resume_tasks(dot)
        dot.metadata["last_start_reason"] = reason
        self.persist()
        return dot

    def stop(self, dot_id: str, reason: str = "") -> Dot:
        dot = self._require(dot_id)
        if dot.status not in TERMINAL_STATES:
            dot.transition(DotStatus.STOPPED)
        self._cancel_tasks(dot)
        if reason:
            dot.failures.append(f"stopped: {reason}")
        self._mirror_world(dot, "stopped")
        self.persist()
        return dot

    def recover(self, dot_id: str, reason: str = "") -> Dot:
        """Restart a terminal/blocked Dot in a fresh cycle.

        Archives the previous run into metadata, keeps failures visible,
        preserves the checkpoint as last_checkpoint. Never rewrites history.
        """
        dot = self._require(dot_id)
        if dot.status not in TERMINAL_STATES and dot.status != DotStatus.BLOCKED:
            if not self._is_stale(dot):
                raise InvalidTransition(
                    f"dot {dot_id} in {dot.status.value} needs no recovery; "
                    f"use pause/resume instead")
        past = {"status": dot.status.value, "progress": dot.progress,
                "failures": list(dot.failures),
                "checkpoint": dot.checkpoint, "at": now(), "reason": reason}
        dot.metadata.setdefault("past_runs", []).append(_scrub(past))
        dot.failures.clear()
        dot.progress = 0.0
        dot.task_ids = []
        # Fresh cycle from terminal state.
        dot.status = DotStatus.READY
        dot.updated_at = now()
        dot.metadata["recovered_at"] = now()
        dot.metadata["recovery_reason"] = reason
        self._mirror_world(dot, "recovered")
        self.persist()
        return dot

    # -- event routing -------------------------------------------------
    def route_event(self, event: dict[str, Any]) -> list[str]:
        """Match a proactive/normalized event to subscribed Dots.

        Returns dot_ids with a newly queued activation. Dedupe: a Dot that
        is already RUNNING/WAITING, or already has this fingerprint pending,
        does not get a duplicate activation. Events themselves are never
        consumed or deleted.
        """
        etype = str(event.get("type", ""))
        entity = str(event.get("entity", ""))
        summary = str(event.get("summary", ""))
        fingerprint = f"{etype}|{entity}|{summary[:80]}"
        matched: list[str] = []
        for dot in self.dots.values():
            if dot.status in TERMINAL_STATES:
                continue
            if not self._subscribed(dot, etype, entity, summary):
                continue
            key = f"{dot.dot_id}|{fingerprint}"
            if dot.status in ACTIVE_STATES or key in self._pending:
                continue  # already working or already queued: no duplicate
            self._pending[key] = dot.dot_id
            dot.metadata["pending_activation"] = {
                "fingerprint": fingerprint, "event": _scrub(event),
                "at": now()}
            matched.append(dot.dot_id)
        if matched:
            self.persist()
        return matched

    def consume_pending(self, dot_id: str, fingerprint: str) -> bool:
        return self._pending.pop(f"{dot_id}|{fingerprint}", None) is not None

    def pending(self, dot_id: str) -> list[str]:
        """Fingerprints queued for this Dot, oldest first."""
        prefix = f"{dot_id}|"
        return [key[len(prefix):] for key in self._pending
                if key.startswith(prefix)]

    @staticmethod
    def _subscribed(dot: Dot, etype: str, entity: str, summary: str) -> bool:
        if not dot.trigger_subscriptions:
            return False
        haystack = f"{etype} {entity} {summary}".lower()
        return any(sub.lower() in haystack
                   for sub in dot.trigger_subscriptions if sub)

    # -- tasks ---------------------------------------------------------
    def _require(self, dot_id: str) -> Dot:
        dot = self.dots.get(dot_id)
        if dot is None:
            raise KeyError(f"unknown dot: {dot_id}")
        return dot

    def _is_stale(self, dot: Dot) -> bool:
        """An active-status Dot with no live tasks died mid-run (crash,
        kill, restart). That staleness is precisely what recovery heals."""
        if dot.status not in ACTIVE_STATES:
            return False
        tasks = self.deps.tasks
        if tasks is None:
            return True
        for task_id in dot.task_ids:
            task = tasks.tasks.get(task_id)
            if task is not None and task.state not in (
                    TaskState.COMPLETED, TaskState.FAILED,
                    TaskState.CANCELLED):
                return False
        return True

    def _ensure_task(self, dot: Dot, reason: str = ""):
        """Reuse a live owned task, else create one. Never duplicates."""
        tasks = self.deps.tasks
        if tasks is None:
            return None
        for task_id in dot.task_ids:
            task = tasks.tasks.get(task_id)
            if task is not None and task.state not in (
                    TaskState.COMPLETED, TaskState.FAILED,
                    TaskState.CANCELLED):
                return task
        task = tasks.register(dot.goal or dot.name,
                              priority=dot.priority)
        dot.task_ids.append(task.task_id)
        if reason:
            task.history.append({"event": f"dot-owned: {reason}", "at": now()})
        self._mirror_task(dot, task.task_id)
        return task

    def _task_states(self, dot: Dot) -> dict[str, str]:
        tasks = self.deps.tasks
        if tasks is None:
            return {}
        out = {}
        for task_id in dot.task_ids:
            task = tasks.tasks.get(task_id)
            if task is not None:
                out[task_id] = task.state.value
        return out

    def _pause_tasks(self, dot: Dot) -> None:
        tasks = self.deps.tasks
        if tasks is None:
            return
        for task_id in dot.task_ids:
            try:
                tasks.pause(task_id)
            except Exception:
                continue

    def _resume_tasks(self, dot: Dot) -> None:
        tasks = self.deps.tasks
        if tasks is None:
            return
        for task_id in dot.task_ids:
            try:
                tasks.resume(task_id)
            except Exception:
                continue

    def _cancel_tasks(self, dot: Dot) -> None:
        tasks = self.deps.tasks
        if tasks is None:
            return
        for task_id in dot.task_ids:
            try:
                tasks.cancel(task_id)
            except Exception:
                continue

    # -- world mirror --------------------------------------------------
    def _mirror_world(self, dot: Dot, event: str) -> None:
        registry = self.deps.world_registry
        if registry is None:
            return
        try:
            entity, _ = registry.upsert_entity(
                "agent", f"dot:{dot.name}",
                state={"status": dot.status.value, "progress": dot.progress},
                provenance={"observer": "dot-manager", "source": "dots",
                            "event": event},
                confidence=0.9, entity_id=f"agent:dot-{dot.dot_id[:8]}")
            for task_id in dot.task_ids[-3:]:
                try:
                    task_entity, _ = registry.upsert_entity(
                        "task", task_id,
                        provenance={"observer": "dot-manager",
                                    "source": "dots"},
                        confidence=0.7)
                    registry.relate(
                        entity.id, "owns", task_entity.id,
                        provenance={"source": "dots"})
                except Exception:
                    continue
        except Exception:
            pass

    def _mirror_task(self, dot: Dot, task_id: str) -> None:
        registry = self.deps.world_registry
        if registry is None:
            return
        try:
            dot_entity, _ = registry.upsert_entity(
                "agent", f"dot:{dot.name}",
                provenance={"observer": "dot-manager", "source": "dots"},
                confidence=0.9,
                entity_id=f"agent:dot-{dot.dot_id[:8]}")
            task_entity, _ = registry.upsert_entity(
                "task", task_id,
                provenance={"observer": "dot-manager", "source": "dots"},
                confidence=0.7)
            registry.relate(dot_entity.id, "owns", task_entity.id,
                            provenance={"source": "dots"})
        except Exception:
            pass
