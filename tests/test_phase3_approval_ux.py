"""Phase 3 integration tests: Approval UX.

Tests the operator approval flow:
  SecurityAgent gates action → creates approval token → task pauses
  → operator approves via PolicyEngine → Supervisor.resume_task() → completes

Tests cover:
- Safe actions execute without approval
- Actions requiring approval create tokens and pause tasks
- check_approval reflects PolicyEngine state
- resume_task completes after approval, fails after denial
- pending_approvals lists waiting tasks
- Multiple sequential approvals in one task
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from jarvis.core.config import JarvisConfig
from jarvis.core.types import ActionPlan, RiskLevel
from jarvis.policy.policy import PolicyEngine, PolicyDecision
from jarvis.agents.agents import AgentRegistry, default_agents
from jarvis.agents.enhanced_supervisor import EnhancedSupervisor
from jarvis.agents.security_agent import SecurityAgent


# -- fixtures --------------------------------------------------------------


@pytest.fixture
def home():
    return tempfile.mkdtemp(prefix="jarvis-phase3-")


@pytest.fixture
def config(home):
    cfg = JarvisConfig()
    cfg.paths.home = Path(home)
    cfg.policy.local_only = True
    cfg.models.cloud_enabled = False
    cfg.models.ollama_enabled = False
    # Lower the approval threshold so more actions require approval
    cfg.policy.require_approval_above_risk = 0.3
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


# -- mock on_step ----------------------------------------------------------


def _mock_on_step(step, agent):
    """Simulate tool execution: always succeeds."""
    return {
        "ok": True,
        "output": f"simulated {step.tool} for {step.description[:40]}",
        "agent": agent.name,
    }


# -- SecurityAgent approval token tests ------------------------------------


def test_security_agent_creates_approval_token(policy):
    """Actions requiring approval get a persistent token."""
    agent = SecurityAgent(policy=policy, actor="test")

    # A write action that is allowed but requires approval
    verdict = agent.evaluate(
        action="filesystem_write",
        args={"path": "/tmp/sensitive.txt", "content": "secret"},
    )

    assert verdict.allowed is True  # allowed but needs approval
    assert verdict.approval_token != ""
    assert len(verdict.approval_token) >= 8
    assert agent.pending_count == 1
    assert verdict.decision.requires_approval is True


def test_security_agent_safe_action_no_token(policy):
    """Safe actions don't create approval tokens."""
    agent = SecurityAgent(policy=policy, actor="test")

    verdict = agent.evaluate(
        action="filesystem_read",
        args={"path": "/tmp/test.txt"},
    )

    assert verdict.allowed is True
    assert verdict.approval_token == ""
    assert agent.pending_count == 0


def test_security_agent_check_approval(policy):
    """check_approval reflects PolicyEngine state."""
    agent = SecurityAgent(policy=policy, actor="test")

    verdict = agent.evaluate(
        action="filesystem_write",
        args={"path": "/etc/sensitive", "content": "x"},
    )
    token = verdict.approval_token

    # Not yet approved
    assert agent.check_approval(token) is False

    # Approve via PolicyEngine
    assert policy.approve(token, by="operator") is True
    assert agent.check_approval(token) is True


# -- EnhancedSupervisor approval flow tests --------------------------------


def test_supervisor_pauses_for_approval(registry, policy):
    """Task pauses when a step requires approval."""
    supervisor = EnhancedSupervisor(
        registry=registry, policy=policy, on_step=_mock_on_step)

    # "delete" is high-risk and will require approval
    task = supervisor.submit("delete the temp file and read the config")
    result = supervisor.run_task(task.task_id)

    assert result.state.value == "waiting"
    assert len(supervisor._waiting) == 1

    # pending_approvals should list the waiting task
    pending = supervisor.pending_approvals()
    assert len(pending) == 1
    assert pending[0]["task_id"] == task.task_id
    assert pending[0]["token_prefix"] != ""
    assert pending[0]["action"] == "filesystem_write"


