"""
Testing framework — JARVIS-OS testing and simulation subsystem.

Provides agent simulation, load testing, fault injection, regression
testing, and red team exercises for testing JARVIS-OS resilience and
correctness.
"""

from .agent_simulation import (
    AgentSimulation,
    SimulatedAgent,
    SimulationScenario,
    SimulationResult,
    get_agent_simulation,
)
from .load_tester import (
    LoadTester,
    LoadTestConfig,
    LoadTestResult,
    get_load_tester,
)
from .fault_injector import (
    FaultInjector,
    FaultInjection,
    FaultResult,
    get_fault_injector,
)
from .regression_tester import (
    RegressionTester,
    RegressionTest,
    RegressionResult,
    get_regression_tester,
)
from .red_team_exerciser import (
    RedTeamExerciser,
    RedTeamExercise,
    RedTeamResult,
    get_red_team_exerciser,
)

__all__ = [
    # Agent Simulation
    "AgentSimulation",
    "SimulatedAgent",
    "SimulationScenario",
    "SimulationResult",
    "get_agent_simulation",
    # Load Testing
    "LoadTester",
    "LoadTestConfig",
    "LoadTestResult",
    "get_load_tester",
    # Fault Injection
    "FaultInjector",
    "FaultInjection",
    "FaultResult",
    "get_fault_injector",
    # Regression Testing
    "RegressionTester",
    "RegressionTest",
    "RegressionResult",
    "get_regression_tester",
    # Red Team Exercises
    "RedTeamExerciser",
    "RedTeamExercise",
    "RedTeamResult",
    "get_red_team_exerciser",
]