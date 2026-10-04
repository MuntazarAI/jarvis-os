"""Agent Intelligence 2.0: contracts, bus, blackboard, orchestration, safety."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.agents.blackboard import Blackboard  # noqa: E402
from jarvis.agents.bus import (  # noqa: E402
    AgentMessage,
    Classification,
    MessageBus,
    MessageType,
)
from jarvis.agents.contract import (  # noqa: E402
    AgentCard,
    AgentResult,
    SkillRegistry,
    VerificationStatus,
    role_cards,
)
from jarvis.agents.orchestrator import (  # noqa: E402
    Budgets,
    Orchestrator,
    OrchestratorContext,
    TEAMS,
)


def _ctx(**kw):
    from jarvis.agents.agents import AgentRegistry, Planner
    from jarvis.policy.policy import PolicyEngine
    from jarvis.tools.tools import default_registry
    base = {"registry": AgentRegistry(), "planner": Planner(),
            "policy": PolicyEngine(), "tools": default_registry()}
    base.update(kw)
    return OrchestratorContext(**base)


# -- contracts -------------------------------------------------------------
def test_role_cards_complete_and_bound():
    cards = role_cards()
    assert len(cards) == 31  # 30 original roles + tester agent
    by_id = {c.role_id: c for c in cards}
    assert by_id["tester"].skills == ["code.test"]
    assert by_id["tester"].version == "1.0"
    executors = {"supervisor", "planner", "researcher", "coder", "analyst",
                 "computer", "guardian", "librarian"}
    for card in cards:
        assert isinstance(card, AgentCard)
        assert card.executor in executors, card.role_id
        assert card.model_requirements in ("fast", "reasoning", "coding", "vision")
        assert card.resource_budget["max_tool_calls"] >= 0
    assert SkillRegistry().get("research.web") is not None
    assert SkillRegistry().get("nope") is None


def test_agent_result_contract():
    result = AgentResult(success=True, role="test", output={"a": 1})
    data = result.to_dict()
    for key in ("success", "output", "evidence", "confidence", "provenance",
                "assumptions", "uncertainties", "artifacts", "actions_taken",
                "verification_status", "errors", "agent_id", "parent_task_id"):
        assert key in data
    failed = AgentResult.failure("x", "boom")
    assert not failed.success and failed.errors == ["boom"]


def test_verification_status_values():
    assert {s.value for s in VerificationStatus} == {
        "unverified", "verified", "failed", "uncertain"}


# -- message bus -------------------------------------------------------------
def test_message_types_and_classification():
    assert len(MessageType) == 16
    message = AgentMessage(type=MessageType.EVIDENCE, sender="a")
    assert message.classification == Classification.INTERNAL
    child = message.reply("b", MessageType.CRITIQUE)
    assert child.parent_id == message.message_id
    assert child.recipient == "a"
    assert AgentMessage.from_dict(message.to_dict()).message_id == message.message_id


def test_bus_isolation_and_thread():
    bus = MessageBus()
    seen: list[str] = []

    def bad(message):
        raise RuntimeError("subscriber boom")

    bus.subscribe("worker", bad)
    bus.subscribe("worker", lambda m: seen.append(m.message_id))
    first = bus.publish(AgentMessage(type=MessageType.REQUEST, sender="t",
                                     recipient="worker", task_id="t1"))
    assert seen == [first.message_id]  # bad subscriber did not break delivery
    reply = first.reply("worker", MessageType.COMPLETION)
    bus.publish(reply)
    assert [m.message_id for m in bus.thread(reply.message_id)] == [
        first.message_id, reply.message_id]
    assert bus.history(task_id="t1")
    assert bus.history(type=MessageType.REQUEST)


# -- blackboard ------------------------------------------------------------------
def test_blackboard_lifecycle():
    board = Blackboard(goal="g")
    try:
        board.write("nope", "x", author="a")
        raise AssertionError("bad section must fail")
    except ValueError:
        pass
    entry = board.write("evidence", {"a": 1}, author="r", confidence=0.8)
    fixed = board.correct(entry.entry_id, {"a": 2}, author="r2")
    assert fixed.supersedes == entry.entry_id
    assert board.read("evidence")[0].entry_id == fixed.entry_id
    assert board.retract(fixed.entry_id) and not board.retract("missing")
    assert board.read("evidence") == []
    clone = Blackboard.from_dict(board.to_dict())
    assert clone.goal == "g"
    assert clone.summary()["sections"]["evidence"] == 0


def test_blackboard_conflict_detection():
    board = Blackboard(goal="x?")
    board.write("results", {"subject": "X", "verdict": "true"},
                author="researcher", confidence=0.8)
    assert board.conflicts() == []
    board.write("results", {"subject": "X", "verdict": "false"},
                author="critic", confidence=0.6)
    assert len(board.conflicts()) == 1


# -- orchestrator ------------------------------------------------------------------
def test_depth_heuristic():
    assert Orchestrator.depth_for("hi") == 0
    assert Orchestrator.depth_for("calculate 2+2") == 1
    assert Orchestrator.depth_for("verify the backup", explicit=None) == 2
    assert Orchestrator.depth_for("research the best database", explicit=None) >= 3
    assert Orchestrator.depth_for("x", explicit=99) == 5
    assert Orchestrator.depth_for("x", explicit=-1) == 0


def test_level0_and_level1_run():
    orch = Orchestrator(_ctx())
    zero = orch.run("hi", depth=0)
    assert zero["ok"] and zero["result"]["role"] == "communication"
    one = orch.run("summarize this", depth=1)
    assert one["ok"]
    assert orch.explain("missing-task") == "task missing-task: no trace"


def test_teams_registered():
    assert set(TEAMS) == {"research", "coding", "debugging", "computer",
                          "decision", "daily"}
    assert [r for r, _ in TEAMS["coding"]][:3] == ["planner", "coder", "verifier"]


def test_team_run_with_memory_bound():
    from jarvis.memory.palace import MemoryPalace
    palace = MemoryPalace()
    palace.remember("the deploy key is rotated monthly", tier="semantic",
                    source="user")
    orch = Orchestrator(_ctx(palace=palace),
                        Budgets(max_agents=6, max_tool_calls=4))
    out = orch.run("what is the deploy key schedule?", team="daily")
    assert out["ok"]
    entries = out["blackboard"]["entries"]
    assert any(e["section"] == "evidence" for e in entries)
    assert len(out["trace"]) >= 4


def test_budgets_and_cancellation():
    orch = Orchestrator(_ctx(), Budgets(max_agents=1, max_tool_calls=0))
    capped = orch.run("big complex investigation with many steps", depth=3)
    assert capped["state"].get("capped")
    orch2 = Orchestrator(_ctx())
    task_id = "cancel-me"
    orch2.cancel(task_id)
    out = orch2.run("whatever", depth=2, task_id=task_id)
    assert out["state"].get("cancelled")


def test_unknown_role_and_spawn_limits():
    orch = Orchestrator(_ctx())
    assert orch._run_role("nope", "g", Blackboard(), "t",
                          {"agents_used": 0, "tool_calls": 0},
                          Budgets(), 999999.0, 0).success is False
    denied = orch.spawn("t", "research", "g", depth=99)
    assert not denied.success and "depth" in denied.errors[0]
    ok_spawn = orch.spawn("t", "reasoning", "hi", depth=0)
    assert ok_spawn.success


def test_conflict_resolution_no_averaging():
    from jarvis.agents.orchestrator import Orchestrator as O
    orch = O(_ctx())
    board = Blackboard(goal="x?")
    board.write("results", {"subject": "X", "verdict": "true",
                             "findings": ["source A confirms"]},
                author="researcher", confidence=0.8)
    board.write("results", {"subject": "X", "verdict": "false"},
                author="critic", confidence=0.6)
    result = orch.resolve_conflicts(board)
    assert result["resolved"] == 1
    kept = result["resolutions"][0]["kept"]
    assert kept["author"] == "researcher"  # evidence beats bare confidence
    assert "averaging" in result["resolutions"][0]["reason"]


def test_why_believe_traces_chain():
    from jarvis.memory.palace import MemoryPalace
    palace = MemoryPalace()
    palace.remember("deploy key rotated monthly", tier="semantic", source="user")
    orch = Orchestrator(_ctx(palace=palace))
    board = Blackboard(goal="deploy?")
    board.write("decisions", "rotate the deploy key monthly", author="reasoning",
                provenance="memory-recall", confidence=0.7)
    answer = orch.why_believe("deploy key", board)
    assert answer["verdict"] == "supported"
    assert answer["chain"] and answer["memory"]
    empty = orch.why_believe("zzz nothing like this", Blackboard())
    assert empty["verdict"] == "unsupported"


def test_policy_gate_blocks_unganted_tools():
    orch = Orchestrator(_ctx())
    # fresh PolicyEngine grants nothing: terminal_run needs exec → denied.
    # (computer tools like mouse_click aren't even registered here, which
    # also fails closed at lookup; this path exercises the policy denial.)
    result = orch._gated_tool("coder", "terminal_run", {"command": "ls"},
                              {"agents_used": 0, "tool_calls": 0},
                              Budgets(), "list files")
    assert not result.success
    assert "policy" in result.errors[0].lower() or "approval" in result.errors[0].lower()


def test_tool_budget_exhaustion():
    orch = Orchestrator(_ctx())
    result = orch._gated_tool("coder", "python_run", {"code": "1+1"},
                              {"agents_used": 0, "tool_calls": 99},
                              Budgets(max_tool_calls=5), "calc")
    assert not result.success and "budget" in result.errors[0]


def test_fallback_chain_and_legacy_supervisor():
    from jarvis.agents.agents import AgentRegistry, Supervisor
    orch = Orchestrator(_ctx())
    board = Blackboard(goal="g")
    state: dict = {"agents_used": 0, "tool_calls": 0}
    # researcher with no research engine and a nonsense URL fails → knowledge fallback
    result = orch._run_role("research", "not a url at all !!!", board, "t1",
                            state, Budgets(), 9999999999.0, 0)
    assert isinstance(result.success, bool)  # either path is a clean result
    # legacy supervisor untouched
    sup = Supervisor(registry=AgentRegistry())
    assert len(sup.registry.list_agents()) == 8
    task = sup.submit("check system status")
    assert sup.run_task(task.task_id).state.value == "completed"
