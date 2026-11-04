"""Enhanced Supervisor — coordinates Planner → Security Agent → Agent execution.

Every delegated step passes through SecurityAgent (PolicyEngine) before
execution. When an action requires human approval, the task pauses and
waits for the operator to approve/deny via `jarvis device approvals ...`.
Supports parallel execution of independent step groups.
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
    # Populated when the step is waiting for operator approval.
    waiting_for_approval: bool = False
    approval_token: str = ""


class EnhancedSupervisor:
    """Owns the full agent lifecycle with security gating and approval flow.

    Flow: goal → Planner (DAG) → Security Agent (gate each step) →
    Agent execution → Verification → Report.

    When SecurityAgent returns a verdict that requires approval:
    - Task transitions to WAITING state
    - Approval token is stored on the DelegatedStep
    - Operator approves/denies via `jarvis device approvals approve <token>`
    - Supervisor.resume_task() re-executes from the waiting step
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
        # Map task_id -> step_id that is waiting for approval
        self._waiting: dict[str, str] = {}

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
        """Execute a task: plan → security gate → delegate → verify.

        If resuming from a paused state, continues from the waiting step.
        """
        task = self.tasks.get(task_id)
        if task is None:
            raise KeyError(f"unknown task: {task_id}")

        # If resuming from waiting, pick up where we left off.
        if task.state == TaskState.WAITING and task_id in self._waiting:
            return self._resume_from_approval(task)

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
                # Store the approval token on the delegated step so the
                # operator can approve/deny via CLI.
                delegated = DelegatedStep(
                    step_id=sid, agent_name="", tool=step.tool,
                    args=step.args, security_verdict=verdict,
                    waiting_for_approval=True,
                    approval_token=verdict.approval_token,
                )
                self.delegations.append(delegated)

                task.state = TaskState.WAITING
                self._waiting[task_id] = sid
                task.history.append({
                    "event": "approval_required",
                    "step": sid,
                    "token": verdict.approval_token[:8],
                    "reason": "; ".join(verdict.decision.reasons),
                    "at": now(),
                })
                log.warning("Task waiting for approval",
                            task_id=task.task_id, step=sid,
                            token=verdict.approval_token[:8],
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

        # 4. Verify (set result first so _verify can read it)
        task.result = results
        task.state = TaskState.VERIFYING
        verified = self._verify(task, steps)
        task.state = TaskState.COMPLETED if verified else TaskState.FAILED
        task.progress = 1.0
        task.updated_at = now()
        task.history.append({"event": task.state.value, "at": now()})

        if not verified:
            task.error = "verification failed"

        log.info("Task finished", task_id=task.task_id, state=task.state.value,
                 steps=len(steps), verdicts=len(self.security.verdicts))
        return task

    def resume_task(self, task_id: str) -> Task:
        """Resume a task that was waiting for approval.

        Checks if the pending approval was granted. If approved, re-executes
        the waiting step and continues. If denied, fails the task.
        """
        task = self.tasks.get(task_id)
        if task is None:
            raise KeyError(f"unknown task: {task_id}")
        if task.state != TaskState.WAITING:
            return task
        if task_id not in self._waiting:
            return self._fail(task, "not waiting for approval")

        return self._resume_from_approval(task)

    def _resume_from_approval(self, task: Task) -> Task:
        """Internal: re-execute a task after its approval decision."""
        task_id = task.task_id
        sid = self._waiting[task_id]

        # Find the delegated step that is waiting for approval.
        delegated = None
        for d in self.delegations:
            if d.step_id == sid and d.waiting_for_approval:
                delegated = d
                break

        if delegated is None:
            return self._fail(task, f"no waiting step found for {sid}")

        token = delegated.approval_token
        approved = self.security.check_approval(token)

        if not approved:
            # Still pending or denied — leave task waiting.
            log.warning("Task still waiting for approval",
                        task_id=task_id, step=sid, token=token[:8])
            return task

        # Approved! Clear the waiting state and re-execute the step.
        log.info("Approval granted, resuming task",
                 task_id=task_id, step=sid, token=token[:8])

        # Mark the old delegated step as consumed.
        delegated.waiting_for_approval = False
        delegated.approval_token = ""
        task.state = TaskState.RUNNING
        del self._waiting[task_id]

        # Re-run the security gate (in case policy changed) and delegate.
        step_dict = next(s for s in task.steps if s["step_id"] == sid)
        step = EnhancedPlanStep(**step_dict)

        verdict = self.security.evaluate(
            action=step.tool,
            args=step.args,
            context={"step_id": sid, "goal": task.goal[:100]},
        )

        if not verdict.allowed:
            return self._fail(task, f"step {sid} now blocked by security: "
                                 f"{'; '.join(verdict.decision.reasons)}")

        agent = self.registry.by_name(step.agent)
        if agent is None:
            return self._fail(task, f"no agent named {step.agent}")

        task.assigned_agent = agent.name
        agent.state = "working"

        agent.send({
            "task_id": task.task_id,
            "step_id": sid,
            "step": step.to_dict(),
        })

        try:
            outcome = self.on_step(step, agent) if self.on_step else {"ok": True}
        except Exception as exc:
            outcome = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        # Replace the old delegated step with the new result.
        new_delegated = DelegatedStep(
            step_id=sid, agent_name=agent.name, tool=step.tool,
            args=step.args, security_verdict=verdict,
            started_at=time.time(),
        )
        self.delegations.append(new_delegated)

        new_delegated.ended_at = time.time()
        new_delegated.duration_ms = round(
            (new_delegated.ended_at - new_delegated.started_at) * 1000, 2)
        new_delegated.result = outcome

        if not outcome.get("ok"):
            agent.tasks_failed += 1
            agent.state = "idle"
            return self._fail(task, f"step {sid} failed after approval: "
                                 f"{outcome.get('error', outcome)}")

        agent.tasks_done += 1
        agent.state = "idle"
        log.info("Step completed after approval",
                 task_id=task_id, step=sid, agent=agent.name,
                 duration_ms=new_delegated.duration_ms)

        # Continue with remaining steps.
        results: dict[str, Any] = {}
        # Collect results from already-completed steps.
        for d in self.delegations:
            if d.step_id != sid and d.result is not None:
                results[d.step_id] = d.result

        order = self.planner.validate(
            [EnhancedPlanStep(**s) for s in task.steps])
        by_id = {s.step_id: s for s in
                 [EnhancedPlanStep(**s) for s in task.steps]}

        start_index = order.index(sid) + 1
        for index, next_sid in enumerate(order[start_index:], start=start_index):
            next_step = by_id[next_sid]

            # Security gate for remaining steps.
            next_verdict = self.security.evaluate(
                action=next_step.tool,
                args=next_step.args,
                context={"step_id": next_sid, "goal": task.goal[:100]},
            )

            if next_verdict.decision.requires_approval:
                # Another approval needed — pause again.
                next_delegated = DelegatedStep(
                    step_id=next_sid, agent_name="", tool=next_step.tool,
                    args=next_step.args, security_verdict=next_verdict,
                    waiting_for_approval=True,
                    approval_token=next_verdict.approval_token,
                )
                self.delegations.append(next_delegated)

                task.state = TaskState.WAITING
                self._waiting[task_id] = next_sid
                task.history.append({
                    "event": "approval_required",
                    "step": next_sid,
                    "token": next_verdict.approval_token[:8],
                    "reason": "; ".join(next_verdict.decision.reasons),
                    "at": now(),
                })
                log.warning("Task waiting for another approval",
                            task_id=task_id, step=next_sid,
                            token=next_verdict.approval_token[:8])
                return task

            if not next_verdict.allowed:
                return self._fail(task, f"step {next_sid} blocked by security: "
                                     f"{'; '.join(next_verdict.decision.reasons)}")

            next_agent = self.registry.by_name(next_step.agent)
            if next_agent is None:
                return self._fail(task, f"no agent named {next_step.agent}")

            task.assigned_agent = next_agent.name
            task.progress = index / max(1, len(order))
            next_agent.state = "working"

            next_delegated = DelegatedStep(
                step_id=next_sid, agent_name=next_agent.name,
                tool=next_step.tool, args=next_step.args,
                security_verdict=next_verdict,
                started_at=time.time(),
            )
            self.delegations.append(next_delegated)

            next_agent.send({
                "task_id": task.task_id,
                "step_id": next_sid,
                "step": next_step.to_dict(),
            })

            try:
                next_outcome = self.on_step(next_step, next_agent) \
                    if self.on_step else {"ok": True}
            except Exception as exc:
                next_outcome = {"ok": False,
                                "error": f"{type(exc).__name__}: {exc}"}

            next_delegated.ended_at = time.time()
            next_delegated.duration_ms = round(
                (next_delegated.ended_at - next_delegated.started_at) * 1000, 2)
            next_delegated.result = next_outcome

            results[next_sid] = next_outcome

            if not next_outcome.get("ok"):
                next_agent.tasks_failed += 1
                next_agent.state = "idle"
                return self._fail(task, f"step {next_sid} failed: "
                                     f"{next_outcome.get('error', next_outcome)}")

            next_agent.tasks_done += 1
            next_agent.state = "idle"

        # 4. Verify (set result first so _verify can read it)
        all_results = {**results, sid: new_delegated.result}
        task.result = all_results
        task.state = TaskState.VERIFYING
        remaining_steps = [EnhancedPlanStep(**s) for s in task.steps]
        verified = all(bool(all_results.get(s.step_id, {}).get("ok"))
                       for s in remaining_steps)
        task.state = TaskState.COMPLETED if verified else TaskState.FAILED
        task.progress = 1.0
        task.updated_at = now()
        task.history.append({"event": task.state.value, "at": now()})

        if not verified:
            task.error = "verification failed"

        log.info("Task finished after approval resume",
                 task_id=task_id, state=task.state.value)
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

    # -- pending approvals -------------------------------------------------
    def pending_approvals(self) -> list[dict[str, Any]]:
        """List tasks waiting for approval, with their tokens and details."""
        pending = []
        for task_id, sid in self._waiting.items():
            task = self.tasks[task_id]
            delegated = None
            for d in self.delegations:
                if d.step_id == sid and d.waiting_for_approval:
                    delegated = d
                    break
            if delegated is None:
                continue
            token = delegated.approval_token
            pending.append({
                "task_id": task_id,
                "goal": task.goal,
                "step_id": sid,
                "token": token,
                "token_prefix": token[:8],
                "action": delegated.tool,
                "actor": delegated.security_verdict.actor
                if delegated.security_verdict else "security",
                "reasons": delegated.security_verdict.decision.reasons
                if delegated.security_verdict else [],
                "risk": delegated.security_verdict.decision.risk
                if delegated.security_verdict else 0.0,
                "risk_level": delegated.security_verdict.decision.risk_level.value
                if delegated.security_verdict else "unknown",
            })
        return pending

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
            "waiting_for_approval": len(self._waiting),
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
            "waiting_step": self._waiting.get(task_id),
            "duration_ms": round((task.updated_at - task.created_at) * 1000, 1),
        }