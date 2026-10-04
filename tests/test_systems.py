"""Verification tests for cognition, mentalist, tools, policy, agents, tasks."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.agents.agents import Agent, AgentRegistry, Planner, PlanStep, Supervisor  # noqa: E402
from jarvis.cognition.cognition import (  # noqa: E402
    AttentionController,
    ExecutiveFunction,
    Perception,
    Reflector,
    Understander,
)
from jarvis.cognition.mentalist import Baseline, MentalistMode  # noqa: E402
from jarvis.core.types import ActionPlan, Confidence, RiskLevel  # noqa: E402
from jarvis.inference.analysis import Claim  # noqa: E402
from jarvis.policy.policy import PolicyEngine, RiskEngine  # noqa: E402
from jarvis.tasks.engine import (  # noqa: E402
    TaskEngine,
    Trigger,
    TriggerEngine,
    Workflow,
    WorkflowEngine,
    WorkflowNode,
)
from jarvis.tools.tools import default_registry  # noqa: E402


# -- cognition -----------------------------------------------------------
def test_perception_modalities():
    p = Perception()
    o1 = p.perceive_text("hello")
    o2 = p.perceive_system("cpu 90%")
    assert o1.modality == "text" and o2.confidence == 0.95
    assert p.by_modality("system") == [o2] and len(p.latest()) == 2
    p.clear()
    assert p.latest() == []


def test_understander_intents_entities():
    u = Understander()
    assert u.understand("deploy the site tomorrow at 9am").intent == "command"
    assert u.understand("what time is it?").intent == "question"
    assert u.understand("hello there").intent == "greeting"
    assert u.understand("yes").intent == "confirmation"
    assert u.understand("the sky is blue").intent == "statement"
    e = u.understand('meet Darren on 2026-10-05 about "migration"')
    assert "2026-10-05" in e.entities["date"] and "Darren" in e.entities["names"]
    assert u.understand("fix the bug", {"active_app": "terminal"}).situation == "working"


def test_attention_budget_and_focus_mode():
    a = AttentionController()
    items = [{"id": "i1", "text": "coffee"},
             {"id": "i2", "text": "URGENT deploy failed", "priority": 1, "is_anomaly": True}]
    assert a.attend(items)[0]["id"] == "i2" and a.state.focus == "i2"
    assert a.cognitive_load(4, 10)["overloaded"]
    a2 = AttentionController()
    a2.state.focus_mode = True
    assert a2.attend([{"id": "x", "text": "blah"}]) == []


def test_executive_priority_decompose_schedule():
    x = ExecutiveFunction()
    assert x.eisenhower(True, True) == "do_now" and x.eisenhower(False, False) == "drop"
    tasks = [{"id": "a", "urgent": False, "important": False},
             {"id": "b", "urgent": True, "important": True}]
    assert [t["id"] for t in x.prioritize(tasks)] == ["b", "a"]
    assert len(x.decompose("Build a website")) == 5
    x.schedule("backup", 100)
    x.schedule("cleanup", 50)
    assert [e["action"] for e in x.due(60)] == ["cleanup"]
    assert x.allocate(2, 512)["approved"] and not x.allocate(999, 99999)["approved"]


def test_reflector_checks_and_failure_analysis():
    r = Reflector()
    assert r.self_check("") == ["empty output"]
    assert r.verify_result("deploy ok", "deploy")["matched"]
    assert not r.verify_result("ok", "deploy")["matched"]
    assert r.analyze_failure("rm", "permission denied")["likely_cause"] == "permission"
    r.learn("verify paths")
    r.learn("verify paths")
    assert r.lessons == ["verify paths"]
    assert r.critique_plan(["step one", "step one"])


# -- mentalist -----------------------------------------------------------
def test_mentalist_full_sequence():
    m = MentalistMode()
    o1 = m.observe("chair left of desk", kind="visual", source="camera")
    m.record_facts([o1])
    m.establish_baseline([{"speech": {"speed": "normal"}}] * 2 + [{"speech": {"speed": "fast"}}])
    dev = m.check_deviation({"speech": {"speed": "fast"}})
    assert dev and "not deception" in dev[0]["note"]
    assert Baseline().deviations({"speech": {"speed": "x"}})
    hs = m.hypothesize(["someone moved the chair", "perspective changed"])
    assert len(hs) == 2
    assert len(m.find_contradictions(
        [Claim("u", "chair moved"), Claim("u", "chair did not move")])) == 1
    assert m.ask("find mover", ["footage"], ["photo"])["best_question"]
    assert m.verify("chair always moves")["verdict"] == "unsupported"
    assert m.deception_check(0.9, 0.9, [])["findings"] == []
    rep = m.report(unknowns=["who"], next_test="check footage")
    assert rep.unknowns == ["who"]
    text = m.render()
    for section in ("OBSERVATIONS", "EVIDENCE", "HYPOTHESES", "CONFIDENCE", "NEXT TEST"):
        assert section in text


# -- tools / policy ------------------------------------------------------
def test_tools_registry_and_sandbox():
    reg = default_registry()
    assert len(reg.list_tools()) == 8  # + filesystem_move (autonomy)
    move = reg.get("filesystem_move")
    assert move.spec.required_permissions == ["fs.write"]
    assert reg.call("python_run", code="2 + 3 * 4").output["result"] == 14
    assert not reg.call("python_run", code="import os").ok
    assert not reg.call("python_run", code='open("/etc/passwd").read()').ok
    assert "hello" in reg.call("terminal_run", command="echo hello").output["stdout"]
    assert not reg.call("terminal_run", command="nonexistent-binary-xyz").ok
    assert not reg.call("nope").ok
    try:
        reg.register(reg.get("system_probe"))
        raise AssertionError("duplicate registration must fail")
    except ValueError:
        pass


def test_policy_gates_and_stop():
    rk = RiskEngine()
    assert rk.assess("read status").risk_level == RiskLevel.SAFE
    d = rk.assess("delete all system files in /etc")
    assert d.risk_level == RiskLevel.DESTRUCTIVE and d.requires_approval
    assert rk.assess("read file", {"path": "~/.ssh/id_rsa"}).risk == 1.0
    pe = PolicyEngine()
    pe.grant("coder", "fs.read")
    plan = ActionPlan(action="read file", args={"path": "n.txt"},
                      required_permissions=["fs.read"])
    assert pe.evaluate("coder", plan).allow
    bad = ActionPlan(action="delete system files", args={}, required_permissions=["exec"])
    dec = pe.evaluate("coder", bad)
    assert not dec.allow and dec.requires_approval
    tok = pe.request_approval("coder", bad, dec)
    assert pe.approve(tok) and pe.approved(tok) and not pe.approve(tok)
    assert pe.privacy_check("secret", "vault")[0]
    assert not pe.privacy_check("secret", "external")[0]
    pe.engage_stop()
    assert not pe.evaluate("coder", plan).allow
    assert pe.release_stop() and pe.evaluate("coder", plan).allow


# -- agents --------------------------------------------------------------
def test_agent_lifecycle_and_planner():
    r = AgentRegistry()
    a = Agent(name="coder", role="code")
    r.spawn(a)
    try:
        r.spawn(a)
        raise AssertionError("duplicate spawn must fail")
    except ValueError:
        pass
    a.send({"hi": 1})
    msg = a.receive()
    assert msg["hi"] == 1 and a.receive() is None
    assert r.shutdown(a.agent_id) and not r.shutdown("nope")
    fork = [PlanStep("a", "x"), PlanStep("b", "y"),
            PlanStep("c", "z", depends_on=["a", "b"])]
    assert Planner.validate(fork)[-1] == "c"
    assert Planner.independent_groups(fork) == [["a", "b"], ["c"]]
    try:
        Planner.validate([PlanStep("a", "x", depends_on=["b"]),
                          PlanStep("b", "y", depends_on=["a"])])
        raise AssertionError("cycle must fail")
    except ValueError as exc:
        assert "cycle" in str(exc)


def test_supervisor_runs_and_fails_cleanly():
    sup = Supervisor()
    assert len(sup.registry.list_agents()) == 8
    done = sup.run_task(sup.submit("Check system status").task_id)
    assert done.state.value == "completed" and done.progress == 1.0

    def boom(step, agent):  # noqa: ANN001, ANN202
        raise RuntimeError("tool exploded")

    sup2 = Supervisor(on_step=boom)
    failed = sup2.run_task(sup2.submit("Build a website").task_id)
    assert failed.state.value == "failed" and "exploded" in failed.error
    try:
        sup.run_task("missing")
        raise AssertionError("unknown task must fail")
    except KeyError:
        pass
    assert Supervisor().vote(["a", "b"], {"x": "a", "y": "a", "z": "b"}) == "a"


# -- tasks / workflows / triggers ----------------------------------------
def test_task_engine_dependencies_retries():
    te = TaskEngine(max_retries=1)
    a = te.register("first", priority=1)
    b = te.register("second", priority=9, depends_on=[a.task_id])
    assert te.next_ready().task_id == a.task_id
    te.complete(a.task_id, "done")
    assert te.next_ready().task_id == b.task_id
    te.fail(b.task_id, "boom")
    assert te.tasks[b.task_id].state.value == "queued"
    te.fail(b.task_id, "boom")
    assert te.tasks[b.task_id].state.value == "failed" and len(te.dead_letters) == 1
    c = te.register("third")
    assert te.cancel(c.task_id) and not te.cancel(c.task_id)
    assert te.register("late", deadline=1.0) in te.overdue()


def test_workflow_failure_semantics_and_conditions():
    we = WorkflowEngine()
    wf = Workflow(name="deploy")
    wf.add(WorkflowNode("t1", "task", {"task": "migrate"},
                        next_on_ok="gate", next_on_fail="fix"))
    wf.add(WorkflowNode("gate", "condition", {"key": "flag", "equals": True},
                        next_on_ok="t2", next_on_fail="fix"))
    wf.add(WorkflowNode("t2", "task", {"task": "restart"},
                        next_on_ok="", next_on_fail="fix"))
    wf.add(WorkflowNode("fix", "task", {"task": "rollback"}))
    we.register(wf)
    ok_run = we.run("deploy", lambda n, c: {"ok": True}, context={"flag": True})
    assert ok_run["ok"] and ok_run["visited"] == ["t1", "gate", "t2"]
    bad_run = we.run("deploy", lambda n, c: {"ok": n.node_id != "t2", "error": "no"},
                     context={"flag": True})
    assert not bad_run["ok"] and bad_run["visited"][-1] == "fix"
    assert any("t2" in f for f in bad_run["failures"])
    gate_run = we.run("deploy", lambda n, c: {"ok": True}, context={"flag": False})
    assert gate_run["ok"] and gate_run["visited"] == ["t1", "gate", "fix"]


def test_trigger_matching():
    tg = TriggerEngine()
    t1 = tg.add(Trigger(kind="schedule", spec={"at": 100}, action="backup"))
    assert tg.poll({"now": 50}) == []
    assert [t.trigger_id for t in tg.poll({"now": 150})] == [t1.trigger_id]
    assert tg.poll({"now": 200}) == []
    t2 = tg.add(Trigger(kind="file", spec={"path": "/inbox"}, action="process"))
    assert t2 in tg.poll({"now": 1, "new_files": ["/inbox/a.txt"]})
    assert t2 not in tg.poll({"now": 1, "new_files": ["/other/b.txt"]})
    t3 = tg.add(Trigger(kind="system", spec={"metric": "disk_free", "above": 90},
                        action="clean"))
    assert t3 in tg.poll({"now": 2, "disk_free": 95})
    assert t3 not in tg.poll({"now": 2, "disk_free": 10})
    assert tg.remove(t1.trigger_id) and not tg.remove("nope")