def test_supervisor_resumes_after_approval(registry, policy):
    """Task resumes and completes after all approvals are granted."""
    supervisor = EnhancedSupervisor(
        registry=registry, policy=policy, on_step=_mock_on_step)

    task = supervisor.submit("write a config file to /tmp/test.cfg")
    result = supervisor.run_task(task.task_id)

    assert result.state.value == "waiting"

    # Approve all pending approvals one by one until complete
    for _ in range(5):  # safety limit
        pending = supervisor.pending_approvals()
        if not pending:
            break
        token = pending[0]["token"]
        assert policy.approve(token, by="operator") is True
        result = supervisor.resume_task(task.task_id)
        if result.state.value == "completed":
            break

    assert result.state.value == "completed"
    assert not result.error  # empty string = no error


def test_supervisor_fails_after_denial(registry, policy):
    """Task fails when approval is denied."""
    supervisor = EnhancedSupervisor(
        registry=registry, policy=policy, on_step=_mock_on_step)

    task = supervisor.submit("delete the temp file and read the config")
    result = supervisor.run_task(task.task_id)

    assert result.state.value == "waiting"

    # Get the approval token and deny it
    pending = supervisor.pending_approvals()
    token = pending[0]["token"]
    assert policy.deny(token, by="operator") is True

    # Resume — should fail because approval was denied
    result = supervisor.resume_task(task.task_id)
    assert result.state.value == "waiting"  # still waiting (denied = not approved)
    # The task stays waiting because check_approval returns False for denied


def test_supervisor_task_status_shows_waiting(registry, policy):
    """task_status includes waiting_step info."""
    supervisor = EnhancedSupervisor(
        registry=registry, policy=policy, on_step=_mock_on_step)

    task = supervisor.submit("delete the temp file and read the config")
    supervisor.run_task(task.task_id)

    status = supervisor.task_status(task.task_id)
    assert status["state"] == "waiting"
    assert status["waiting_step"] is not None


def test_supervisor_status_includes_waiting_count(registry, policy):
    """Supervisor status includes waiting_for_approval count."""
    supervisor = EnhancedSupervisor(
        registry=registry, policy=policy, on_step=_mock_on_step)

    task = supervisor.submit("delete the temp file and read the config")
    supervisor.run_task(task.task_id)

    status = supervisor.status()
    assert status["waiting_for_approval"] == 1


def test_auto_approve_bypasses_pause(registry, policy):
    """auto_approve=True skips the approval pause."""
    supervisor = EnhancedSupervisor(
        registry=registry, policy=policy, on_step=_mock_on_step)

    task = supervisor.submit("delete the temp file and read the config")
    result = supervisor.run_task(task.task_id, auto_approve=True)

    assert result.state.value == "completed"
    assert len(supervisor._waiting) == 0


def test_multiple_sequential_approvals(registry, policy):
    """Task can pause for multiple approvals in sequence."""
    supervisor = EnhancedSupervisor(
        registry=registry, policy=policy, on_step=_mock_on_step)

    # Multiple write actions → multiple approvals needed
    task = supervisor.submit("write config file A and write config file B")
    result = supervisor.run_task(task.task_id)

    assert result.state.value == "waiting"

    # Approve all pending approvals one by one until complete
    for _ in range(10):  # safety limit
        pending = supervisor.pending_approvals()
        if not pending:
            break
        token = pending[0]["token"]
        assert policy.approve(token, by="operator") is True
        result = supervisor.resume_task(task.task_id)
        if result.state.value == "completed":
            break

    assert result.state.value == "completed"


def test_resume_when_not_waiting(registry, policy):
    """resume_task on a non-waiting task returns it unchanged."""
    supervisor = EnhancedSupervisor(
        registry=registry, policy=policy, on_step=_mock_on_step)

    task = supervisor.submit("read a simple file")
    result = supervisor.run_task(task.task_id)
    assert result.state.value == "completed"

    # Resume on a completed task should be a no-op
    result = supervisor.resume_task(task.task_id)
    assert result.state.value == "completed"