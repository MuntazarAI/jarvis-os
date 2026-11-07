"""Advanced Planning - M32.

Hierarchical task decomposition, constraint solving, plan optimization,
and planning evaluation. Builds on jarvis.cognition.planning.PlanningEngine.

All components are deterministic and deterministic — no model calls,
no external dependencies. Suitable for CPU-only operation.
"""

from __future__ import annotations

import heapq
import time
from dataclasses import dataclass, field
from typing import Any

from ..cognition.planning import Plan, PlanStep, PlanningEngine


@dataclass
class TaskConstraint:
    """A constraint on task execution."""
    constraint_id: str
    name: str
    constraint_type: str  # "time", "resource", "dependency", "budget"
    value: Any
    description: str = ""
    weight: float = 1.0  # importance weight for optimization


@dataclass
class HierarchicalTask:
    """A task in a hierarchical decomposition."""
    task_id: str
    name: str
    description: str
    parent_id: str | None = None
    subtasks: list[str] = field(default_factory=list)
    status: str = "pending"  # pending, in_progress, completed, failed
    dependencies: list[str] = field(default_factory=list)
    estimated_duration: float | None = None
    constraints: list[str] = field(default_factory=list)  # constraint_ids
    agent_id: str | None = None
    result: dict[str, Any] | None = None


class HierarchicalTaskDecomposer:
    """Decomposes high-level goals into hierarchical subtasks."""

    def __init__(self) -> None:
        self.tasks: dict[str, HierarchicalTask] = {}
        self.created_at = time.time()

    def decompose(self, goal: str,
                  max_depth: int = 3,
                  max_branching: int = 5) -> str:
        """Create a hierarchical task decomposition for a goal."""
        task_id = f"task-{len(self.tasks):06d}"
        root = HierarchicalTask(
            task_id=task_id,
            name=goal,
            description=goal,
            status="pending",
        )
        self.tasks[task_id] = root
        self._decompose_recursive(task_id, goal, depth=0,
                                   max_depth=max_depth,
                                   max_branching=max_branching)
        return task_id

    def _decompose_recursive(self, parent_id: str,
                             goal: str,
                             depth: int,
                             max_depth: int,
                             max_branching: int) -> None:
        if depth >= max_depth:
            return

        subtasks = self._split_goal(goal, max_branching)
        for i, (name, desc) in enumerate(subtasks):
            child_id = f"{parent_id}-{i:02d}"
            child = HierarchicalTask(
                task_id=child_id,
                name=name,
                description=desc,
                parent_id=parent_id,
                status="pending",
            )
            self.tasks[child_id] = child
            self.tasks[parent_id].subtasks.append(child_id)

            self._decompose_recursive(child_id, desc,
                                      depth + 1,
                                      max_depth,
                                      max_branching)

    def _split_goal(self, goal: str,
                    max_branching: int) -> list[tuple[str, str]]:
        goal_lower = goal.lower()
        subtasks: list[tuple[str, str]] = []

        if "research" in goal_lower:
            subtasks = [
                ("Identify sources", "Find relevant information sources"),
                ("Gather information", "Collect data from sources"),
                ("Synthesize findings", "Combine findings into answer"),
            ]
        elif "write" in goal_lower or "create" in goal_lower:
            subtasks = [
                ("Outline", "Create outline for content"),
                ("Draft", "Write initial draft"),
                ("Review", "Review and revise draft"),
            ]
        elif "analyze" in goal_lower:
            subtasks = [
                ("Collect data", "Gather relevant data"),
                ("Analyze patterns", "Identify patterns and trends"),
                ("Draw conclusions", "Form conclusions from analysis"),
            ]
        elif "plan" in goal_lower:
            subtasks = [
                ("Define objectives", "Clarify what needs to be achieved"),
                ("Identify steps", "Break down into actionable steps"),
                ("Allocate resources", "Assign resources to steps"),
            ]
        elif "fix" in goal_lower or "debug" in goal_lower:
            subtasks = [
                ("Identify issue", "Locate the problem"),
                ("Diagnose root cause", "Find underlying cause"),
                ("Implement fix", "Apply and test fix"),
            ]
        else:
            subtasks = [("Execute primary task", f"Complete: {goal}")]

        return subtasks[:max_branching]

    def get_task(self, task_id: str) -> HierarchicalTask | None:
        return self.tasks.get(task_id)

    def get_subtasks(self, task_id: str) -> list[HierarchicalTask]:
        task = self.tasks.get(task_id)
        if task is None:
            return []
        return [self.tasks[tid] for tid in task.subtasks
                if tid in self.tasks]

    def get_root_tasks(self) -> list[HierarchicalTask]:
        return [t for t in self.tasks.values() if t.parent_id is None]

    def get_leaf_tasks(self) -> list[HierarchicalTask]:
        return [t for t in self.tasks.values() if not t.subtasks]

    def get_ready_tasks(self) -> list[HierarchicalTask]:
        completed = {t.task_id for t in self.tasks.values()
                     if t.status == "completed"}
        return [t for t in self.tasks.values()
                if t.status == "pending"
                and all(d in completed for d in t.dependencies)]

    def update_task_status(self, task_id: str,
                           status: str,
                           result: dict[str, Any] | None = None) -> bool:
        task = self.tasks.get(task_id)
        if task is None:
            return False
        task.status = status
        if result is not None:
            task.result = result
        return True

    def get_stats(self) -> dict[str, Any]:
        total = len(self.tasks)
        completed = sum(1 for t in self.tasks.values()
                        if t.status == "completed")
        failed = sum(1 for t in self.tasks.values()
                     if t.status == "failed")
        return {
            "total_tasks": total,
            "completed_tasks": completed,
            "failed_tasks": failed,
            "max_depth": self._max_depth(),
        }

    def _max_depth(self) -> int:
        if not self.tasks:
            return 0
        return max(self._depth(t.task_id) for t in self.tasks.values())

    def _depth(self, task_id: str) -> int:
        task = self.tasks.get(task_id)
        if task is None or not task.subtasks:
            return 1
        return 1 + max(self._depth(sid) for sid in task.subtasks)


