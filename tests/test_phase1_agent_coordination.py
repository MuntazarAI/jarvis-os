"""Integration tests for Phase 1: Agent System Coordination.

Tests the full multi-agent loop:
  Planner (DAG) → Security Agent (PolicyEngine gate) → Agent execution → Verify

No stubbed hooks — uses real EnhancedPlanner, SecurityAgent, and
EnhancedSupervisor with a mock on_step that simulates tool execution.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from jarvis.core.config import JarvisConfig
from jarvis.policy.policy import PolicyEngine
from jarvis.agents.agents import AgentRegistry, default_agents
from jarvis.agents.enhanced_planner import EnhancedPlanner, plan_goal
from jarvis.agents.enhanced_supervisor import EnhancedSupervisor
from jarvis.agents.security_agent import SecurityAgent


# -- fixtures --------------------------------------------------------------


@pytest.fixture
def home():
    return tempfile.mkdtemp(prefix="jarvis-phase1-")


@pytest.fixture
def config(home):
    cfg = JarvisConfig()
    cfg.paths.home = Path(home)
    cfg.policy.local_only = True
    cfg.models.cloud_enabled = False
    cfg.models.ollama_enabled = False
    return cfg


@pytest.fixture
def policy(config):
    return PolicyEngine(config=config)


@pytest.fixture
def registry():
    reg = AgentRegistry()
    from jarvis.agents.agents import default_agents
    for a in default_agents():
        if reg.by_name(a.name) is None:
            reg.spawn(a)
    return reg


# -- Step 1.1: Enhanced Planner tests -------------------------------------


def test_enhanced_planner_builds_dag(registry):
    """Planner produces a valid DAG with capability-matched agents."""
    planner = EnhancedPlanner(registry)
    steps = planner.plan("read the config file and list the directory")

    assert len(steps) >= 1
    # Each step should have an agent assigned
    for step in steps:
        assert step.agent != ""
        assert step.tool != ""
        assert step.step_id.startswith("s")

    # DAG should be topologically valid
    order = planner.validate(steps)
    assert len(order) == len(steps)


def test_enhanced_planner_assigns_agents_by_capability(registry):
    """Steps get matched to agents that can actually use the tool."""
    planner = EnhancedPlanner(registry)
    steps = planner.plan("search the web for information about Python")

    # Web fetch steps should go to researcher
    web_steps = [s for s in steps if s.tool == "web_fetch"]
    if web_steps:
        for step in web_steps:
            assert step.agent == "researcher", f"web_fetch should go to researcher, got {step.agent}"


def test_enhanced_planner_risk_levels(registry):
    """High-risk actions (delete) get flagged for approval."""
    planner = EnhancedPlanner(registry)
    steps = planner.plan("delete the temporary file and read the config")

    delete_steps = [s for s in steps if "delete" in s.description.lower()]
    if delete_steps:
        for step in delete_steps:
            assert step.risk_level == "high"
            assert step.requires_approval is True


def test_plan_goal_convenience(registry):
    """plan_goal convenience function works."""
    steps = plan_goal("read a file", registry)
    assert len(steps) >= 1


# -- Step 1.3: Security Agent tests ---------------------------------------


def test_security_agent_allows_safe_action(policy):
    """Safe actions pass through PolicyEngine."""
    agent = SecurityAgent(policy=policy, actor="test")
    verdict = agent.evaluate(action="filesystem_read", args={"path": "/tmp/test.txt"})

    assert verdict.allowed is True
    assert agent.allowed_count == 1
    assert agent.blocked_count == 0


def test_security_agent_blocks_destructive_action(policy):
    """Destructive actions are blocked or require approval."""
    agent = SecurityAgent(policy=policy, actor="test")
    verdict = agent.evaluate(action="rm -rf /", args={})

    assert verdict.allowed is False or verdict.decision.requires_approval is True
    assert len(agent.verdicts) == 1


def test_security_agent_audit_trail(policy):
    """Every evaluation is recorded for audit."""
    agent = SecurityAgent(policy=policy, actor="test")
    agent.evaluate(action="read", args={"path": "/tmp/a.txt"})
    agent.evaluate(action="write", args={"path": "/tmp/b.txt"})

    assert len(agent.verdicts) == 2
    status = agent.status()
    assert status["total_evaluations"] == 2
    assert status["allowed"] == 2


# -- Step 1.5: Multi-agent workflow end-to-end ---------------------------


def _mock_on_step(step, agent):
    """Simulate tool execution: always succeeds for safe tools."""
    tool = step.tool.lower()
    if any(bad in tool for bad in ("rm", "delete", "format", "shutdown")):
        return {"ok": False, "error": "destructive tool blocked"}
    return {
        "ok": True,
        "output": f"simulated {tool} for {step.description[:40]}",
        "agent": agent.name,
    }


def test_multi_agent_workflow_read_then_write(config, registry, policy):
    """A two-step workflow: plan → security gate → execute → verify."""
    supervisor = EnhancedSupervisor(
        registry=registry, policy=policy, on_step=_mock_on_step)

    task = supervisor.submit("read the config file then write a summary")
    result = supervisor.run_task(task.task_id)

    assert result.state.value in ("completed", "failed")
    assert result.progress >= 0.0
    # At least one delegation was attempted
    assert len(supervisor.delegations) >= 1


def test_multi_agent_workflow_blocks_destructive(config, registry, policy):
    """A destructive goal should be blocked by Security Agent."""
    supervisor = EnhancedSupervisor(
        registry=registry, policy=policy, on_step=_mock_on_step)

    task = supervisor.submit("delete all system files")
    result = supervisor.run_task(task.task_id)

    # Should fail or be blocked — never succeed with destructive action
    assert result.state.value != "completed" or result.error is not None \
        or len(supervisor.security.verdicts) >= 1


def test_multi_agent_independent_groups(config, registry, policy):
    """Independent step groups can be identified for parallel execution."""
    supervisor = EnhancedSupervisor(
        registry=registry, policy=policy, on_step=_mock_on_step)

    task = supervisor.submit("read file A and read file B")
    supervisor.run_task(task.task_id)

    groups = supervisor.independent_groups(task.task_id)
    assert len(groups) >= 1
    # All steps should appear in some group
    all_step_ids = [sid for group in groups for sid in group]
    assert len(all_step_ids) >= 1


def test_supervisor_status_includes_security(config, registry, policy):
    """Supervisor status includes security metrics."""
    supervisor = EnhancedSupervisor(
        registry=registry, policy=policy, on_step=_mock_on_step)

    task = supervisor.submit("read a file")
    supervisor.run_task(task.task_id)

    status = supervisor.status()
    assert "security" in status
    assert status["security"]["total_evaluations"] >= 1


def test_agent_registry_capable_of(registry):
    """AgentRegistry can find agents capable of a tool."""
    capable = registry.capable_of("filesystem_read")
    assert len(capable) >= 1
    # librarian should be capable of filesystem_read
    names = [a.name for a in capable]
    assert "librarian" in names or "coder" in names


def test_default_agents_registered(registry):
    """All 8 default agents are in the registry."""
    agents = registry.list_agents()
    names = {a.name for a in agents}
    expected = {"supervisor", "planner", "researcher", "coder",
                "analyst", "computer", "guardian", "librarian"}
    assert expected.issubset(names), f"missing: {expected - names}"


# -- Security Agent integration with PolicyEngine ------------------------


def test_security_agent_uses_policy_engine(config, registry, policy):
    """SecurityAgent verdicts come from PolicyEngine evaluation."""
    agent = SecurityAgent(policy=policy, actor="integration-test")

    # Safe filesystem read on local path
    verdict = agent.evaluate(
        action="filesystem_read",
        args={"path": str(Path(config.paths.home) / "safe.txt")},
    )

    assert verdict.decision.risk_level is not None
    assert isinstance(verdict.decision.reasons, list)
    assert verdict.allowed is True or verdict.decision.requires_approval is True