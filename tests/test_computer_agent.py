"""Computer Agent 2.0 tests. Input is mocked; screenshot/clipboard run live."""

import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.computer.agent import ComputerAgent, UIAction  # noqa: E402
from jarvis.computer.computer import ComputerController, computer_tools  # noqa: E402
from jarvis.core.config import JarvisConfig  # noqa: E402
from jarvis.policy.policy import PolicyEngine  # noqa: E402
from jarvis.tools.tools import default_registry  # noqa: E402


def _agent(tmp, granted=("desktop.screenshot", "desktop.windows",
                         "clipboard.read", "clipboard.write")):
    policy = PolicyEngine(JarvisConfig())
    for perm in granted:
        policy.grant("computer", perm)
    registry = default_registry()
    for tool in computer_tools():
        registry.register(tool)
    return (ComputerAgent(ComputerController(), policy, registry,
                          shot_dir=str(tmp)), policy)


def test_approved_write_verifies_and_undoes(tmp_path):
    agent, policy = _agent(tmp_path)
    first = agent.act("computer", UIAction(
        tool="clipboard_write", args={"text": "undo-me-123"},
        verify={"kind": "clipboard_equals", "text": "undo-me-123"}))
    assert "needs approval" in first.error
    token = first.error.split("token ")[1].strip(")")
    assert policy.approve(token)
    done = agent.act("computer", UIAction(
        tool="clipboard_write", args={"text": "undo-me-123"},
        verify={"kind": "clipboard_equals", "text": "undo-me-123"}),
        approval=token)
    assert done.ok and done.reversible and done.attempts == 1
    assert done.before_shot and done.after_shot
    assert agent.undo_last()["ok"]
    assert not agent.undo_last()["ok"]


def test_blocked_input_and_failed_verification(tmp_path):
    agent, _ = _agent(tmp_path)
    blocked = agent.act("computer", UIAction(tool="mouse_click", args={}))
    assert not blocked.ok and "blocked" in blocked.error
    bad = agent.act("computer", UIAction(
        tool="clipboard_read", args={},
        verify={"kind": "clipboard_equals", "text": "definitely-not-this"}))
    assert not bad.ok


def test_run_goal_stops_on_failure(tmp_path):
    agent, policy = _agent(tmp_path)
    goal = agent.run_goal("computer", [
        UIAction(tool="clipboard_read", args={}),
        UIAction(tool="nonexistent-tool", args={})])
    assert not goal["ok"] and len(goal["steps"]) == 2
    assert goal["steps"][0]["ok"]


def test_action_serialization():
    action = UIAction(tool="mouse_click", args={"button": "left"})
    assert action.to_dict()["tool"] == "mouse_click"
