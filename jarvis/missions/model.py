"""Missions 3.3 — persistent multi-dot objectives.

A Mission is NOT a task and NOT a dot:
- Task   = one unit of work (TaskEngine)
- Dot    = persistent responsibility owner (dots/)
- Goal   = desired persistent outcome (memory tier goal)
- Mission = persistent objective coordinating dots/tasks/agents
  with ordered objectives, verification, and recovery.

A Mission never executes tools. Execution always flows:
Mission → Objective → Dot → Task → Orchestrator → PolicyEngine → tool.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..core.types import new_id, now

MISSION_SCHEMA_VERSION = 1


class MissionStatus(str, Enum):
    DRAFT = "draft"
    READY = "ready"
    RUNNING = "running"
    WAITING = "waiting"
    BLOCKED = "blocked"
    NEEDS_APPROVAL = "needs_approval"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    STOPPED = "stopped"


class ObjectiveStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    BLOCKED = "blocked"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


#: Mission lifecycle. Terminal states leave only via recover().
MISSION_TRANSITIONS: dict[MissionStatus, frozenset[MissionStatus]] = {
    MissionStatus.DRAFT: frozenset({MissionStatus.READY,
                                    MissionStatus.CANCELLED}),
    MissionStatus.READY: frozenset({MissionStatus.RUNNING,
                                    MissionStatus.PAUSED,
                                    MissionStatus.CANCELLED}),
    MissionStatus.RUNNING: frozenset({MissionStatus.WAITING,
                                      MissionStatus.PAUSED,
                                      MissionStatus.BLOCKED,
                                      MissionStatus.NEEDS_APPROVAL,
                                      MissionStatus.VERIFYING,
                                      MissionStatus.COMPLETED,
                                      MissionStatus.FAILED,
                                      MissionStatus.CANCELLED,
                                      MissionStatus.STOPPED}),
    MissionStatus.WAITING: frozenset({MissionStatus.RUNNING,
                                      MissionStatus.PAUSED,
                                      MissionStatus.BLOCKED,
                                      MissionStatus.STOPPED}),
    MissionStatus.BLOCKED: frozenset({MissionStatus.RUNNING,
                                      MissionStatus.PAUSED,
                                      MissionStatus.STOPPED}),
    MissionStatus.NEEDS_APPROVAL: frozenset({MissionStatus.RUNNING,
                                             MissionStatus.PAUSED,
                                             MissionStatus.STOPPED}),
    MissionStatus.VERIFYING: frozenset({MissionStatus.COMPLETED,
                                        MissionStatus.FAILED,
                                        MissionStatus.RUNNING,
                                        MissionStatus.BLOCKED}),
    MissionStatus.PAUSED: frozenset({MissionStatus.READY,
                                     MissionStatus.RUNNING,
                                     MissionStatus.STOPPED,
                                     MissionStatus.CANCELLED}),
    MissionStatus.COMPLETED: frozenset(),
    MissionStatus.FAILED: frozenset(),
    MissionStatus.CANCELLED: frozenset(),
    MissionStatus.STOPPED: frozenset(),
}

MISSION_TERMINAL = frozenset({MissionStatus.COMPLETED, MissionStatus.FAILED,
                              MissionStatus.CANCELLED, MissionStatus.STOPPED})


class InvalidMissionTransition(Exception):
    """Illegal mission lifecycle transition attempted."""


class InvalidObjectiveTransition(Exception):
    """Illegal objective lifecycle transition attempted."""


def validate_mission_transition(from_status: MissionStatus,
                                to_status: MissionStatus) -> None:
    if to_status not in MISSION_TRANSITIONS[from_status]:
        raise InvalidMissionTransition(
            f"mission cannot move {from_status.value} → {to_status.value}")


@dataclass
class Objective:
    """One ordered, dependency-aware unit of mission work."""

    objective_id: str = field(default_factory=lambda: new_id("obj"))
    mission_id: str = ""
    name: str = ""
    description: str = ""
    status: ObjectiveStatus = ObjectiveStatus.PENDING
    priority: int = 5
    weight: float = 1.0
    depends_on: list[str] = field(default_factory=list)
    dot_id: str = ""
    task_ids: list[str] = field(default_factory=list)
    success_criteria: list[dict[str, Any]] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    progress: float = 0.0
    confidence: float = 0.5
    uncertainty: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=now)
    updated_at: float = field(default_factory=now)
    completed_at: float | None = None
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        data = dict(self.__dict__)
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Objective":
        status = data.get("status", "pending")
        try:
            parsed = ObjectiveStatus(status)
        except ValueError:
            parsed = ObjectiveStatus.PENDING
        return cls(
            objective_id=data.get("objective_id", new_id("obj")),
            mission_id=data.get("mission_id", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            status=parsed,
            priority=int(data.get("priority", 5)),
            weight=float(data.get("weight", 1.0)),
            depends_on=list(data.get("depends_on", [])),
            dot_id=data.get("dot_id", ""),
            task_ids=list(data.get("task_ids", [])),
            success_criteria=list(data.get("success_criteria", [])),
            evidence_refs=list(data.get("evidence_refs", [])),
            progress=float(data.get("progress", 0.0)),
            confidence=float(data.get("confidence", 0.5)),
            uncertainty=list(data.get("uncertainty", [])),
            failures=list(data.get("failures", [])),
            created_at=data.get("created_at", now()),
            updated_at=data.get("updated_at", now()),
            completed_at=data.get("completed_at"),
            version=int(data.get("version", 1)))


@dataclass
class Mission:
    """Persistent multi-dot objective with verification and recovery."""

    mission_id: str = field(default_factory=lambda: new_id("msn"))
    name: str = ""
    description: str = ""
    status: MissionStatus = MissionStatus.DRAFT
    priority: int = 5
    created_at: float = field(default_factory=now)
    updated_at: float = field(default_factory=now)
    started_at: float | None = None
    completed_at: float | None = None
    owner: str = "user"
    goal: str = ""
    success_criteria: list[dict[str, Any]] = field(default_factory=list)
    failure_criteria: list[str] = field(default_factory=list)
    objectives: dict[str, Objective] = field(default_factory=dict)
    dot_ids: list[str] = field(default_factory=list)
    task_ids: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    blocked_by: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    checkpoint_refs: list[str] = field(default_factory=list)
    active_objective: str = ""
    progress: float = 0.0
    confidence: float = 0.5
    uncertainty: list[str] = field(default_factory=list)
    risk: str = "medium"
    budget: dict[str, Any] = field(default_factory=dict)
    workspace: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    version: int = 1
    created_by: str = "user"
    provenance: dict[str, Any] = field(default_factory=dict)

    def transition(self, to_status: MissionStatus) -> None:
        validate_mission_transition(self.status, to_status)
        self.status = to_status
        self.updated_at = now()
        self.version += 1
        if to_status == MissionStatus.RUNNING and self.started_at is None:
            self.started_at = now()
        if to_status in MISSION_TERMINAL:
            self.completed_at = now()

    def to_dict(self) -> dict[str, Any]:
        data = dict(self.__dict__)
        data["status"] = self.status.value
        data["objectives"] = {oid: obj.to_dict()
                              for oid, obj in self.objectives.items()}
        data["schema_version"] = MISSION_SCHEMA_VERSION
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Mission":
        status = data.get("status", "draft")
        try:
            parsed = MissionStatus(status)
        except ValueError:
            parsed = MissionStatus.DRAFT
        objectives = {}
        for oid, raw in (data.get("objectives") or {}).items():
            try:
                obj = Objective.from_dict(raw)
            except Exception:
                continue
            obj.objective_id = oid
            objectives[oid] = obj
        return cls(
            mission_id=data.get("mission_id", new_id("msn")),
            name=data.get("name", ""),
            description=data.get("description", ""),
            status=parsed,
            priority=int(data.get("priority", 5)),
            created_at=data.get("created_at", now()),
            updated_at=data.get("updated_at", now()),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            owner=data.get("owner", "user"),
            goal=data.get("goal", ""),
            success_criteria=list(data.get("success_criteria", [])),
            failure_criteria=list(data.get("failure_criteria", [])),
            objectives=objectives,
            dot_ids=list(data.get("dot_ids", [])),
            task_ids=list(data.get("task_ids", [])),
            dependencies=list(data.get("dependencies", [])),
            blocked_by=list(data.get("blocked_by", [])),
            evidence_refs=list(data.get("evidence_refs", [])),
            checkpoint_refs=list(data.get("checkpoint_refs", [])),
            active_objective=data.get("active_objective", ""),
            progress=float(data.get("progress", 0.0)),
            confidence=float(data.get("confidence", 0.5)),
            uncertainty=list(data.get("uncertainty", [])),
            risk=data.get("risk", "medium"),
            budget=dict(data.get("budget", {})),
            workspace=dict(data.get("workspace", {})),
            metadata=dict(data.get("metadata", {})),
            version=int(data.get("version", 1)),
            created_by=data.get("created_by", "user"),
            provenance=dict(data.get("provenance", {})))


def ready_objectives(mission: Mission) -> list[Objective]:
    """Objectives whose dependencies all completed (explicit IDs only).

    Failed/skipped dependencies block dependents instead of cascading.
    Objectives with unknown dependency IDs are blocked, never released.
    """
    ready = []
    for obj in mission.objectives.values():
        if obj.status not in (ObjectiveStatus.PENDING, ObjectiveStatus.READY):
            continue
        blocked, failed_dep = False, ""
        for dep_id in obj.depends_on:
            dep = mission.objectives.get(dep_id)
            if dep is None:
                blocked, failed_dep = True, f"unknown dependency {dep_id}"
                break
            if dep.status == ObjectiveStatus.COMPLETED:
                continue
            if dep.status in (ObjectiveStatus.FAILED,
                              ObjectiveStatus.SKIPPED):
                blocked, failed_dep = True, f"dependency {dep_id} {dep.status.value}"
                break
            blocked, failed_dep = True, f"waiting on {dep_id}"
            break
        if blocked:
            if failed_dep and "failed" in failed_dep:
                obj.status = ObjectiveStatus.BLOCKED
                obj.updated_at = now()
            continue
        ready.append(obj)
    return sorted(ready, key=lambda o: (-o.priority, o.created_at))


def compute_progress(mission: Mission) -> float:
    """Deterministic weighted progress. Weights normalize; missing weight
    defaults to 1.0. Uncertain/failed work counts honestly below 1.0."""
    if not mission.objectives:
        return 0.0
    total = sum(max(0.0, o.weight) for o in mission.objectives.values())
    if total <= 0:
        return 0.0
    scored = 0.0
    for obj in mission.objectives.values():
        weight = max(0.0, obj.weight)
        if obj.status == ObjectiveStatus.COMPLETED:
            scored += weight * 1.0
        elif obj.status == ObjectiveStatus.FAILED:
            scored += weight * 0.0
        elif obj.status == ObjectiveStatus.SKIPPED:
            scored += weight * 0.0
        else:
            scored += weight * max(0.0, min(1.0, obj.progress)) * 0.99
    return round(scored / total, 4)
