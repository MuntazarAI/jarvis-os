"""Enhanced Planner — builds validated DAGs with AgentRegistry capability matching."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core.logging import get_module_logger
from ..core.types import new_id
from .agents import PlanStep

log = get_module_logger(__name__)


@dataclass
class EnhancedPlanStep(PlanStep):
    """A plan step with security and capability metadata."""
    risk_level: str = "low"
    requires_approval: bool = False
    can_parallel: bool = True
    estimated_seconds: float = 5.0

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data.update({
            "risk_level": self.risk_level,
            "requires_approval": self.requires_approval,
            "can_parallel": self.can_parallel,
            "estimated_seconds": self.estimated_seconds,
        })
        return data


class EnhancedPlanner:
    """Builds DAGs of steps, matching each to the best-capable agent.

    Uses AgentRegistry to find agents capable of each tool, assigns
    risk levels, and groups independent steps for parallel execution.
    """

    # Verb → (tool, risk_level, default_agent, estimated_seconds)
    # Destructive/high-risk verbs checked FIRST so they take priority
    # over benign verbs that may appear in the same description.
    VERB_MAP = [
        ("delete", "filesystem_write", "high", "computer", 5.0),
        ("remove", "filesystem_write", "high", "computer", 5.0),
        ("format", "filesystem_write", "destructive", "computer", 5.0),
        ("wipe", "filesystem_write", "destructive", "computer", 5.0),
        ("drop", "filesystem_write", "destructive", "computer", 5.0),
        ("shutdown", "terminal_run", "destructive", "computer", 10.0),
        ("kill", "terminal_run", "high", "computer", 10.0),
        ("chmod", "terminal_run", "high", "computer", 5.0),
        ("chown", "terminal_run", "high", "computer", 5.0),
        ("mkfs", "terminal_run", "destructive", "computer", 5.0),
        ("read", "filesystem_read", "low", "librarian", 3.0),
        ("list", "filesystem_read", "low", "librarian", 3.0),
        ("write", "filesystem_write", "medium", "coder", 5.0),
        ("create", "filesystem_write", "medium", "coder", 5.0),
        ("run", "terminal_run", "medium", "computer", 10.0),
        ("execute", "terminal_run", "medium", "computer", 10.0),
        ("calculate", "python_run", "medium", "coder", 10.0),
        ("compute", "python_run", "medium", "coder", 10.0),
        ("fetch", "web_fetch", "medium", "researcher", 15.0),
        ("search", "web_fetch", "medium", "researcher", 15.0),
        ("git", "git_status", "low", "coder", 5.0),
        ("probe", "system_probe", "low", "computer", 3.0),
        ("check system", "system_probe", "low", "computer", 3.0),
    ]

    def __init__(self, registry=None) -> None:
        from .agents import AgentRegistry
        self.registry = registry or AgentRegistry()
        from .agents import default_agents
        for agent in default_agents():
            if self.registry.by_name(agent.name) is None:
                self.registry.spawn(agent)

    def plan(self, goal: str) -> list[EnhancedPlanStep]:
        """Decompose a goal into validated, capability-matched steps."""
        from ..cognition.cognition import ExecutiveFunction
        subtasks = ExecutiveFunction.decompose(goal)

        steps: list[EnhancedPlanStep] = []
        prev = ""
        for i, sub in enumerate(subtasks):
            step_id = f"s{i + 1}"
            tool, risk_level, agent_name, est_seconds = self._match(sub)
            agent = self.registry.by_name(agent_name)
            if agent is None:
                agent_name = "analyst"
                agent = self.registry.by_name(agent_name)
            deps = [prev] if prev else []
            requires_approval = risk_level in ("high", "destructive")
            steps.append(EnhancedPlanStep(
                step_id=step_id, description=sub, agent=agent_name,
                tool=tool, args={}, depends_on=deps,
                verification=f"confirm: {sub[:60]}",
                risk_level=risk_level,
                requires_approval=requires_approval,
                estimated_seconds=est_seconds,
            ))
            prev = step_id

        self.validate(steps)
        return steps

    def _match(self, description: str) -> tuple[str, str, str, float]:
        """Match a step description to (tool, risk_level, agent, seconds)."""
        low = description.lower()
        for verb, tool, risk, agent, seconds in self.VERB_MAP:
            if verb in low:
                return tool, risk, agent, seconds
        return "system_probe", "low", "analyst", 3.0

    def validate(self, steps: list[EnhancedPlanStep]) -> list[str]:
        """Topological validation. Returns execution order. Raises on cycles."""
        ids = {s.step_id for s in steps}
        for step in steps:
            for dep in step.depends_on:
                if dep not in ids:
                    raise ValueError(f"step {step.step_id} depends on unknown {dep}")

        order: list[str] = []
        resolved: set[str] = set()
        remaining = {s.step_id: set(s.depends_on) for s in steps}
        while remaining:
            ready = sorted(sid for sid, deps in remaining.items() if deps <= resolved)
            if not ready:
                raise ValueError(f"dependency cycle among: {sorted(remaining)}")
            for sid in ready:
                order.append(sid)
                resolved.add(sid)
                del remaining[sid]
        return order

    def independent_groups(self, steps: list[EnhancedPlanStep]) -> list[list[str]]:
        """Group steps by dependency depth for parallel execution."""
        depth: dict[str, int] = {}
        by_id = {s.step_id: s for s in steps}
        order = self.validate(steps)

        def level(sid: str) -> int:
            if sid in depth:
                return depth[sid]
            deps = by_id[sid].depends_on
            depth[sid] = 0 if not deps else 1 + max(level(d) for d in deps)
            return depth[sid]

        groups: dict[int, list[str]] = {}
        for sid in order:
            groups.setdefault(level(sid), []).append(sid)
        return [groups[k] for k in sorted(groups)]

    def agents_for_tool(self, tool: str):
        """Return registry agents capable of a given tool."""
        return self.registry.capable_of(tool)


# Convenience function for quick planning
def plan_goal(goal: str, registry=None) -> list[EnhancedPlanStep]:
    """Plan a goal into enhanced steps."""
    return EnhancedPlanner(registry).plan(goal)