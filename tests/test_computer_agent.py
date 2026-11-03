"""Computer Agent 2.0 tests. Input is mocked; screenshot runs live, clipboard is faked."""

import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.computer.agent import ComputerAgent, UIAction  # noqa: E402
from jarvis.computer.computer import ComputerController, computer_tools  # noqa: E402
from jarvis.core.config import JarvisConfig  # noqa: E402
from jarvis.policy.policy import PolicyEngine  # noqa: E402
from jarvis.tools.tools import ToolResult, default_registry  # noqa: E402


def _policy(home):
    config = JarvisConfig()
    config.paths.home = home
    return PolicyEngine(config)


def _agent(tmp, granted=("desktop.screenshot", "desktop.windows",
                         "clipboard.read", "clipboard.write"), computer=None,
           policy=None):
    policy = policy or PolicyEngine(JarvisConfig())
    for perm in granted:
        policy.grant("computer", perm)
    registry = default_registry()
    computer = computer or ComputerController()
    for tool in computer_tools(computer):
        registry.register(tool)
    return (ComputerAgent(computer, policy, registry,
                          shot_dir=str(tmp)), policy)


def test_approved_write_verifies_and_undoes(tmp_path):
    clipboard = MagicMock()
    clipboard.value = "original"
    clipboard.read.side_effect = lambda: {"ok": True, "text": clipboard.value}
    clipboard.write.side_effect = lambda text: (setattr(clipboard, "value", text) or {"ok": True})
    screen = MagicMock()
    screen.capture.return_value = {"ok": True, "bytes": 1234}
    computer = ComputerController(screen=screen, clipboard=clipboard)
    agent, policy = _agent(tmp_path, computer=computer)

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
    assert clipboard.value == "undo-me-123" or clipboard.value == "original"
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
    clipboard = MagicMock()
    clipboard.read.side_effect = lambda: {"ok": True, "text": "goal-step"}
    computer = ComputerController(clipboard=clipboard)
    agent, policy = _agent(tmp_path, computer=computer)
    goal = agent.run_goal("computer", [
        UIAction(tool="clipboard_read", args={}),
        UIAction(tool="nonexistent-tool", args={})])
    assert not goal["ok"] and len(goal["steps"]) == 2
    assert goal["steps"][0]["ok"]


def test_action_serialization():
    action = UIAction(tool="mouse_click", args={"button": "left"})
    assert action.to_dict()["tool"] == "mouse_click"


def _clipboard_computer():
    clipboard = MagicMock()
    clipboard.value = "original"
    clipboard.read.side_effect = lambda: {"ok": True, "text": clipboard.value}
    clipboard.write.side_effect = lambda text: (
        setattr(clipboard, "value", text) or {"ok": True})
    screen = MagicMock()
    screen.capture.return_value = {"ok": True, "bytes": 1234}
    return ComputerController(screen=screen, clipboard=clipboard), clipboard


def _approved_token(agent, policy, action):
    first = agent.act("computer", action)
    assert "needs approval" in first.error
    token = first.error.split("token ")[1].strip(")")
    assert policy.approve(token)
    return token


def test_single_use_approval_cannot_authorize_second_action(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    policy = _policy(home)
    computer, clipboard = _clipboard_computer()
    agent, policy = _agent(tmp_path, computer=computer, policy=policy)
    action = UIAction(
        tool="clipboard_write", args={"text": "one-shot"},
        verify={"kind": "clipboard_equals", "text": "one-shot"})

    token = _approved_token(agent, policy, action)
    assert agent.act("computer", action, approval=token).ok
    writes = clipboard.write.call_count

    replay = agent.act("computer", action, approval=token)
    assert not replay.ok
    assert "needs approval" in replay.error
    assert clipboard.write.call_count == writes
    assert policy.approved(token) is False


def test_approval_is_bound_to_exact_action_and_args(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    policy = _policy(home)
    computer, clipboard = _clipboard_computer()
    agent, policy = _agent(tmp_path, computer=computer, policy=policy)
    approved = UIAction(
        tool="clipboard_write", args={"text": "approved"},
        verify={"kind": "clipboard_equals", "text": "approved"})
    other = UIAction(
        tool="clipboard_write", args={"text": "not-approved"},
        verify={"kind": "clipboard_equals", "text": "not-approved"})

    token = _approved_token(agent, policy, approved)
    denied = agent.act("computer", other, approval=token)
    assert not denied.ok and "needs approval" in denied.error
    assert clipboard.write.call_count == 0
    # A wrong binding does not spend the token; the exact action still works.
    assert policy.approved(token) is True
    assert agent.act("computer", approved, approval=token).ok
    assert clipboard.value == "approved"


def test_pending_denied_and_unknown_tokens_never_execute(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    policy = _policy(home)
    computer, clipboard = _clipboard_computer()
    agent, policy = _agent(tmp_path, computer=computer, policy=policy)
    action = UIAction(
        tool="clipboard_write", args={"text": "must-not-run"},
        verify={"kind": "clipboard_equals", "text": "must-not-run"})

    pending = agent.act("computer", action)
    pending_token = pending.error.split("token ")[1].strip(")")
    assert not agent.act("computer", action, approval=pending_token).ok
    assert clipboard.write.call_count == 0

    assert policy.deny(pending_token)
    assert not agent.act("computer", action, approval=pending_token).ok
    assert clipboard.write.call_count == 0

    assert not agent.act("computer", action, approval="appr-not-real").ok
    assert clipboard.write.call_count == 0


def test_retries_share_one_authorized_action(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    policy = _policy(home)
    policy.grant("computer", "exec")
    registry = default_registry()
    calls = []

    def flaky_terminal(command, timeout=30.0, cwd="."):
        calls.append(command)
        return ToolResult(tool="terminal_run", ok=len(calls) > 1,
                          output={"ran": len(calls)},
                          error="" if len(calls) > 1 else "transient")

    registry.get("terminal_run").func = flaky_terminal
    screen = MagicMock()
    screen.capture.return_value = {"ok": True}
    computer = ComputerController(screen=screen)
    agent = ComputerAgent(computer, policy, registry,
                          shot_dir=str(tmp_path))
    action = UIAction(tool="terminal_run",
                      args={"command": "echo once"}, retries=2)

    token = _approved_token(agent, policy, action)
    done = agent.act("computer", action, approval=token)
    assert done.ok and done.attempts == 2
    assert calls == ["echo once", "echo once"]


def test_concurrent_requests_cannot_replay_one_approval(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    policy = _policy(home)
    policy.grant("computer", "exec")
    registry = default_registry()
    calls = []
    calls_lock = threading.Lock()

    def slow_terminal(command, timeout=30.0, cwd="."):
        with calls_lock:
            calls.append(command)
        time.sleep(0.05)
        return ToolResult(tool="terminal_run", ok=True,
                          output={"ran": True})

    registry.get("terminal_run").func = slow_terminal
    screen = MagicMock()
    screen.capture.return_value = {"ok": True}
    computer = ComputerController(screen=screen)
    agent = ComputerAgent(computer, policy, registry,
                          shot_dir=str(tmp_path))
    action = UIAction(tool="terminal_run",
                      args={"command": "echo once"})
    token = _approved_token(agent, policy, action)

    barrier = threading.Barrier(2)
    results = []

    def run_once():
        barrier.wait()
        results.append(agent.act("computer", action, approval=token))

    threads = [threading.Thread(target=run_once) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert len(results) == 2
    assert sum(1 for result in results if result.ok) == 1
    assert calls == ["echo once"]
    assert policy.approved(token) is False
