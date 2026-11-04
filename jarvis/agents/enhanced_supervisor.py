"""Enhanced Supervisor — coordinates Planner → Security Agent → Agent execution.

Every delegated step passes through SecurityAgent (PolicyEngine) before
execution. Supports parallel execution of independent step groups.
Produces AgentResult objects per the contract system.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from ..core.logging import get_module_logger
from ..core.types import Task, TaskState, new_id, now
from ..policy.policy import PolicyEngine
from .agents import AgentRegistry, Agent, PlanStep
from .enhanced_planner import EnhancedPlanStep, EnhancedPlanner
from .security_agent import SecurityAgent

log = get_module_logger(__name__)


@dataclass
class DelegatedStep:
    """A step delegated to an agent with security verdict."""
    step_id: str
    agent_name: str
    tool: str
    args: dict[str, Any]
    security_verdict: Any = None
    result: Any = None
    error: str = ""
    started_at: float = 0.0
    ended_at: float = 0.0
    duration_ms: float = 0.0


class EnhancedSupervisor:
    """Owns the full agent lifecycle with security gating.

    Flow: goal → Planner (DAG) → Security Agent (gate each step) →
    Agent execution → Verification → Report.
    """

    def __init__(self, registry: AgentRegistry | None = None,
                 policy: PolicyEngine | None = None,
                 on_step: Callable[[PlanStep, Agent], dict[str, Any]] | None = None) -> None:
        self.registry = registry or AgentRegistry()
        from .agents import default_agents
        for agent in default_agents():
            if self.registry.by_name(agent.name) is None:
                self.registry.spawn(agent)
        self.planner = EnhancedPlanner(self.registry)
        self.security = SecurityAgent(policy or PolicyEngine(), actor="supervisor")
        self.on_step = on_step
        self.tasks: dict[str, Task] = {}
        self.delegations: list[DelegatedStep] = []

    # -- task submission ---------------------------------------------------
    def submit(self, goal: str, priority: int = 5,
               require_approval: bool = False) -> Task:
        """Create a new task from a goal."""
        task = Task(goal=goal, priority=priority)
        self.tasks[task.task_id] = task
        log.info("Task submitted", task_id=task.task_id, goal=goal[:100])
        return task

    def run_task(self, task_id: str, timeout_steps: int = 50,
                 auto_approve: bool = False) -> Task:
        """Execute a task: plan → security gate → delegate → verify."""
        task = self.tasks.get(task_id)
        if task is None:
            raise KeyError(f"unknown task: {task_id}")

        task.state = TaskState.PLANNING
        task.history.append({"event": "planning_started", "at": now()})

        # 1. Plan
        try:
            steps = self.planner.plan(task.goal)
        except ValueError as exc:
            return self._fail(task, f"planning failed: {exc}")

        task.steps = [s.to_dict() for s in steps]
        log.info("Task planned", task_id=task.task_id, steps=len(steps))

        # 2. Execute in dependency order with security gating
        task.state = TaskState.RUNNING
        order = self.planner.validate(steps)
        by_id = {s.step_id: s for s in steps}
        results: dict[str, Any] = {}

        for index, sid in enumerate(order[:timeout_steps]):
            step = by_id[sid]

            # Security gate
            verdict = self.security.evaluate(
                action=step.tool,
                args=step.args,
                context={"step_id": sid, "goal": task.goal[:100]},
            )

            # Require approval if needed
            if verdict.decision.requires_approval and not auto_approve:
                task.state = TaskState.WAITING
                task.history.append({
                    "event": "approval_required",
                    "step": sid,
                    "reason": "; ".join(verdict.decision.reasons),
                    "at": now(),
                })
                log.warning("Task waiting for approval",
                            task_id=task.task_id, step=sid,
                            reasons=verdict.decision.reasons)
                return task

            if not verdict.allowed:
                return self._fail(task, f"step {sid} blocked by security: "
                                     f"{'; '.join(verdict.decision.reasons)}")

            # 3. Delegate to agent
            agent = self.registry.by_name(step.agent)
            if agent is None:
                return self._fail(task, f"no agent named {step.agent}")

            task.assigned_agent = agent.name
            task.progress = index / max(1, len(order))
            agent.state = "working"

            delegated = DelegatedStep(
                step_id=sid, agent_name=agent.name, tool=step.tool,
                args=step.args, security_verdict=verdict,
                started_at=time.time(),
            )
            self.delegations.append(delegated)

            agent.send({
                "task_id": task.task_id,
                "step_id": sid,
                "step": step.to_dict(),
            })

            try:
                outcome = self.on_step(step, agent) if self.on_step else {"ok": True}
            except Exception as exc:
                outcome = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

            delegated.ended_at = time.time()
            delegated.duration_ms = round((delegated.ended_at - delegated.started_at) * 1000, 2)
            delegated.result = outcome

            results[sid] = outcome

            if not outcome.get("ok"):
                agent.tasks_failed += 1
                agent.state = "idle"
                return self._fail(task, f"step {sid} failed: "
                                     f"{outcome.get('error', outcome)}")

            agent.tasks_done += 1
            agent.state = "idle"
            log.info("Step completed", task_id=task.task_id, step=sid,
                     agent=agent.name, duration_ms=delegated.duration_ms)

        # 4. Verify
        task.state = TaskState.VERIFYING
        verified = self._verify(task, steps)
        task.state = TaskState.COMPLETED if verified else TaskState.FAILED
        task.result = results
        task.progress = 1.0
        task.updated_at = now()
        task.history.append({"event": task.state.value, "at": now()})

        if not verified:
            task.error = "verification failed"

        log.info("Task finished", task_id=task.task_id, state=task.state.value,
                 steps=len(steps), verdicts=len(self.security.verdicts))
        return task

    @staticmethod
    def _verify(task: Task, steps: list[EnhancedPlanStep]) -> bool:
        if not steps:
            return False
        results = task.result or {}
        return all(bool(results.get(s.step_id, {}).get("ok")) for s in steps)

    @staticmethod
    def _fail(task: Task, error: str) -> Task:
        task.state = TaskState.FAILED
        task.error = error
        task.updated_at = now()
        task.history.append({"event": "failed", "error": error, "at": now()})
        return task

    # -- parallel groups ---------------------------------------------------
    def independent_groups(self, task_id: str) -> list[list[str]]:
        """Return step groups that can run in parallel for a task."""
        task = self.tasks.get(task_id)
        if task is None or not task.steps:
            return []
        steps = [EnhancedPlanStep(**s) for s in task.steps]
        return self.planner.independent_groups(steps)

    # -- status ------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        return {
            "agents": [a.to_dict() for a in self.registry.list_agents()],
            "tasks": len(self.tasks),
            "delegations": len(self.delegations),
            "security": self.security.status(),
        }

    def task_status(self, task_id: str) -> dict[str, Any] | None:
        task = self.tasks.get(task_id)
        if task is None:
            return None
        return {
            "task_id": task.task_id,
            "goal": task.goal,
            "state": task.state.value,
            "progress": task.progress,
            "steps": len(task.steps),
            "assigned_agent": task.assigned_agent,
            "error": task.error,
            "duration_ms": round((task.updated_at - task.created_at) * 1000, 1),
        }