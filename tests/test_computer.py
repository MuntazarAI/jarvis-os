"""Computer control + policy gate tests. Input paths are mocked (never touch desktop)."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.agents.agents import PlanStep  # noqa: E402
from jarvis.computer.computer import ComputerController, computer_tools  # noqa: E402
from jarvis.core.loop import Jarvis  # noqa: E402
from jarvis.core.types import ActionPlan, RiskLevel  # noqa: E402
from jarvis.policy.policy import PolicyEngine, RiskEngine  # noqa: E402


@pytest.fixture()
def jarvis(tmp_path):
    j = Jarvis(home=str(tmp_path))
    yield j
    j.close()


def test_risk_word_boundaries():
    rk = RiskEngine()
    assert rk.assess("screen_capture capture screen").risk < 0.3
    assert rk.assess("run the adaptation layer").risk < 0.3
    assert rk.assess("apt install foo").risk >= 0.5
    assert rk.assess("pip install bar").risk >= 0.5
    assert RiskLevel.from_score(0.05) == RiskLevel.SAFE
    assert RiskLevel.from_score(0.9) == RiskLevel.DESTRUCTIVE


def test_declared_risk_floors_assessment():
    pe = PolicyEngine()
    pe.grant("computer", "desktop.input")
    plan = ActionPlan(action="mouse_click click mouse", args={},
                      required_permissions=["desktop.input"], risk=RiskLevel.HIGH)
    decision = pe.evaluate("computer", plan)
    assert decision.risk >= 0.75 and decision.requires_approval


def test_gated_screenshot_runs_input_blocked(jarvis, tmp_path):
    computer = jarvis.supervisor.registry.by_name("computer")
    dest = str(tmp_path / "gated.png")
    with patch.object(jarvis.computer.screen, "capture",
                      return_value={"ok": True, "path": dest, "bytes": 1234}):
        out = jarvis._execute_step(PlanStep(step_id="s1", description="capture screen",
                                            agent="computer", tool="screen_capture",
                                            args={"dest": dest}), computer)
    assert out["ok"], out
    out2 = jarvis._execute_step(PlanStep(step_id="s2", description="click",
                                         agent="computer", tool="mouse_click",
                                         args={}), computer)
    assert not out2["ok"] and "desktop.input" in out2["error"]


def test_granted_input_still_needs_approval(jarvis):
    computer = jarvis.supervisor.registry.by_name("computer")
    jarvis.policy.grant("computer", "desktop.input")
    out = jarvis._execute_step(PlanStep(step_id="s3", description="click",
                                        agent="computer", tool="mouse_click",
                                        args={}), computer)
    assert not out["ok"] and "needs approval" in out["error"]
    token = out["error"].split("token ")[1].strip(")")
    assert jarvis.policy.approve(token)


def test_computer_tool_registry():
    tools = {t.spec.name: t for t in computer_tools()}
    assert tools["screen_capture"].spec.risk == RiskLevel.SAFE
    assert tools["mouse_click"].spec.risk == RiskLevel.HIGH
    assert tools["clipboard_read"].spec.risk == RiskLevel.LOW
    assert "desktop.input" in tools["type_text"].spec.required_permissions


def test_input_argv_mocked():
    c = ComputerController()
    calls = []

    def fake(cmd, **kw):
        calls.append(cmd)
        m = MagicMock()
        m.returncode = 0
        m.stderr = ""
        m.stdout = ""
        return m

    with patch("jarvis.computer.computer._run", side_effect=fake):
        assert c.input.move(100, 200)["ok"]
        assert calls[-1] == ["ydotool", "mousemove", "-x", "100", "-y", "200"]
        assert c.input.click()["ok"] and calls[-1][-1] == "0xC0"
        assert not c.input.click("sideways")["ok"]
        assert c.input.type_text("hi")["ok"]
        assert not c.input.type_text("x" * 2001)["ok"]
        assert c.input.key("ctrl", "c")["ok"]
        assert not c.input.key()["ok"]
        assert not c.input.scroll("sideways")["ok"]