class ConstraintSolver:
    """Validates plans against constraints."""

    def __init__(self) -> None:
        self.constraints: dict[str, TaskConstraint] = {}

    def add_constraint(self, constraint: TaskConstraint) -> None:
        self.constraints[constraint.constraint_id] = constraint

    def remove_constraint(self, constraint_id: str) -> bool:
        if constraint_id in self.constraints:
            del self.constraints[constraint_id]
            return True
        return False

    def check_constraint(self, constraint: TaskConstraint,
                         context: dict[str, Any]) -> tuple[bool, str]:
        ctype = constraint.constraint_type.lower()
        value = constraint.value

        if ctype == "time":
            max_seconds = float(value)
            est = float(context.get("estimated_seconds", 0))
            if est > max_seconds:
                return False, f"Estimated {est}s exceeds {max_seconds}s limit"
        elif ctype == "resource":
            resource = str(value)
            available = context.get("resources", {}).get(resource, 0)
            required = context.get("required_resources", {}).get(resource, 0)
            if required > available:
                return False, f"Insufficient {resource}: need {required}, have {available}"
        elif ctype == "budget":
            max_cost = float(value)
            est_cost = float(context.get("estimated_cost", 0))
            if est_cost > max_cost:
                return False, f"Estimated cost {est_cost} exceeds {max_cost} budget"
        elif ctype == "dependency":
            dep_ids = list(value) if isinstance(value, list) else [str(value)]
            completed = set(context.get("completed_ids", []))
            missing = [d for d in dep_ids if d not in completed]
            if missing:
                return False, f"Unmet dependencies: {missing}"

        return True, "OK"

    def validate_plan(self, context: dict[str, Any]) -> tuple[bool, list[str]]:
        """Validate all constraints against context. Returns (valid, violations)."""
        violations = []
        for constraint in self.constraints.values():
            ok, reason = self.check_constraint(constraint, context)
            if not ok:
                violations.append(f"{constraint.name}: {reason}")
        return len(violations) == 0, violations


class PlanOptimizer:
    """Optimizes plan ordering based on dependencies and resource constraints."""

    def __init__(self) -> None:
        self.created_at = time.time()

    def topological_sort(self, steps: list[PlanStep]) -> list[PlanStep]:
        """Sort steps topologically by dependencies."""
        step_map = {s.step_id: s for s in steps}
        in_degree = {s.step_id: 0 for s in steps}
        adj: dict[str, list[str]] = {s.step_id: [] for s in steps}

        for s in steps:
            for dep in s.dependencies:
                if dep in step_map:
                    adj[dep].append(s.step_id)
                    in_degree[s.step_id] += 1

        queue = [sid for sid, deg in in_degree.items() if deg == 0]
        heapq.heapify(queue)
        result: list[PlanStep] = []

        while queue:
            sid = heapq.heappop(queue)
            result.append(step_map[sid])
            for neighbor in adj[sid]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    heapq.heappush(queue, neighbor)

        if len(result) != len(steps):
            # Cycle detected — append remaining in original order
            remaining = [s for s in steps if s.step_id
                         not in {r.step_id for r in result}]
            result.extend(remaining)

        return result

    def optimize_order(self, plan: Plan) -> list[PlanStep]:
        """Return steps in optimal execution order."""
        return self.topological_sort(list(plan.steps))


