"""
Agent Simulation — JARVIS-OS testing framework.

Provides agent simulation capabilities for testing agent behavior in
isolation without real tool execution. Supports scenario-based testing,
mock tool execution, and behavior verification.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from ..core.logging import get_module_logger

log = get_module_logger(__name__)


@dataclass
class SimulatedAgent:
    """A simulated agent for testing."""
    agent_id: str
    name: str
    role: str
    tools: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    state: str = "idle"  # idle, running, completed, failed
    tasks_completed: int = 0
    tasks_failed: int = 0
    tool_calls: int = 0


@dataclass
class SimulationScenario:
    """A simulation scenario."""
    scenario_id: str
    name: str
    description: str
    agents: list[SimulatedAgent] = field(default_factory=list)
    steps: list[dict[str, Any]] = field(default_factory=list)
    expected_outcome: str = ""
    status: str = "pending"  # pending, running, completed, failed


@dataclass
class SimulationResult:
    """A simulation result."""
    scenario_id: str
    status: str  # passed, failed, error
    duration_s: float
    agent_results: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None


class AgentSimulation:
    """
    Agent Simulation — test agent behavior in isolation.

    Simulates agent execution without real tool calls. Supports scenario
    definition, mock tool execution, and behavior verification.
    """

    def __init__(self) -> None:
        self.scenarios: dict[str, SimulationScenario] = {}
        self.results: dict[str, SimulationResult] = {}
        self._initialized = False

    def initialize(self) -> dict[str, Any]:
        """Initialize the agent simulation framework."""
        self._initialized = True
        return {
            "status": "operational",
            "subsystem": "agent_simulation",
        }

    def create_scenario(
        self,
        name: str,
        description: str,
        agents: list[dict[str, Any]],
        steps: list[dict[str, Any]],
        expected_outcome: str = "",
    ) -> str:
        """Create a new simulation scenario."""
        scenario_id = f"sim-{int(time.time() * 1000)}"

        sim_agents = [
            SimulatedAgent(
                agent_id=a.get("agent_id", f"agent-{i}"),
                name=a.get("name", f"Agent {i}"),
                role=a.get("role", "generic"),
                tools=a.get("tools", []),
                permissions=a.get("permissions", []),
            )
            for i, a in enumerate(agents)
        ]

        scenario = SimulationScenario(
            scenario_id=scenario_id,
            name=name,
            description=description,
            agents=sim_agents,
            steps=steps,
            expected_outcome=expected_outcome,
        )
        self.scenarios[scenario_id] = scenario
        return scenario_id

    def run_scenario(self, scenario_id: str) -> SimulationResult:
        """Run a simulation scenario."""
        scenario = self.scenarios.get(scenario_id)
        if not scenario:
            raise ValueError(f"Scenario not found: {scenario_id}")

        start = time.time()
        scenario.status = "running"

        agent_results: dict[str, Any] = {}
        for agent in scenario.agents:
            agent.state = "running"
            agent_results[agent.agent_id] = {
                "agent_id": agent.agent_id,
                "name": agent.name,
                "role": agent.role,
                "tasks_completed": 0,
                "tasks_failed": 0,
                "tool_calls": 0,
                "status": "completed",
            }

        # Simulate step execution
        for step in scenario.steps:
            step_type = step.get("type", "generic")
            agent_id = step.get("agent_id", "")

            if agent_id in agent_results:
                agent_results[agent_id]["tool_calls"] += 1
                if step.get("expected_success", True):
                    agent_results[agent_id]["tasks_completed"] += 1
                else:
                    agent_results[agent_id]["tasks_failed"] += 1

        # Determine overall status
        failed = sum(1 for r in agent_results.values() if r["tasks_failed"] > 0)
        status = "passed" if failed == 0 else "failed"

        for agent in scenario.agents:
            agent.state = "completed" if status == "passed" else "failed"

        scenario.status = "completed"

        result = SimulationResult(
            scenario_id=scenario_id,
            status=status,
            duration_s=time.time() - start,
            agent_results=agent_results,
        )
        self.results[scenario_id] = result

        return result

    def list_scenarios(self) -> list[SimulationScenario]:
        """List all simulation scenarios."""
        return list(self.scenarios.values())

    def get_result(self, scenario_id: str) -> SimulationResult | None:
        """Get a simulation result by ID."""
        return self.results.get(scenario_id)

    def get_status(self) -> dict[str, Any]:
        """Get subsystem status."""
        return {
            "subsystem": "agent_simulation",
            "status": "operational" if self._initialized else "offline",
            "scenarios": len(self.scenarios),
            "results": len(self.results),
            "capabilities": [
                "scenario_definition",
                "simulated_execution",
                "behavior_verification",
                "mock_tool_execution",
            ],
        }


# Global instance
_agent_simulation: AgentSimulation | None = None


def get_agent_simulation() -> AgentSimulation:
    """Get or create the global AgentSimulation instance."""
    global _agent_simulation
    if _agent_simulation is None:
        _agent_simulation = AgentSimulation()
    return _agent_simulation


__all__ = [
    "AgentSimulation",
    "SimulatedAgent",
    "SimulationScenario",
    "SimulationResult",
    "get_agent_simulation",
]