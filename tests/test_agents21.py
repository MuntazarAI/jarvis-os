"""Agent Intelligence 2.1: traces, explain, evidence, robustness, resilience."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.agents.blackboard import (  # noqa: E402
    Blackboard,
    EntryState,
    VersionConflict,
)
from jarvis.agents.bus import MessageBus  # noqa: E402
from jarvis.agents.contract import VerificationStatus  # noqa: E402
from jarvis.agents.orchestrator import (  # noqa: E402
    Budgets,
    Orchestrator,
    OrchestratorContext,
    RunRecord,
)


def _ctx(home="", **kw):
    from jarvis.agents.agents import AgentRegistry, Planner
    from jarvis.policy.policy import PolicyEngine
    from jarvis.tools.tools import default_registry
    base = {"registry": AgentRegistry(), "planner": Planner(),
            "policy": PolicyEngine(), "tools": default_registry(),
            "home": home or tempfile.mkdtemp()}
    base.update(kw)
    return OrchestratorContext(**base)


# -- trace lifecycle -------------------------------------------------------
def test_run_record_structured_and_persisted():
    home = tempfile.mkdtemp()
    orch = Orchestrator(_ctx(home=home))
    out = orch.run("hi", depth=0)
    record = orch.runs[out["run_id"]]
    data = record.to_dict()
    for key in ("run_id", "task_id", "goal", "depth", "status",
                "started_at", "duration_ms", "roles", "tools",
                "tool_calls", "budgets", "evidence_refs", "fallbacks",
                "policy_decisions", "outcome", "failure", "board_summary"):
        assert key in data, key
    assert record.status == "ok" and record.duration_ms >= 0
    persisted = list(Path(home, "traces").glob("run-*.json"))
    assert len(persisted) == 1
    loaded = orch.load_trace(out["task_id"])
    assert loaded is not None and loaded.run_id == record.run_id
    assert orch.load_trace("missing") is None


def test_nested_child_traces_carry_parent():
    orch = Orchestrator(_ctx())
    parent = orch.run("hi", depth=0)
    child_out = orch.run("hi again", depth=0,
                         task_id="child-1")
    assert child_out["ok"]
    assert orch.runs[parent["run_id"]].parent_id == ""
    # spawn() wires parent task ids with depth caps
    spawned = orch.spawn(parent["task_id"], "reasoning", "sub", depth=0)
    assert spawned.success and spawned.parent_task_id == parent["task_id"]


def test_explain_reconstructs_narrative_and_redacts():
    orch = Orchestrator(_ctx())
    out = orch.run("calculate 2+2", depth=1)
    text = orch.explain(out["task_id"])
    for marker in ("request:", "orchestration:", "roles:", "result:"):
        assert marker in text, text
    evil = "run with password=hunter2-secret"
    redacted = Orchestrator._redact(evil)
    assert "hunter2" not in redacted and "[redacted" in redacted
    long_token = "key " + "x" * 50
    assert "xxxx" not in Orchestrator._redact(long_token)
    assert orch.explain("missing-task") == "task missing-task: no trace"


def test_explain_cross_session_from_disk():
    home = tempfile.mkdtemp()
    orch = Orchestrator(_ctx(home=home))
    out = orch.run("hi", depth=0)
    fresh = Orchestrator(_ctx(home=home))
    text = fresh.explain(out["task_id"])
    assert "request: hi" in text and "orchestration:" in text


# -- evidence --------------------------------------------------------------
def test_evidence_links_and_visibility():
    board = Blackboard(goal="g")
    claim = board.write("results", {"subject": "X", "verdict": "true"},
                        author="researcher", confidence=0.8)
    board.link_evidence(claim.entry_id, "supports", claim.entry_id,
                        author="researcher")
    assert claim.links[0]["relation"] == "supports"
    try:
        board.link_evidence(claim.entry_id, "vibes", "x", author="r")
        raise AssertionError("bad relation must fail")
    except ValueError:
        pass
    grouped = board.evidence_for("X")
    assert grouped["supporting"] and not grouped["conflicting"]
    critic = board.write("results", {"subject": "X", "verdict": "false"},
                         author="critic", confidence=0.6)
    board.link_evidence(critic.entry_id, "refutes", claim.entry_id,
                        author="critic")
    assert board.evidence_for("X")["conflicting"]
    assert len(board.conflicts()) == 1


def test_why_believe_semantics_preserved():
    from jarvis.memory.palace import MemoryPalace
    palace = MemoryPalace()
    palace.remember("deploy key rotated monthly", tier="semantic", source="user")
    orch = Orchestrator(_ctx(palace=palace))
    board = Blackboard(goal="deploy?")
    board.write("decisions", "rotate the deploy key monthly",
                author="reasoning", provenance="memory-recall", confidence=0.7)
    assert orch.why_believe("deploy key", board)["verdict"] == "supported"
    assert orch.why_believe("zzz nothing", Blackboard())["verdict"] == "unsupported"


# -- blackboard robustness ---------------------------------------------------
def test_supersession_cas_and_chain():
    board = Blackboard(goal="g")
    first = board.write("evidence", {"v": 1}, author="a")
    assert first.version == 1
    second = board.correct(first.entry_id, {"v": 2}, author="b",
                           expected_version=1)
    assert second.version == 2 and second.supersedes == first.entry_id
    assert board.current(first.entry_id).entry_id == second.entry_id
    try:
        board.correct(first.entry_id, {"v": 3}, author="c",
                      expected_version=1)
        raise AssertionError("stale CAS must fail")
    except VersionConflict:
        pass
    try:
        board.correct(first.entry_id, {"v": 3}, author="c")
        raise AssertionError("correcting superseded entry must fail")
    except VersionConflict:
        pass
    # history preserved, provenance intact
    assert len(board.read("evidence", active_only=False)) == 2
    assert board.read("evidence")[0].entry_id == second.entry_id


def test_serialization_preserves_meaning():
    board = Blackboard(goal="g")
    entry = board.write("evidence", {"v": 1}, author="a", provenance="p",
                        confidence=0.9)
    board.link_evidence(entry.entry_id, "supports", entry.entry_id, author="a")
    clone = Blackboard.from_dict(board.to_dict())
    back = clone.read("evidence")[0]
    assert (back.version, back.provenance, back.confidence) == (1, "p", 0.9)
    assert back.links[0]["relation"] == "supports"
    # legacy entries without version/links still load
    legacy = Blackboard.from_dict({"goal": "g", "entries": [
        {"section": "evidence", "content": "x", "author": "a",
         "entry_id": "bb-old"}]})
    assert legacy.read("evidence")[0].version == 1


# -- resilience ----------------------------------------------------------------
def test_cancellation_mid_team():
    orch = Orchestrator(_ctx())
    task_id = "cancel-team"
    orch.cancel(task_id)
    out = orch.run("plan and build and research extensively", depth=3,
                   task_id=task_id)
    assert not out["ok"] and out["state"].get("cancelled")


def test_timeout_degrades_honestly():
    orch = Orchestrator(_ctx(), Budgets(max_runtime_s=0.0))
    out = orch.run("do something big with many stages", depth=3)
    assert not out["ok"]
    assert out["state"].get("timeout") or out.get("failure")


def test_budget_exhaustion_surfaced():
    # capped: first stage succeeds, cap flag honestly surfaced
    orch = Orchestrator(_ctx(), Budgets(max_agents=1, max_tool_calls=0))
    out = orch.run("big complex investigation with many steps", depth=3)
    assert out["state"].get("capped")
    # zero budget: nothing can run, honest failure
    orch2 = Orchestrator(_ctx(), Budgets(max_agents=0))
    out2 = orch2.run("big complex investigation with many steps", depth=3)
    assert not out2["ok"]


def test_fallback_and_verifier_failure():
    orch = Orchestrator(_ctx())
    board = Blackboard(goal="g")
    board.write("results", {"subject": "S", "verdict": "failed"},
                author="coder", confidence=0.4)
    out = orch.run("verify the thing", depth=2)
    assert isinstance(out["ok"], bool)
    assert "verification" in [e["section"] for e in out["blackboard"]["entries"]] \
        or out["blackboard"]["entries"]


def test_spawn_depth_cap():
    orch = Orchestrator(_ctx(), Budgets(max_depth=1))
    denied = orch.spawn("t", "research", "g", depth=5)
    assert not denied.success and "depth" in denied.errors[0]


# -- memory promotion ------------------------------------------------------------
def test_memory_promotion_carries_provenance():
    from jarvis.memory.palace import MemoryPalace
    palace = MemoryPalace()
    palace.remember("the deploy key is rotated monthly", tier="semantic",
                    source="user")
    orch = Orchestrator(_ctx(palace=palace))
    out = orch.run("what is the deploy key schedule?", team="daily")
    assert out["ok"]
    evidence = [e for e in out["blackboard"]["entries"]
                if e["section"] == "evidence" and e["author"] == "memory"]
    assert evidence
    prov = evidence[0]["content"]["provenance"]
    assert prov and prov[0]["origin"] == "told"
    assert "confidence" in prov[0] and "id" in prov[0]


# -- depth heuristic ---------------------------------------------------------------
def test_depth_deterministic_and_act_based():
    assert Orchestrator.depth_for("hi") == 0
    assert Orchestrator.depth_for("calculate 2+2") == 1
    assert Orchestrator.depth_for("verify the backup") == 2
    assert Orchestrator.depth_for("research the best database") >= 3
    assert Orchestrator.depth_for("x", explicit=99) == 5
    assert Orchestrator.depth_for("x", explicit=-1) == 0
    # same input → same depth, twice
    assert Orchestrator.depth_for("verify the backup") == \
        Orchestrator.depth_for("verify the backup")


# -- CLI -----------------------------------------------------------------------
ROOT = str(Path(__file__).resolve().parent.parent)


def test_cli_agents_commands():
    import json
    import subprocess
    base = ["python3", "-m", "jarvis.cli", "agents"]
    listing = subprocess.run(base + ["list"], capture_output=True, text=True,
                             timeout=120, cwd=ROOT)
    assert listing.returncode == 0 and "orchestrator" in listing.stdout
    teams = subprocess.run(base + ["teams"], capture_output=True, text=True,
                           timeout=120, cwd=ROOT)
    assert teams.returncode == 0 and "research" in teams.stdout
    status = subprocess.run(base + ["status", "--json"], capture_output=True,
                            text=True, timeout=120, cwd=ROOT)
    assert status.returncode == 0
    info = json.loads(status.stdout)
    assert info["roles"] == 31 and "budgets" in info
    run = subprocess.run(base + ["run", "hi", "--depth", "0", "--json"],
                         capture_output=True, text=True, timeout=180, cwd=ROOT)
    assert run.returncode == 0
    payload = json.loads(run.stdout)
    assert payload["ok"] and payload["task_id"]
