"""Goals, hierarchical planning, and plan criticism (5.0).

GoalInterpreter turns high-level requests into inspectable goals
(never executes). HierarchicalPlanner decomposes MISSION →
OBJECTIVES → TASKS → ACTIONS over the existing MissionPlanner with
bounded depth and explicit dependencies. PlanCritic validates plans
(VALID | NEEDS_REVISION | BLOCKED) before anything executes.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

MAX_SUBGOALS = 5
MAX_DEPTH = 3
MAX_STEPS = 12


class CriticVerdict(str, Enum):
    VALID = "valid"
    NEEDS_REVISION = "needs_revision"
    BLOCKED = "blocked"


class PlanningError(ValueError):
    """Malformed goal/plan or bound violation."""


def _utcnow() -> float:
    return time.time()


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


@dataclass
class Constraint:
    kind: str  # budget|risk|permission|time|scope
    detail: str
    limit: float | None = None


@dataclass
class Goal:
    goal_id: str = field(default_factory=lambda: _new_id("goal"))
    description: str = ""
    desired_state: str = ""
    success_criteria: list[str] = field(default_factory=list)
    failure_criteria: list[str] = field(default_factory=list)
    constraints: list[Constraint] = field(default_factory=list)
    required_capabilities: list[str] = field(default_factory=list)
    risk_level: str = "low"
    created_at: float = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        if not self.description:
            raise PlanningError("goal needs a description")
        self.description = self.description[:500]
        if self.risk_level not in ("low", "medium", "high"):
            raise PlanningError(f"invalid risk level: {self.risk_level!r}")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["constraints"] = [asdict(c) if not isinstance(c, dict)
                               else c for c in self.constraints]
        return data


@dataclass
class PlanStep:
    name: str
    kind: str = "action"  # action|verification|approval|wait
    args: dict[str, Any] = field(default_factory=dict)
    depends_on: list[int] = field(default_factory=list)
    expected: str = ""
    reversible: bool = True


@dataclass
class HierarchicalPlan:
    plan_id: str = field(default_factory=lambda: _new_id("hplan"))
    goal: str = ""
    objectives: list[str] = field(default_factory=list)
    steps: list[PlanStep] = field(default_factory=list)
    verification: dict[str, Any] = field(default_factory=dict)
    recovery: str = ""
    max_depth: int = 2

    def to_dict(self) -> dict[str, Any]:
        return {"plan_id": self.plan_id, "goal": self.goal,
                "objectives": self.objectives,
                "steps": [asdict(s) for s in self.steps],
                "verification": self.verification,
                "recovery": self.recovery, "max_depth": self.max_depth}


class GoalInterpreter:
    """Deterministic request -> Goal decomposition. Inspectable."""

    #: keyword -> (subgoal templates, capabilities, risk)
    PATTERNS: tuple = (
        (("deploy", "release", "publish"),
         ("inspect repository", "inspect dependencies", "run tests",
          "verify output"), ("vcs.read", "plan"), "medium"),
        (("test", "check", "verify", "health"),
         ("gather state", "run checks", "report results"),
         ("plan",), "low"),
        (("battery", "device", "phone"),
         ("read device state",),
         ("device.battery",), "low"),
        (("backup", "snapshot"),
         ("capture state", "verify capture"),
         ("storage.read",), "medium"),
    )

    def interpret(self, request: str, *,
                  constraints: list[Constraint] | None = None) -> Goal:
        if not request or not request.strip():
            raise PlanningError("goal request must not be empty")
        lowered = request.lower()
        subgoals: list[str] = ["understand request"]
        capabilities: list[str] = []
        risk = "low"
        for keywords, templates, caps, level in self.PATTERNS:
            if any(keyword in lowered for keyword in keywords):
                subgoals = list(templates)
                capabilities = list(caps)
                risk = level
                break
        return Goal(
            description=request.strip()[:500],
            desired_state=f"completed: {request.strip()[:200]}",
            success_criteria=[f"{sub} done" for sub in
                              subgoals[:MAX_SUBGOALS]],
            failure_criteria=["blocked prerequisite",
                              "verification failed"],
            constraints=list(constraints or []),
            required_capabilities=capabilities,
            risk_level=risk)

    def decompose(self, goal: Goal,
                  depth: int = 1) -> list[list[str]]:
        """Goal -> levels of subgoal lists. Bounded depth.

        Level 0 is the goal itself; criteria distribute round-robin
        across `depth` refinement levels (deeper levels refine the
        same objectives, never invent new ones).
        """
        if depth < 1 or depth > MAX_DEPTH:
            raise PlanningError(f"depth must be 1..{MAX_DEPTH}")
        criteria = list(goal.success_criteria[:MAX_SUBGOALS])
        levels: list[list[str]] = [[goal.description]]
        for level in range(depth):
            chunk = criteria[level::depth]
            if not chunk:
                break
            levels.append(chunk)
        return levels


class HierarchicalPlanner:
    """MISSION -> OBJECTIVES -> TASKS -> ACTIONS over MissionPlanner."""

    def __init__(self, planner: Any = None, max_steps: int = MAX_STEPS,
                 max_depth: int = MAX_DEPTH) -> None:
        self.planner = planner
        self.max_steps = max(1, max_steps)
        self.max_depth = max(1, max_depth)
        self.metrics: dict[str, int] = {"plans": 0}

    def plan(self, goal: Goal,
             context: dict[str, Any] | None = None) -> HierarchicalPlan:
        """Deterministic bounded decomposition. Never executes."""
        context = dict(context or {})
        objectives = [criterion.replace(" done", "")
                      for criterion in
                      goal.success_criteria[:MAX_SUBGOALS]]
        steps: list[PlanStep] = []
        for index, objective in enumerate(objectives):
            action = self._action_for(objective, context)
            steps.append(PlanStep(
                name=objective[:120], kind="action",
                args={"objective": objective[:120]},
                depends_on=[index - 1] if index else [],
                expected=f"{objective} observed complete",
                reversible=True))
            if len(steps) >= self.max_steps:
                break
        steps.append(PlanStep(
            name="verify outcomes", kind="verification",
            args={}, depends_on=list(range(len(steps))),
            expected="all objectives verified", reversible=True))
        plan = HierarchicalPlan(
            goal=goal.description, objectives=objectives, steps=steps,
            verification={"all_objectives": "verified"},
            recovery="stop at first failure; report blocked objective",
            max_depth=min(self.max_depth, MAX_DEPTH))
        self.metrics["plans"] += 1
        return plan

    def _action_for(self, objective: str,
                    context: dict[str, Any]) -> dict[str, Any]:
        if self.planner is not None:
            try:
                result = self.planner.plan({"conclusion": {
                    "summary": objective, "decision": objective}})
                if isinstance(result, dict) and result.get("action"):
                    return result
            except Exception:
                pass
        return {"action": "", "args": {},
                "reason": "no rule matched (observe only)"}


class PlanCritic:
    """Pre-execution validation: VALID | NEEDS_REVISION | BLOCKED."""

    IRREVERSIBLE_KEYWORDS = ("delete", "wipe", "format", "shutdown",
                             "rm ", "unpair", "revoke")

    def review(self, plan: HierarchicalPlan) -> dict[str, Any]:
        issues: list[str] = []
        if not plan.steps:
            return {"verdict": CriticVerdict.BLOCKED.value,
                    "issues": ["plan has no steps"]}
        names = [step.name for step in plan.steps]
        for index, step in enumerate(plan.steps):
            for dep in step.depends_on:
                if dep < 0 or dep >= len(plan.steps):
                    issues.append(f"step {index}: bad dependency {dep}")
                elif dep >= index:
                    issues.append(f"step {index}: forward dependency {dep}")
            lowered = f"{step.name} {step.args}".lower()
            if any(keyword in lowered
                   for keyword in self.IRREVERSIBLE_KEYWORDS):
                if step.reversible:
                    issues.append(f"step {index}: irreversible action "
                                  f"marked reversible")
            if step.kind == "action" and not step.expected:
                issues.append(f"step {index}: missing expected outcome")
        if not any(step.kind == "verification" for step in plan.steps):
            issues.append("plan has no verification step")
        if len(set(names)) != len(names):
            issues.append("duplicate step names")
        if any("missing prerequisite" in issue or "bad dependency" in issue
               for issue in issues):
            return {"verdict": CriticVerdict.BLOCKED.value, "issues": issues}
        if issues:
            return {"verdict": CriticVerdict.NEEDS_REVISION.value,
                    "issues": issues}
        return {"verdict": CriticVerdict.VALID.value, "issues": []}


__all__ = [
    "Constraint",
    "CriticVerdict",
    "Goal",
    "GoalInterpreter",
    "HierarchicalPlan",
    "HierarchicalPlanner",
    "PlanCritic",
    "PlanStep",
    "PlanningError",
]
