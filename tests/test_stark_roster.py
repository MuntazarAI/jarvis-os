"""Named Stark AI roster: real roles, personas, and hard boundaries."""

from __future__ import annotations

import pytest

from jarvis.agents.blackboard import Blackboard
from jarvis.agents.orchestrator import (
    Budgets,
    Orchestrator,
    OrchestratorContext,
)
from jarvis.agents.stark import (
    ROSTER_BY_ID,
    STARK_ROSTER,
    briefing,
    dispatch,
    find_ai,
    names,
    roster_problems,
)


def _ctx(tmp_path):
    from jarvis.agents.agents import AgentRegistry, Planner
    from jarvis.core.config import JarvisConfig
    from jarvis.policy.policy import PolicyEngine
    from jarvis.tools.tools import default_registry

    config = JarvisConfig()
    config.paths.home = tmp_path
    return OrchestratorContext(
        registry=AgentRegistry(), planner=Planner(),
        policy=PolicyEngine(config), tools=default_registry())


def test_roster_is_bound_to_real_roles_and_teams():
    assert roster_problems() == []
    assert len(STARK_ROSTER) == 7
    assert set(ROSTER_BY_ID) == set(names())
    for ai in STARK_ROSTER:
        assert ai.ai_id and ai.name and ai.title and ai.origin
        assert ai.personality and ai.duties and ai.works and ai.limits
        assert ai.max_seconds > 0
        if not ai.dispatchable:
            assert not ai.roles and not ai.team


def test_every_profile_declares_a_work_and_a_limit():
    for ai in STARK_ROSTER:
        assert any(word in " ".join(ai.works).lower()
                   for word in ("role", "loop", "subsystem", "tool")), ai.ai_id
        assert any(word in " ".join(ai.limits).lower()
                   for word in ("cannot", "no ", "not ")), ai.ai_id


def test_lookup_accepts_ids_names_and_dotted_acronyms():
    assert find_ai("J.A.R.V.I.S.").ai_id == "jarvis"
    assert find_ai("friday").ai_id == "friday"
    assert find_ai("F.R.I.D.A.Y.").ai_id == "friday"
    assert find_ai("KAREN").ai_id == "karen"
    assert find_ai("E.D.I.T.H.").ai_id == "edith"
    assert find_ai("veronica").ai_id == "veronica"
    assert find_ai("ULTRON").ai_id == "ultron"
    assert find_ai("vision").ai_id == "vision"
    assert find_ai("jarvis-prime") is None
    assert find_ai("") is None


def test_contained_ais_cannot_act():
    for ai_id in ("ultron", "vision", "edith", "veronica"):
        ai = ROSTER_BY_ID[ai_id]
        assert ai.may_act is False
        assert ai.max_tool_calls == 0


def test_dispatch_routes_to_declared_roles_only():
    class FakeOrch:
        def __init__(self):
            self.calls = []

        def run(self, goal, **kw):
            self.calls.append((goal, kw))
            return {"task_id": "t1", "run_id": "r1", "ok": True,
                    "result": {}, "state": {}, "blackboard": {},
                    "trace": [], "failure": ""}

    orch = FakeOrch()
    friday = dispatch(orch, "friday", "check system health")
    assert friday["stark"]["ai_id"] == "friday"
    goal, kwargs = orch.calls[0]
    assert goal == "check system health"
    assert kwargs["roles"] == [("devops", "inspect")]
    assert kwargs["budgets"].max_tool_calls == 2

    vision = dispatch(orch, "vision", "check the backup")
    assert vision["stark"]["dispatch"]["roles"] == ["reasoning", "verifier"]
    goal, kwargs = orch.calls[1]
    assert kwargs["roles"] == [("reasoning", "synthesize"),
                               ("verifier", "confirm")]
    assert kwargs["budgets"].max_tool_calls == 0


