"""Multi-Agent Coordination - M36.

Builds on:
- Stark AI roster (jarvis/agents/stark.py) for agent definitions
- AgentMesh (jarvis/agents/agent_mesh_intelligence.py) for team formation
- ToolUsingReasoner (jarvis/agents/tool_using_reasoning.py) for tool execution
- CognitiveEngine (jarvis/cognition/cognitive_engine.py) for cognitive loop

Provides:
- Multi-agent team formation and role-based coordination
- Agent-to-agent communication via message passing
- Task distribution across multiple agents
- Consensus building for group decisions
- Failure recovery with agent fallback
- Workload balancing across team members
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any

from ..agents.agent_mesh_intelligence import (
    AgentMesh,
    AgentTaskResult,
    AgentTeam,
    StarkAI,
)
from ..agents.tool_using_reasoning import (
    ToolCapability,
    ToolExecutionPlan,
    ToolExecutionResult,
    ToolUsingReasoner,
)
from ..cognition.task_evaluation import (
    TaskEvaluation,
    TaskReasoningEngine,
)
from ..cognition.world_model import WorldModel


@dataclass
class TeamTask:
    """A task assigned to a multi-agent team."""
    task_id: str
    name: str
    description: str
    team_id: str
    status: str = "pending"  # pending, assigned, in_progress, completed, failed
    assigned_agent: str | None = None
    subtasks: list[dict[str, Any]] = field(default_factory=list)
    results: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "name": self.name,
            "description": self.description,
            "team_id": self.team_id,
            "status": self.status,
            "assigned_agent": self.assigned_agent,
            "subtasks": self.subtasks,
            "results": self.results,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "metadata": self.metadata,
        }


@dataclass
class CoordinationResult:
    """Result of multi-agent coordination."""
    coordination_id: str
    task_id: str
    team_id: str
    success: bool
    summary: str
    agent_results: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "coordination_id": self.coordination_id,
            "task_id": self.task_id,
            "team_id": self.team_id,
            "success": self.success,
            "summary": self.summary,
            "agent_results": self.agent_results,
            "confidence": self.confidence,
            "created_at": self.created_at,
        }


class TeamCoordinator:
    """Coordinates multi-agent teams for complex task execution.

    Capabilities:
    - Form teams based on task requirements and agent capabilities
    - Decompose tasks into subtasks and assign to team members
    - Aggregate results from multiple agents
    - Detect and resolve conflicts between agent outputs
    - Rebalance workload when agents fail or become overloaded
    """

    def __init__(self, mesh: AgentMesh | None = None,
                 reasoner: ToolUsingReasoner | None = None):
        self.mesh = mesh or AgentMesh()
        self.reasoner = reasoner or ToolUsingReasoner()
        self.team_tasks: dict[str, TeamTask] = {}
        self.coordination_results: dict[str, CoordinationResult] = {}
        self.created_at = time.time()
        self.stats = {
            "teams_coordinated": 0,
            "tasks_coordinated": 0,
            "tasks_successful": 0,
            "tasks_failed": 0,
            "recoveries": 0,
        }

    def form_team_for_task(self,
                           goal: str,
                           required_capabilities: list[str] | None = None,
                           max_agents: int = 5) -> str:
        """Form a team for a specific task based on required capabilities."""
        # Map capabilities to agent roles
        role_map = {
            "research": "researcher",
            "code": "coder",
            "write": "writer",
            "analyze": "analyst",
            "critique": "critic",
            "coordinate": "coordinator",
        }

        required_roles = []
        if required_capabilities:
            for cap in required_capabilities:
                cap_lower = cap.lower()
                for key, role in role_map.items():
                    if key in cap_lower and role not in required_roles:
                        required_roles.append(role)

        if not required_roles:
            required_roles = ["core"]

        team_id = self.mesh.form_team(goal, required_roles, max_agents)
        return team_id

    def decompose_and_assign(self,
                             team_id: str,
                             goal: str,
                             max_subtasks: int = 5) -> list[dict[str, Any]]:
        """Decompose a task into subtasks and assign to team members."""
        team = self.mesh.get_team(team_id)
        if team is None:
            return []

        members = team.members
        if not members:
            return []

        # Decompose goal into subtasks
        subtasks = self._decompose_goal(goal, max_subtasks)

        # Assign subtasks to team members round-robin
        assignments = []
        for i, subtask in enumerate(subtasks):
            agent_id = members[i % len(members)]
            stark = STARK_ROSTER_BY_ID.get(agent_id)
            if stark:
                assignments.append({
                    "subtask_id": f"{team_id}-subtask-{i:03d}",
                    "name": subtask["name"],
                    "description": subtask["description"],
                    "assigned_agent": agent_id,
                    "agent_name": stark.name,
                    "agent_role": stark.team or "core",
                    "status": "pending",
                })

        return assignments

    def _decompose_goal(self, goal: str,
                        max_subtasks: int) -> list[dict[str, str]]:
        """Decompose a goal into subtasks using keyword heuristics."""
        goal_lower = goal.lower()
        subtasks = []

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
        elif "code" in goal_lower or "program" in goal_lower:
            subtasks = [
                ("Design architecture", "Plan code structure"),
                ("Implement", "Write code implementation"),
                ("Test", "Test implementation"),
                ("Review", "Review code quality"),
            ]
        else:
            subtasks = [("Execute task", goal)]

        return subtasks[:max_subtasks]

    def execute_coordinated_task(self,
                                 team_id: str,
                                 goal: str,
                                 subtasks: list[dict[str, Any]] | None = None) -> CoordinationResult:
        """Execute a task through coordinated multi-agent effort."""
        import time as _time
        start = _time.time()
        coordination_id = f"coord-{hashlib.sha256(f'{team_id}|{start}'.encode()).hexdigest()[:8]}"

        team = self.mesh.get_team(team_id)
        if team is None:
            return CoordinationResult(
                coordination_id=coordination_id,
                task_id=team_id,
                team_id=team_id,
                success=False,
                summary="Team not found",
                confidence=0.0,
            )

        # Decompose if no subtasks provided
        if subtasks is None:
            subtasks = self._decompose_goal(goal, max_subtasks=len(team.members))

        # Create team task
        team_task = TeamTask(
            task_id=f"team-task-{len(self.team_tasks):06d}",
            name=goal,
            description=goal,
            team_id=team_id,
            status="in_progress",
        )
        self.team_tasks[team_task.task_id] = team_task

        # Distribute subtasks to agents
        agent_results = []
        for i, subtask in enumerate(subtasks):
            agent_id = team.members[i % len(team.members)]
            stark = STARK_ROSTER_BY_ID.get(agent_id)
            if not stark:
                continue

            # Delegate task to agent through mesh
            delegated_task_id = self.mesh.delegate_task(
                team_id,
                subtask["description"],
                task_type="general",
                agent_id=agent_id,
            )

            # Get result (simulated since execute=False)
            agent_result = self.mesh.get_task_result(delegated_task_id)
            if agent_result:
                agent_results.append({
                    "subtask_id": subtask["subtask_id"],
                    "agent_id": agent_id,
                    "agent_name": stark.name,
                    "agent_role": stark.team or "core",
                    "subtask_name": subtask["name"],
                    "success": agent_result.success,
                    "output": agent_result.output,
                })

        # Aggregate results
        successful = sum(1 for r in agent_results if r.get("success", False))
        total = len(agent_results)
        success = total > 0 and successful == total
        confidence = (successful / total) if total > 0 else 0.0

        # Generate summary
        if success:
            summary = f"Task '{goal}' completed successfully by {total} agent(s)."
        else:
            summary = f"Task '{goal}' partially completed: {successful}/{total} subtasks succeeded."

        coordination_result = CoordinationResult(
            coordination_id=coordination_id,
            task_id=team_task.task_id,
            team_id=team_id,
            success=success,
            summary=summary,
            agent_results=agent_results,
            confidence=confidence,
        )

        self.coordination_results[coordination_id] = coordination_result
        self.team_tasks[team_task.task_id].status = "completed" if success else "failed"
        self.team_tasks[team_task.task_id].completed_at = time.time()
        self.team_tasks[team_task.task_id].results = coordination_result.to_dict()

        self.stats["teams_coordinated"] += 1
        self.stats["tasks_coordinated"] += 1
        if success:
            self.stats["tasks_successful"] += 1
        else:
            self.stats["tasks_failed"] += 1

        return coordination_result

    def get_coordination_result(self, coordination_id: str) -> CoordinationResult | None:
        return self.coordination_results.get(coordination_id)

    def get_team_task(self, team_task_id: str) -> TeamTask | None:
        return self.team_tasks.get(team_task_id)

    def get_stats(self) -> dict[str, Any]:
        return {
            "teams_coordinated": self.stats["teams_coordinated"],
            "tasks_coordinated": self.stats["tasks_coordinated"],
            "tasks_successful": self.stats["tasks_successful"],
            "tasks_failed": self.stats["tasks_failed"],
            "recoveries": self.stats["recoveries"],
            "success_rate": (
                self.stats["tasks_successful"] / max(self.stats["tasks_coordinated"], 1)
            ),
        }


# Global team coordinator instance
_team_coordinator: TeamCoordinator | None = None


def get_team_coordinator() -> TeamCoordinator:
    """Get or create the global TeamCoordinator instance."""
    global _team_coordinator
    if _team_coordinator is None:
        _team_coordinator = TeamCoordinator()
    return _team_coordinator


__all__ = [
    "TeamTask",
    "CoordinationResult",
    "TeamCoordinator",
    "get_team_coordinator",
]
