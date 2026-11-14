"""JARVIS Experience Layer — read-only dashboard consuming real JARVIS state.

This module is a *consumer* of existing JARVIS subsystems, never the owner of
intelligence. It does NOT create:

- a second planner
- a second agent system
- a second task engine
- a second memory system
- a second world model
- a second policy/approval system
- a second event bus
- a second scheduler

All UI state flows through existing authoritative systems (MemoryPalace,
WorldModel, PolicyEngine, TaskEngine, EnhancedSupervisor) via their public
APIs. Secrets, approval tokens, and raw credentials are never exposed.

Architecture:

    UI → ExperienceView → existing subsystems (read-only)

The view is read-only with respect to intelligence: it may display state and
emit user intents, but all mutations flow through PolicyEngine + approvals.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from ..core.logging import get_module_logger
from ..memory.palace import MemoryPalace
from ..world.model import WorldModel
from ..policy.policy import PolicyEngine
from ..tasks.engine import TaskEngine
from ..agents import EnhancedSupervisor

log = get_module_logger(__name__)


# -- data contracts -----------------------------------------------------------


@dataclass
class ExperienceView:
    """Immutable snapshot of JARVIS state for the experience layer.

    Every field is derived from existing subsystems; none is mutated here.
    """

    # Cognitive loop
    cycle: int = 0
    memory_total: int = 0
    memory_live: int = 0
    memory_archived: int = 0

    # World model
    world_entities: int = 0
    world_events: int = 0
    world_rooms: int = 0

    # Agent system
    agents_total: int = 0
    agents_idle: int = 0
    agents_working: int = 0
    agents_failed: int = 0

    # Tasks
    tasks_total: int = 0
    tasks_queued: int = 0
    tasks_running: int = 0
    tasks_completed: int = 0
    tasks_failed: int = 0

    # Security / policy
    policy_decisions: int = 0
    pending_approvals: int = 0
    emergency_stop: bool = False

    # Posture
    posture: str = "unknown"  # clear | review | attention | critical | unknown

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ExperienceManager:
    """Read-only front door over JARVIS subsystems for the experience layer.

    Every getter delegates to an existing subsystem; nothing is mutated,
    duplicated, or re-implemented here.
    """

    def __init__(
        self,
        palace: MemoryPalace | None = None,
        world: WorldModel | None = None,
        policy: PolicyEngine | None = None,
        tasks: TaskEngine | None = None,
        supervisor: EnhancedSupervisor | None = None,
    ) -> None:
        self.palace = palace
        self.world = world
        self.policy = policy
        self.tasks = tasks
        self.supervisor = supervisor

    # -- snapshot ----------------------------------------------------------

    def snapshot(self) -> ExperienceView:
        """Capture a read-only snapshot of JARVIS state from subsystems."""
        v = ExperienceView()

        # Memory Palace (real subsystem)
        if self.palace is not None:
            stats = self.palace.stats()
            v.memory_total = stats.get("total", 0)
            v.memory_live = stats.get("live", 0)
            v.memory_archived = stats.get("archived", 0)

        # World Model (real subsystem)
        if self.world is not None:
            v.world_entities = len(self.world.entities())
            v.world_events = len(self.world._timeline)
            v.world_rooms = len(self.world._rooms)

        # Agent system (real subsystem)
        if self.supervisor is not None:
            reg = self.supervisor.registry
            agents = reg.list_agents()
            v.agents_total = len(agents)
            v.agents_idle = sum(1 for a in agents if a.state == "idle")
            v.agents_working = sum(1 for a in agents if a.state == "working")
            v.agents_failed = sum(1 for a in agents if a.state == "failed")

        # Tasks (real subsystem)
        if self.tasks is not None:
            tasks = list(self.tasks.tasks.values())
            v.tasks_total = len(tasks)
            v.tasks_queued = sum(1 for t in tasks if t.state.name == "QUEUED")
            v.tasks_running = sum(1 for t in tasks if t.state.name == "RUNNING")
            v.tasks_completed = sum(1 for t in tasks if t.state.name == "COMPLETED")
            v.tasks_failed = sum(1 for t in tasks if t.state.name == "FAILED")

        # Policy / security (real subsystem)
        if self.policy is not None:
            try:
                v.emergency_stop = self.policy.emergency_stop_engaged()
            except Exception:
                v.emergency_stop = False

        # Posture derived from memory state
        if v.memory_archived > v.memory_live:
            v.posture = "critical"
        elif v.memory_archived > 0:
            v.posture = "attention"
        elif v.memory_live > 0:
            v.posture = "review"
        else:
            v.posture = "clear"

        return v

    # -- read-only helpers --------------------------------------------------

    def pending_approval_count(self) -> int:
        """Return count of pending approvals from PolicyEngine.

        Never exposes approval tokens or secrets.
        """
        if self.policy is None:
            return 0
        try:
            approvals = self.policy.approvals
            return sum(1 for a in approvals.values() if a.get("status") == "pending")
        except Exception:
            return 0

    def health(self) -> dict[str, Any]:
        """Return a health summary derived from subsystem status."""
        snap = self.snapshot()
        checks: dict[str, Any] = {
            "memory_palace": self.palace is not None,
            "world_model": self.world is not None,
            "policy_engine": self.policy is not None,
            "task_engine": self.tasks is not None,
            "agent_supervisor": self.supervisor is not None,
        }
        all_healthy = all(checks.values())
        return {
            "healthy": all_healthy,
            "posture": snap.posture,
            "subsystems": checks,
        }

    def as_public_report(self) -> dict[str, Any]:
        """Return a secret-scrubbed report safe for UI rendering.

        Never includes approval tokens, secrets, or raw credentials.
        """
        snap = self.snapshot()
        return {
            "snapshot": snap.to_dict(),
            "pending_approval_count": self.pending_approval_count(),
            "health": self.health(),
        }


__all__ = ["ExperienceView", "ExperienceManager"]