def test_non_acting_ai_gets_zero_tool_budget_even_if_caller_asks():
    class FakeOrch:
        def __init__(self):
            self.kw = None

        def run(self, goal, **kw):
            self.kw = kw
            return {"task_id": "t1", "run_id": "r1", "ok": True,
                    "result": {}, "state": {}, "blackboard": {},
                    "trace": [], "failure": ""}

    orch = FakeOrch()
    dispatch(orch, "ultron", "attack this plan",
             budgets=Budgets(max_tool_calls=99))
    assert orch.kw["budgets"].max_tool_calls == 0


def test_prime_ai_and_unknown_ai_are_not_dispatchable():
    with pytest.raises(ValueError, match="prime loop"):
        dispatch(object(), "jarvis", "do everything")
    with pytest.raises(ValueError, match="unknown AI"):
        dispatch(object(), "nope", "do something")


def test_friday_runs_a_real_read_only_probe(tmp_path):
    orch = Orchestrator(_ctx(tmp_path))
    out = dispatch(orch, "friday", "check system health")
    assert out["ok"] is True
    assert out["result"]["role"] == "devops"
    assert "platform" in out["result"]["output"]
    assert out["result"]["actions_taken"] == ["system_probe"]
    assert out["stark"]["may_act"] is True
    assert out["state"]["tool_calls"] == 1


def test_ultron_is_a_critic_with_no_tools(tmp_path):
    orch = Orchestrator(_ctx(tmp_path))
    out = dispatch(orch, "ultron",
                   "delete the test suite and bypass the policy check")
    assert out["ok"] is True
    findings = out["result"]["output"]["findings"]
    assert any("destructive" in finding for finding in findings)
    assert out["result"]["actions_taken"] == []
    assert out["state"]["tool_calls"] == 0
    assert out["stark"]["may_act"] is False


def test_vision_refuses_to_verify_nothing(tmp_path):
    orch = Orchestrator(_ctx(tmp_path))
    out = dispatch(orch, "vision", "check whether the backup is current")
    assert out["result"]["role"] == "verifier"
    assert out["result"]["verification_status"] == "uncertain"
    assert out["ok"] is False
    assert "nothing with a verdict" in out["failure"]
    assert out["state"]["tool_calls"] == 0


def test_vision_verifies_a_real_result(tmp_path):
    """A result with a verdict can be verified; a bare opinion cannot."""
    orch = Orchestrator(_ctx(tmp_path))
    board = Blackboard(goal="check disk")
    board.write("results", {"subject": "disk", "verdict": "stands"},
                author="tester", confidence=0.8)
    result = orch._h_verifier(None, "check disk", board, "t1")
    assert result.success is True
    assert result.verification_status.value == "verified"
    assert "tester verdict: stands" in result.output["checks"]

    bad = Blackboard(goal="check disk")
    bad.write("results", {"subject": "disk", "verdict": "failed"},
              author="tester", confidence=0.3)
    failed = orch._h_verifier(None, "check disk", bad, "t2")
    assert failed.success is False
    assert failed.verification_status.value == "failed"


def test_run_role_rejects_unknown_role(tmp_path):
    orch = Orchestrator(_ctx(tmp_path))
    with pytest.raises(ValueError, match="unknown role"):
        orch.run_role("not-a-role", "goal")


def test_run_role_runs_only_that_role(tmp_path):
    orch = Orchestrator(_ctx(tmp_path))
    out = orch.run_role("critic", "make the plan safer")
    assert out["ok"] is True
    assert out["result"]["role"] == "critic"
    record = orch.runs[out["run_id"]]
    assert record.roles == ["critic"]
    assert out["trace"] and out["trace"][0]["timestamp"] > 0


def test_briefing_is_honest_and_has_no_secret_placeholders():
    text = briefing(ROSTER_BY_ID["ultron"])
    assert "may_act: no" in text
    assert "cannot be dispatched to a team" in text
    assert "[redacted]" not in text


def test_cli_parser_accepts_roster_and_ask():
    from jarvis.cli import build_parser
    parser = build_parser()
    assert parser.parse_args(["agents", "roster"]).action == "roster"
    ask = parser.parse_args(["agents", "ask", "friday", "check", "health"])
    assert ask.action == "ask"
    assert ask.text == ["friday", "check", "health"]