class AdvancedPlanningEngine:
    """Advanced planning engine combining hierarchical decomposition,
    constraint solving, and plan optimization.

    Wraps PlanningEngine (M13) and adds M32 capabilities.
    """

    def __init__(self) -> None:
        self.planning_engine = PlanningEngine()
        self.decomposer = HierarchicalTaskDecomposer()
        self.constraint_solver = ConstraintSolver()
        self.optimizer = PlanOptimizer()
        self.created_at = time.time()

    def create_plan(self, goal: str,
                    steps: list[dict[str, Any]] | None = None,
                    decompose: bool = False,
                    max_depth: int = 3,
                    max_branching: int = 5) -> dict[str, Any]:
        """Create a plan with optional hierarchical decomposition."""
        plan = self.planning_engine.create_plan(goal, steps)

        result: dict[str, Any] = {
            "plan_id": plan.plan_id,
            "goal": goal,
            "hierarchical_task_id": None,
        }

        if decompose:
            task_id = self.decomposer.decompose(goal,
                                                max_depth=max_depth,
                                                max_branching=max_branching)
            result["hierarchical_task_id"] = task_id

        return result

    def add_constraint(self, constraint: TaskConstraint) -> None:
        self.constraint_solver.add_constraint(constraint)

    def validate_plan(self, plan_id: str,
                      context: dict[str, Any]) -> dict[str, Any]:
        """Validate a plan against all constraints."""
        plan = self.planning_engine.get_plan(plan_id)
        if plan is None:
            return {"valid": False, "violations": ["Plan not found"]}

        context = dict(context)
        context["estimated_seconds"] = sum(
            s.estimated_duration or 0 for s in plan.steps)
        context["estimated_cost"] = sum(
            s.estimated_duration or 0 for s in plan.steps) * 0.01
        context["completed_ids"] = {
            s.step_id for s in plan.steps if s.status == "completed"
        }

        valid, violations = self.constraint_solver.validate_plan(context)
        return {"valid": valid, "violations": violations}

    def optimize_plan(self, plan_id: str) -> dict[str, Any]:
        """Return steps in optimal execution order."""
        plan = self.planning_engine.get_plan(plan_id)
        if plan is None:
            return {"plan_id": None, "ordered_steps": []}

        ordered = self.optimizer.optimize_order(list(plan.steps))
        return {
            "plan_id": plan.plan_id,
            "ordered_steps": [s.step_id for s in ordered],
            "steps": [s.to_dict() for s in ordered],
        }

    def decompose_goal(self, goal: str,
                       max_depth: int = 3,
                       max_branching: int = 5) -> str:
        """Create a hierarchical task decomposition for a goal."""
        return self.decomposer.decompose(goal,
                                         max_depth=max_depth,
                                         max_branching=max_branching)

    def get_stats(self) -> dict[str, Any]:
        pe_stats = self.planning_engine.get_stats()
        decomp_stats = self.decomposer.get_stats()
        return {
            "planning_engine": pe_stats,
            "hierarchical_tasks": decomp_stats,
            "constraints": len(self.constraint_solver.constraints),
        }


# Global advanced planning engine instance
_advanced_planning_engine: AdvancedPlanningEngine | None = None


def get_advanced_planning_engine() -> AdvancedPlanningEngine:
    """Get or create the global advanced planning engine."""
    global _advanced_planning_engine
    if _advanced_planning_engine is None:
        _advanced_planning_engine = AdvancedPlanningEngine()
    return _advanced_planning_engine


__all__ = [
    "TaskConstraint",
    "HierarchicalTask",
    "HierarchicalTaskDecomposer",
    "ConstraintSolver",
    "PlanOptimizer",
    "AdvancedPlanningEngine",
    "get_advanced_planning_engine",
]
