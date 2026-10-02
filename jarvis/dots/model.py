"""Dots 3.1 — persistent responsibility owners.

A Dot is NOT an agent and NOT a task:
- Agent  = capability/worker role (orchestrated per activation)
- Task   = one unit of work (TaskEngine)
- Goal   = desired persistent outcome (memory tier goal)
- Dot    = persistent owner of a responsibility across sessions

A Dot survives restarts via checkpointed JSON state and is awakened by
relevant events, never by polling loops or background threads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..core.types import new_id, now

DOT_SCHEMA_VERSION = 1


class DotStatus(str, Enum):
    CREATED = "created"
    READY = "ready"
    RUNNING = "running"
    WAITING = "waiting"
    PAUSED = "paused"
    BLOCKED = "blocked"
    NEEDS_APPROVAL = "needs_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


#: Allowed lifecycle transitions. Anything else raises InvalidTransition.
#: Terminal states (COMPLETED/FAILED/STOPPED) only leave via explicit
#: recover() which archives the old run and starts a fresh cycle.
TRANSITIONS: dict[DotStatus, frozenset[DotStatus]] = {
    DotStatus.CREATED: frozenset({DotStatus.READY, DotStatus.STOPPED}),
    DotStatus.READY: frozenset({DotStatus.RUNNING, DotStatus.PAUSED,
                                DotStatus.STOPPED}),
    DotStatus.RUNNING: frozenset({DotStatus.WAITING, DotStatus.PAUSED,
                                  DotStatus.BLOCKED, DotStatus.NEEDS_APPROVAL,
                                  DotStatus.COMPLETED, DotStatus.FAILED,
                                  DotStatus.STOPPED}),
    DotStatus.WAITING: frozenset({DotStatus.RUNNING, DotStatus.PAUSED,
                                  DotStatus.BLOCKED, DotStatus.STOPPED}),
    DotStatus.PAUSED: frozenset({DotStatus.READY, DotStatus.RUNNING,
                                 DotStatus.STOPPED}),
    DotStatus.BLOCKED: frozenset({DotStatus.READY, DotStatus.RUNNING,
                                  DotStatus.STOPPED}),
    DotStatus.NEEDS_APPROVAL: frozenset({DotStatus.RUNNING, DotStatus.PAUSED,
                                         DotStatus.STOPPED}),
    DotStatus.COMPLETED: frozenset(),
    DotStatus.FAILED: frozenset(),
    DotStatus.STOPPED: frozenset(),
}


class InvalidTransition(Exception):
    """Illegal Dot lifecycle transition attempted."""


def validate_transition(from_status: DotStatus,
                        to_status: DotStatus) -> None:
    if to_status not in TRANSITIONS[from_status]:
        raise InvalidTransition(
            f"dot cannot move {from_status.value} → {to_status.value}")


@dataclass
class Checkpoint:
    """Durable recovery record. Uncertain results stay uncertain."""

    checkpoint_id: str = field(default_factory=lambda: new_id("ckpt"))
    dot_id: str = ""
    status: str = ""
    task_id: str = ""
    task_state: str = ""
    completed_work: list[str] = field(default_factory=list)
    pending_work: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    operation_refs: list[str] = field(default_factory=list)
    budgets: dict[str, Any] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)
    uncertain: bool = False
    created_at: float = field(default_factory=now)
    schema_version: int = DOT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id, "dot_id": self.dot_id,
            "status": self.status, "task_id": self.task_id,
            "task_state": self.task_state,
            "completed_work": self.completed_work,
            "pending_work": self.pending_work,
            "evidence_refs": self.evidence_refs,
            "operation_refs": self.operation_refs,
            "budgets": self.budgets, "failures": self.failures,
            "uncertain": self.uncertain, "created_at": self.created_at,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Checkpoint":
        return cls(
            checkpoint_id=data.get("checkpoint_id", new_id("ckpt")),
            dot_id=data.get("dot_id", ""),
            status=data.get("status", ""),
            task_id=data.get("task_id", ""),
            task_state=data.get("task_state", ""),
            completed_work=list(data.get("completed_work", [])),
            pending_work=list(data.get("pending_work", [])),
            evidence_refs=list(data.get("evidence_refs", [])),
            operation_refs=list(data.get("operation_refs", [])),
            budgets=dict(data.get("budgets", {})),
            failures=list(data.get("failures", [])),
            uncertain=bool(data.get("uncertain", False)),
            created_at=data.get("created_at", now()),
            schema_version=int(data.get("schema_version", 1)))


@dataclass
class Dot:
    """Persistent responsibility owner. All state JSON-serializable."""

    dot_id: str = field(default_factory=lambda: new_id("dot"))
    name: str = ""
    description: str = ""
    role: str = "general"
    goal: str = ""
    status: DotStatus = DotStatus.CREATED
    priority: int = 5
    created_at: float = field(default_factory=now)
    updated_at: float = field(default_factory=now)
    workspace: dict[str, Any] = field(default_factory=dict)
    memory_refs: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    trigger_subscriptions: list[str] = field(default_factory=list)
    task_ids: list[str] = field(default_factory=list)
    checkpoint: dict[str, Any] | None = None
    progress: float = 0.0
    evidence_refs: list[str] = field(default_factory=list)
    trace_refs: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    schema_version: int = DOT_SCHEMA_VERSION
    metadata: dict[str, Any] = field(default_factory=dict)

    def transition(self, to_status: DotStatus) -> None:
        validate_transition(self.status, to_status)
        self.status = to_status
        self.updated_at = now()

    def to_dict(self) -> dict[str, Any]:
        data = dict(self.__dict__)
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Dot":
        status = data.get("status", "created")
        try:
            parsed = DotStatus(status)
        except ValueError:
            parsed = DotStatus.CREATED
        return cls(
            dot_id=data.get("dot_id", new_id("dot")),
            name=data.get("name", ""),
            description=data.get("description", ""),
            role=data.get("role", "general"),
            goal=data.get("goal", ""),
            status=parsed,
            priority=int(data.get("priority", 5)),
            created_at=data.get("created_at", now()),
            updated_at=data.get("updated_at", now()),
            workspace=dict(data.get("workspace", {})),
            memory_refs=list(data.get("memory_refs", [])),
            tools=list(data.get("tools", [])),
            skills=list(data.get("skills", [])),
            permissions=list(data.get("permissions", [])),
            trigger_subscriptions=list(
                data.get("trigger_subscriptions", [])),
            task_ids=list(data.get("task_ids", [])),
            checkpoint=data.get("checkpoint"),
            progress=float(data.get("progress", 0.0)),
            evidence_refs=list(data.get("evidence_refs", [])),
            trace_refs=list(data.get("trace_refs", [])),
            failures=list(data.get("failures", [])),
            schema_version=int(data.get("schema_version", 1)),
            metadata=dict(data.get("metadata", {})))
