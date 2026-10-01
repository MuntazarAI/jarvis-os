"""Agent system: registry, lifecycle, DAG planner, supervisor orchestration."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

from ..core.types import Task, TaskState, new_id, now


# -- agent -----------------------------------------------------------------
@dataclass
class Agent:
    name: str
    role: str
    model: str = "local-fast"
    tools: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    memory_scope: str = "shared"
    limits: dict[str, Any] = field(default_factory=dict)
    agent_id: str = ""
    state: str = "idle"
    mailbox: list[dict[str, Any]] = field(default_factory=list)
    tasks_done: int = 0
    tasks_failed: int = 0

    def __post_init__(self) -> None:
        if not self.agent_id:
            self.agent_id = new_id("agent")

    def send(self, message: dict[str, Any]) -> None:
        self.mailbox.append({**message, "at": now()})

    def receive(self) -> dict[str, Any] | None:
        return self.mailbox.pop(0) if self.mailbox else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id, "name": self.name, "role": self.role,
            "model": self.model, "tools": self.tools, "permissions": self.permissions,
            "state": self.state, "tasks_done": self.tasks_done,
            "tasks_failed": self.tasks_failed,
        }


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, Agent] = {}

    def spawn(self, agent: Agent) -> Agent:
        if agent.agent_id in self._agents:
            raise ValueError(f"agent already registered: {agent.agent_id}")
        self._agents[agent.agent_id] = agent
        return agent

    def shutdown(self, agent_id: str) -> bool:
        agent = self._agents.get(agent_id)
        if not agent:
            return False
        agent.state = "shutdown"
        return True

    def get(self, agent_id: str) -> Agent | None:
        return self._agents.get(agent_id)

    def by_name(self, name: str) -> Agent | None:
        for agent in self._agents.values():
            if agent.name == name:
                return agent
        return None

    def list_agents(self) -> list[Agent]:
        return list(self._agents.values())

    def capable_of(self, tool: str) -> list[Agent]:
        return [a for a in self._agents.values() if tool in a.tools]


def default_agents() -> list[Agent]:
    return [
        Agent(name="supervisor", role="orchestrate agents and own the loop",
              model="local-reasoning", tools=[], permissions=["*"]),
        Agent(name="planner", role="break goals into DAG steps",
              model="local-reasoning", tools=[], permissions=["plan"]),
        Agent(name="researcher", role="search and synthesize information",
              model="local-fast", tools=["web_fetch", "filesystem_read"],
              permissions=["net.fetch", "fs.read"]),
        Agent(name="coder", role="write, test and debug code",
              model="local-reasoning", tools=["filesystem_read", "filesystem_write",
                                              "terminal_run", "python_run", "git_status"],
              permissions=["fs.read", "fs.write", "exec", "exec.eval", "vcs.read"]),
        Agent(name="analyst", role="evidence and hypothesis analysis",
              model="local-reasoning", tools=["filesystem_read", "python_run"],
              permissions=["fs.read", "exec.eval"]),
        Agent(name="computer", role="operate the local machine",
              model="local-fast", tools=["terminal_run", "filesystem_read",
                                         "filesystem_write", "system_probe",
                                         "screen_capture", "window_list",
                                         "clipboard_read"],
              permissions=["exec", "fs.read", "fs.write", "desktop.screenshot",
                           "desktop.windows", "clipboard.read"]),
        Agent(name="guardian", role="validate actions against policy",
              model="local-fast", tools=["system_probe"], permissions=[]),
        Agent(name="librarian", role="memory and knowledge queries",
              model="local-fast", tools=["filesystem_read"],
              permissions=["fs.read"]),
    ]


# -- DAG planner -------------------------------------------------------------
@dataclass
class PlanStep:
    step_id: str
    description: str
    agent: str = ""
    tool: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    verification: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"step_id": self.step_id, "description": self.description,
                "agent": self.agent, "tool": self.tool, "args": self.args,
                "depends_on": self.depends_on, "verification": self.verification}


class Planner:
    """Builds validated directed acyclic graphs of steps."""

    VERB_TOOL = [
        ("read", "filesystem_read"), ("list", "filesystem_read"),
        ("write", "filesystem_write"), ("create", "filesystem_write"),
        ("run", "terminal_run"), ("execute", "terminal_run"),
        ("calculate", "python_run"), ("compute", "python_run"),
        ("fetch", "web_fetch"), ("search", "web_fetch"),
        ("git", "git_status"), ("probe", "system_probe"), ("check system", "system_probe"),
    ]

    def plan(self, goal: str) -> list[PlanStep]:
        from ..cognition.cognition import ExecutiveFunction
        subtasks = ExecutiveFunction.decompose(goal)
        steps: list[PlanStep] = []
        prev = ""
        for i, sub in enumerate(subtasks):
            step_id = f"s{i + 1}"
            tool = self._tool_for(sub)
            agent = self._agent_for(tool)
            deps = [prev] if prev else []
            steps.append(PlanStep(
                step_id=step_id, description=sub, agent=agent, tool=tool,
                depends_on=deps,
                verification=f"confirm: {sub[:60]}",
            ))
            prev = step_id
        self.validate(steps)
        return steps

    @classmethod
    def _tool_for(cls, description: str) -> str:
        low = description.lower()
        for verb, tool in cls.VERB_TOOL:
            if verb in low:
                return tool
        return "system_probe"

    @staticmethod
    def _agent_for(tool: str) -> str:
        mapping = {"filesystem_read": "librarian", "filesystem_write": "coder",
                   "terminal_run": "computer", "python_run": "coder",
                   "web_fetch": "researcher", "git_status": "coder",
                   "system_probe": "computer"}
        return mapping.get(tool, "analyst")

    @staticmethod
    def validate(steps: list[PlanStep]) -> list[str]:
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

    @staticmethod
    def independent_groups(steps: list[PlanStep]) -> list[list[str]]:
        """Group steps that can run in parallel (same dependency depth)."""
        depth: dict[str, int] = {}
        by_id = {s.step_id: s for s in steps}
        order = Planner.validate(steps)

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


# -- supervisor --------------------------------------------------------------
class Supervisor:
    """Owns the agent lifecycle: receive → plan → delegate → verify → report."""

    def __init__(self, registry: AgentRegistry | None = None,
                 on_step: Callable[[PlanStep, Agent], dict[str, Any] | None] | None = None) -> None:
        self.registry = registry or AgentRegistry()
        for agent in default_agents():
            if self.registry.by_name(agent.name) is None:
                self.registry.spawn(agent)
        self.planner = Planner()
        self.on_step = on_step
        self.tasks: dict[str, Task] = {}
        self.delegations: list[dict[str, Any]] = []

    def submit(self, goal: str, priority: int = 5) -> Task:
        task = Task(goal=goal, priority=priority)
        self.tasks[task.task_id] = task
        return task

    def run_task(self, task_id: str, timeout_steps: int = 50) -> Task:
        task = self.tasks.get(task_id)
        if task is None:
            raise KeyError(f"unknown task: {task_id}")
        task.state = TaskState.PLANNING
        task.history.append({"event": "planning_started", "at": now()})
        try:
            steps = self.planner.plan(task.goal)
        except ValueError as exc:
            return self._fail(task, f"planning failed: {exc}")
        task.steps = [s.to_dict() for s in steps]
        task.state = TaskState.RUNNING
        order = self.planner.validate(steps)
        by_id = {s.step_id: s for s in steps}
        results: dict[str, Any] = {}
        for index, sid in enumerate(order[:timeout_steps]):
            step = by_id[sid]
            agent = self.registry.by_name(step.agent)
            if agent is None:
                return self._fail(task, f"no agent named {step.agent}")
            task.assigned_agent = agent.name
            task.progress = index / max(1, len(order))
            agent.state = "working"
            agent.send({"task_id": task.task_id, "step": step.to_dict()})
            try:
                outcome = self.on_step(step, agent) if self.on_step else {"ok": True}
            except Exception as exc:
                outcome = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            results[sid] = outcome
            self.delegations.append({"task_id": task.task_id, "step": sid,
                                     "agent": agent.name, "ok": bool(outcome.get("ok"))})
            if not outcome.get("ok"):
                agent.tasks_failed += 1
                agent.state = "idle"
                return self._fail(task, f"step {sid} failed: {outcome.get('error', outcome)}")
            agent.tasks_done += 1
            agent.state = "idle"
        task.state = TaskState.VERIFYING
        task.result = results
        task.progress = 1.0
        verified = self._verify(task, steps)
        task.state = TaskState.COMPLETED if verified else TaskState.FAILED
        if not verified:
            task.error = "verification failed"
        task.updated_at = now()
        task.history.append({"event": task.state.value, "at": now()})
        return task

    @staticmethod
    def _verify(task: Task, steps: list[PlanStep]) -> bool:
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

    def vote(self, candidates: list[str], votes: dict[str, str]) -> str:
        """Multi-agent consensus: majority vote over candidate answers."""
        counts: dict[str, int] = {}
        for _agent, choice in votes.items():
            if choice in candidates:
                counts[choice] = counts.get(choice, 0) + 1
        if not counts:
            return candidates[0] if candidates else ""
        return max(counts, key=lambda c: (counts[c], c))

    def status(self) -> dict[str, Any]:
        return {
            "agents": [a.to_dict() for a in self.registry.list_agents()],
            "tasks": len(self.tasks),
            "delegations": len(self.delegations),
        }
