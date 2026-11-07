"""Planning Engine - M13 Cognitive Architecture.

Provides planning capabilities for JARVIS including:
- Task decomposition: Breaking complex goals into subtasks
- Task sequencing: Ordering tasks by dependencies
- Resource allocation: Assigning resources to tasks
- Plan monitoring: Tracking execution progress
- Plan adaptation: Adjusting plans based on results
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PlanStep:
    """A single step in a plan."""
    step_id: str
    description: str
    agent_id: str | None = None  # Which agent should execute
    dependencies: list[str] = field(default_factory=list)
    status: str = "pending"  # pending, in_progress, completed, failed
    result: dict[str, Any] | None = None
    estimated_duration: float | None = None
    actual_duration: float | None = None
    started_at: float | None = None
    completed_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "description": self.description,
            "agent_id": self.agent_id,
            "dependencies": self.dependencies,
            "status": self.status,
            "result": self.result,
            "estimated_duration": self.estimated_duration,
            "actual_duration": self.actual_duration,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


@dataclass
class Plan:
    """A plan consisting of multiple steps."""
    plan_id: str
    goal: str
    steps: list[PlanStep] = field(default_factory=list)
    status: str = "pending"  # pending, in_progress, completed, failed
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_step(self, step: PlanStep) -> None:
        """Add a step to the plan."""
        self.steps.append(step)

    def get_next_steps(self) -> list[PlanStep]:
        """Get steps that are ready to execute (all dependencies completed)."""
        completed_ids = {s.step_id for s in self.steps
                         if s.status == "completed"}
        return [s for s in self.steps
                if s.status == "pending"
                and all(dep in completed_ids for dep in s.dependencies)]

    def is_complete(self) -> bool:
        """Check if all steps are completed."""
        return all(s.status == "completed" for s in self.steps)

    def is_failed(self) -> bool:
        """Check if any step has failed."""
        return any(s.status == "failed" for s in self.steps)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "goal": self.goal,
            "steps": [s.to_dict() for s in self.steps],
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "metadata": self.metadata,
        }


class PlanningEngine:
    """Planning engine for JARVIS cognitive architecture.

    Provides planning capabilities including:
    - Task decomposition: Breaking complex goals into subtasks
    - Task sequencing: Ordering tasks by dependencies
    - Resource allocation: Assigning resources to tasks
    - Plan monitoring: Tracking execution progress
    - Plan adaptation: Adjusting plans based on results
    """

    def __init__(self) -> None:
        self.plans: dict[str, Plan] = {}
        self.created_at = time.time()

    def create_plan(self, goal: str,
                    steps: list[dict[str, Any]] | None = None) -> Plan:
        """Create a new plan for a goal."""
        plan_id = f"plan-{len(self.plans):06d}"
        plan = Plan(plan_id=plan_id, goal=goal)
        self.plans[plan_id] = plan

        if steps:
            for step_data in steps:
                step = PlanStep(
                    step_id=step_data.get("step_id", f"step-{len(plan.steps):03d}"),
                    description=step_data.get("description", ""),
                    agent_id=step_data.get("agent_id"),
                    dependencies=step_data.get("dependencies", []),
                    estimated_duration=step_data.get("estimated_duration"),
                )
                plan.add_step(step)

        return plan

    def get_plan(self, plan_id: str) -> Plan | None:
        """Get a plan by ID."""
        return self.plans.get(plan_id)

    def update_step_status(self, plan_id: str, step_id: str,
                           status: str,
                           result: dict[str, Any] | None = None) -> bool:
        """Update the status of a plan step."""
        plan = self.plans.get(plan_id)
        if plan is None:
            return False
        for step in plan.steps:
            if step.step_id == step_id:
                step.status = status
                if result is not None:
                    step.result = result
                if status == "in_progress" and step.started_at is None:
                    step.started_at = time.time()
                if status in ("completed", "failed"):
                    step.completed_at = time.time()
                return True
        return False

    def get_next_steps(self, plan_id: str) -> list[PlanStep]:
        """Get steps ready for execution."""
        plan = self.plans.get(plan_id)
        if plan is None:
            return []
        return plan.get_next_steps()

    def get_all_plans(self) -> list[Plan]:
        """Get all plans."""
        return list(self.plans.values())

    def get_stats(self) -> dict[str, Any]:
        """Get planning engine statistics."""
        total_plans = len(self.plans)
        completed = sum(1 for p in self.plans.values() if p.status == "completed")
        failed = sum(1 for p in self.plans.values() if p.status == "failed")
        in_progress = sum(1 for p in self.plans.values() if p.status == "in_progress")
        total_steps = sum(len(p.steps) for p in self.plans.values())
        completed_steps = sum(
            1 for p in self.plans.values()
            for s in p.steps if s.status == "completed"
        )

        return {
            "total_plans": total_plans,
            "completed_plans": completed,
            "failed_plans": failed,
            "in_progress_plans": in_progress,
            "total_steps": total_steps,
            "completed_steps": completed_steps,
        }


# Global planning engine instance
_planning_engine: PlanningEngine | None = None


def get_planning_engine() -> PlanningEngine:
    """Get or create the global planning engine."""
    global _planning_engine
    if _planning_engine is None:
        _planning_engine = PlanningEngine()
    return _planning_engine


__all__ = [
    "PlanStep",
    "Plan",
    "PlanningEngine",
    "get_planning_engine",
]
