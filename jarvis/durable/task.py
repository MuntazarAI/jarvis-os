"""Durable task contracts (Durable Autonomous Tasks 1.0).

Identity, explicit state machine, steps, checkpoints, retry policy.
Validation is strict and bounded; illegal transitions fail closed.
No execution here — only shapes and state rules.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

SCHEMA_VERSION = 1
MAX_TITLE_CHARS = 300
MAX_STEPS = 32
MAX_TEXT_CHARS = 2000
MAX_RETRIES = 5


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _utcnow() -> float:
    return time.time()


class TaskError(ValueError):
    """Malformed task data or illegal transition."""


class TaskState(str, Enum):
    CREATED = "created"
    PLANNING = "planning"
    READY = "ready"
    RUNNING = "running"
    WAITING = "waiting"
    VERIFYING = "verifying"
    CHECKPOINTED = "checkpointed"
    PAUSED = "paused"
    RECOVERING = "recovering"
    RETRYING = "retrying"
    FAILED = "failed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    EXPIRED = "expired"


class StepState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


TRANSITIONS: dict[TaskState, frozenset[TaskState]] = {
    TaskState.CREATED: frozenset({TaskState.PLANNING,
                                  TaskState.CANCELLED,
                                  TaskState.EXPIRED}),
    TaskState.PLANNING: frozenset({TaskState.READY, TaskState.FAILED,
                                   TaskState.CANCELLED}),
    TaskState.READY: frozenset({TaskState.RUNNING, TaskState.PAUSED,
                                TaskState.CANCELLED, TaskState.EXPIRED,
                                TaskState.WAITING, TaskState.FAILED}),
    # FAILED from READY: a deadline kill must land from any live state.
    TaskState.RUNNING: frozenset({TaskState.VERIFYING,
                                  TaskState.WAITING, TaskState.PAUSED,
                                  TaskState.FAILED, TaskState.CANCELLED,
                                  TaskState.RECOVERING,
                                  TaskState.COMPLETED}),
    TaskState.WAITING: frozenset({TaskState.READY, TaskState.CANCELLED,
                                  TaskState.EXPIRED, TaskState.FAILED,
                                  TaskState.RECOVERING}),
    TaskState.VERIFYING: frozenset({TaskState.CHECKPOINTED,
                                    TaskState.FAILED,
                                    TaskState.RETRYING,
                                    TaskState.RECOVERING,
                                    TaskState.CANCELLED}),
    TaskState.CHECKPOINTED: frozenset({TaskState.RUNNING,
                                       TaskState.READY,
                                       TaskState.PAUSED,
                                       TaskState.CANCELLED,
                                       TaskState.FAILED,
                                       TaskState.COMPLETED}),
    # CHECKPOINTED is a stable rest state: resume goes through READY
    # via recover(); direct RUNNING covers same-process continuation.
    TaskState.PAUSED: frozenset({TaskState.READY, TaskState.CANCELLED,
                                 TaskState.RECOVERING, TaskState.FAILED}),
    # FAILED from PAUSED: same deadline-kill rule as READY.
    TaskState.RECOVERING: frozenset({TaskState.READY,
                                     TaskState.RETRYING,
                                     TaskState.WAITING,
                                     TaskState.FAILED,
                                     TaskState.CANCELLED}),
    TaskState.RETRYING: frozenset({TaskState.RUNNING,
                                   TaskState.FAILED,
                                   TaskState.RECOVERING,
                                   TaskState.CANCELLED}),
    TaskState.FAILED: frozenset({TaskState.RECOVERING,
                                 TaskState.CANCELLED}),
    TaskState.CANCELLED: frozenset(),
    TaskState.COMPLETED: frozenset(),
    TaskState.EXPIRED: frozenset({TaskState.CANCELLED}),
}


def check_transition(frm: TaskState, to: TaskState) -> bool:
    return to in TRANSITIONS.get(frm, frozenset())


@dataclass
class RetryPolicy:
    max_attempts: int = 3
    backoff_base_s: float = 60.0
    backoff_max_s: float = 3600.0
    deadline_s: float = 0.0  # 0 = none
    retryable: tuple[str, ...] = ("transient", "timeout", "unknown")

    def __post_init__(self) -> None:
        if not 0 <= self.max_attempts <= MAX_RETRIES:
            raise TaskError("max_attempts out of range")
        if self.backoff_base_s < 0 or self.backoff_max_s < 0:
            raise TaskError("negative backoff")
        if self.deadline_s < 0:
            raise TaskError("negative deadline")

    def delay_for(self, failures: int) -> float:
        delay = self.backoff_base_s * (2.0 ** max(0, failures - 1))
        return min(self.backoff_max_s, delay)

    def to_dict(self) -> dict[str, Any]:
        return {"max_attempts": self.max_attempts,
                "backoff_base_s": self.backoff_base_s,
                "backoff_max_s": self.backoff_max_s,
                "deadline_s": self.deadline_s,
                "retryable": list(self.retryable)}


@dataclass
class TaskStep:
    step_id: str = field(
        default_factory=lambda: _new_id("step"))
    title: str = ""
    state: StepState = StepState.PENDING
    attempts: int = 0
    started_at: float = 0.0
    finished_at: float = 0.0
    output_ref: str = ""
    verification: str = "unknown"  # unknown|verified|failed|partial
    checkpoint: dict[str, Any] = field(default_factory=dict)
    idempotency_key: str = ""

    def __post_init__(self) -> None:
        self.title = str(self.title or "")[:MAX_TEXT_CHARS]
        if isinstance(self.state, str):
            try:
                self.state = StepState(self.state)
            except ValueError:
                raise TaskError(f"bad step state: {self.state!r}")
        if self.attempts < 0:
            raise TaskError("negative attempts")
        if not self.idempotency_key:
            self.idempotency_key = f"{self.step_id}:attempt-0"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["state"] = self.state.value
        return data


@dataclass
class Checkpoint:
    checkpoint_id: str = field(
        default_factory=lambda: _new_id("ckpt"))
    at: float = field(default_factory=_utcnow)
    step_id: str = ""
    # What is KNOWN (verified), never what was merely attempted.
    known: dict[str, Any] = field(default_factory=dict)
    side_effects_confirmed: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Task:
    task_id: str = field(
        default_factory=lambda: f"task-{uuid.uuid4().hex[:12]}")
    version: int = SCHEMA_VERSION
    created_at: float = field(default_factory=_utcnow)
    updated_at: float = field(default_factory=_utcnow)
    title: str = ""
    source: str = ""  # conductor|service|cli|api
    priority: int = 5
    state: TaskState = TaskState.CREATED
    deadline: float = 0.0
    cancel_requested: bool = False
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    plan_ref: str = ""
    plan_version: str = ""
    current_step: str = ""
    steps: list[TaskStep] = field(default_factory=list)
    checkpoints: list[Checkpoint] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.title = str(self.title or "")[:MAX_TITLE_CHARS]
        if isinstance(self.state, str):
            try:
                self.state = TaskState(self.state)
            except ValueError:
                raise TaskError(f"bad task state: {self.state!r}")
        if isinstance(self.retry_policy, dict):
            self.retry_policy = RetryPolicy(**{
                k: v for k, v in self.retry_policy.items()
                if k in ("max_attempts", "backoff_base_s",
                         "backoff_max_s", "deadline_s", "retryable")})
        self.steps = [s if isinstance(s, TaskStep) else TaskStep(**s)
                      for s in self.steps[:MAX_STEPS]]
        self.checkpoints = [
            c if isinstance(c, Checkpoint) else Checkpoint(**c)
            for c in self.checkpoints[-10:]]

    def transition(self, to: TaskState) -> None:
        """Move state; illegal transitions raise (fail closed)."""
        target = to if isinstance(to, TaskState) else TaskState(to)
        if not check_transition(self.state, target):
            raise TaskError(
                f"illegal transition {self.state.value}->{target.value}")
        self.state = target
        self.updated_at = _utcnow()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["state"] = self.state.value
        data["retry_policy"] = self.retry_policy.to_dict()
        data["steps"] = [s.to_dict() for s in self.steps]
        data["checkpoints"] = [c.to_dict() for c in self.checkpoints]
        return data


__all__ = ["Task", "TaskStep", "TaskState", "StepState", "Checkpoint",
           "RetryPolicy", "TRANSITIONS", "check_transition",
           "TaskError", "SCHEMA_VERSION", "MAX_STEPS"]
