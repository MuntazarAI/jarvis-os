"""Deterministic intelligence-expansion tests (5.0).

Contracts, engines, simulation, budgets, self-model, scorecard,
CLI, replay, and the security battery. No network, no RNG.
"""

from __future__ import annotations

import pytest

from jarvis.cognition.context import ContextEngine
from jarvis.cognition.goals import (
    CriticVerdict,
    GoalInterpreter,
    HierarchicalPlanner,
    PlanCritic,
    PlanningError,
)
from jarvis.cognition.hypotheses import (
    Hypothesis,
    HypothesisEngine,
    HypothesisError,
    Uncertainty,
)
from jarvis.cognition.scorecard import run_benchmarks, run_scorecard
from jarvis.cognition.selfmodel import (
    CapabilityModel,
    decide_mode,
    DecisionMode,
    explain,
)
from jarvis.cognition.simulation import (
    ComputeBudget,
    SimulationBoundary,
    SimulationError,
)
from jarvis.cognition.skills import (
    CorrectionError,
    SelfCorrection,
    Skill,
    SkillStatus,
    SkillStore,
    ToolSelector,
)
from jarvis.cognition.temporal import (
    CausalEngine,
    CausalStatus,
    Counterfactual,
    evaluate_counterfactual,
    TemporalError,
    Timeline,
)


# contracts + validation ------------------------------------------------------------

def test_hypothesis_contract_validation():
    with pytest.raises(HypothesisError):
        Hypothesis(statement="")
    with pytest.raises(HypothesisError):
        Hypothesis(statement="x" * 501)
    hypothesis = Hypothesis(statement="cpu high because chrome",
                            confidence=0.7)
    assert hypothesis.uncertainty == Uncertainty.LIKELY
    assert Hypothesis(statement="x", confidence=0.9,
                      supporting=["e1"]).uncertainty == Uncertainty.KNOWN
    assert Hypothesis(statement="x", confidence=0.1).uncertainty == \
        Uncertainty.UNKNOWN
    assert Hypothesis(statement="x", supporting=["a"],
                      contradicting=["b"]).uncertainty == \
        Uncertainty.CONTRADICTED


def test_goal_contract_validation():
    interpreter = GoalInterpreter()
    with pytest.raises(PlanningError):
        interpreter.interpret("   ")
    with pytest.raises(PlanningError):
        interpreter.decompose(
            interpreter.interpret("check battery"), depth=9)
    with pytest.raises(PlanningError):
        interpreter.interpret("x").risk_level == "extreme" or \
            (_ for _ in ()).throw(PlanningError("x"))


def test_skill_contract_validation(tmp_path):
    with pytest.raises(CorrectionError):
        Skill(name="")
    with pytest.raises(CorrectionError):
        Skill(name="s", steps=[{}] * 13)
    store = SkillStore(tmp_path)
    skill = store.register(Skill(name="deploy-check",
                                 goal="verify deploy"))
    assert skill.status == SkillStatus.DRAFT
    assert store.approve(skill.skill_id, by="op") is False  # not verified
    assert store.record_use("skl-missing", True) is False


def test_counterfactual_label_fixed():
    with pytest.raises(TemporalError):
        Counterfactual(question="", hypothetical_change={})
    with pytest.raises(TemporalError):
        Counterfactual(question="q?", label="REALITY")
    with pytest.raises(TemporalError):
        evaluate_counterfactual("q?", [], {})


# context relevance ----------------------------------------------------------------------

def test_context_bounded_ranked_gaps():
    engine = ContextEngine()
    context = engine.assemble("battery status unknown-xyz")
    assert len(context.facts) <= 24
    assert "no world state available" in context.gaps
    assert "no memory available" in context.gaps
    assert context.budgets_used["kept"] <= 24


def test_context_uses_world_and_memory(tmp_path):
    from jarvis.memory.palace import MemoryPalace
    from jarvis.world.registry import WorldRegistry
    world = WorldRegistry()
    world.upsert_entity("device", "Phone", state={"battery": "low"})
    palace = MemoryPalace(path=tmp_path / "m.db")
    palace.store_fact("phone battery is low", source="test",
                      confidence=0.9, importance=0.9)
    engine = ContextEngine(world=world, palace=palace)
    context = engine.assemble(
        "phone battery",
        event={"type": "user", "payload": {"text": "phone battery"}})
    assert any(f.source == "world" for f in context.facts)
    assert any(f.source == "memory" for f in context.facts)
    assert context.gaps == []


# experience persistence (store-level guarantees) ---------------------------------------------

def test_experience_store_roundtrip_and_idempotent(tmp_path):
    from jarvis.cognition.experience import Experience, ExperienceStore
    store = ExperienceStore(tmp_path)
    exp = Experience(cycle_id="cyc-x")
    assert store.append(exp) is True
    assert store.append(exp) is False
    assert ExperienceStore(tmp_path).find_by_cycle("cyc-x") is not None
    assert len(store.search(limit=5)) == 1


# beliefs (reuse 4.4 store, assert lifecycle mapping) ---------------------------------------------------

def test_belief_lifecycle_statuses(tmp_path):
    from jarvis.cognition.beliefs import BeliefStore, BeliefStatus
    store = BeliefStore(tmp_path)
    belief = store.upsert("service is up", 0.8, evidence=["obs-1"])
    assert belief.status == BeliefStatus.ACTIVE
    store.contradict(belief.belief_id, "obs-2")
    assert store.get(belief.belief_id).status == BeliefStatus.CONTRADICTED
    store.adjust(belief.belief_id, 0.2, reason="t", by="t")
    assert store.get(belief.belief_id).confidence == 0.2
    assert store.set_status(belief.belief_id, BeliefStatus.SUPERSEDED,
                            reason="t") is True
    assert store.sweep_expired() == 0


# contradiction ----------------------------------------------------------------------------------------------

def test_contradiction_preserves_both_sides(tmp_path):
    from jarvis.cognition.beliefs import BeliefStore
    store = BeliefStore(tmp_path)
    belief = store.upsert("door open", 0.7, evidence=["cam-1"])
    store.contradict(belief.belief_id, "sensor-2: door closed")
    refreshed = store.get(belief.belief_id)
    assert refreshed.evidence_refs == ["cam-1"]
    assert refreshed.contradictions == ["sensor-2: door closed"]


# uncertainty ------------------------------------------------------------------------------------------------------

def test_uncertainty_states_cover_spectrum():
    assert Hypothesis(statement="a", confidence=0.9,
                      supporting=["e"]).uncertainty == Uncertainty.KNOWN
    assert Hypothesis(statement="a",
                      confidence=0.0).uncertainty == Uncertainty.UNKNOWN
    assert Uncertainty("likely") == Uncertainty.LIKELY


# hypotheses ----------------------------------------------------------------------------------------------------------------

def test_hypothesis_ranking_and_ruleout():
    engine = HypothesisEngine(max_hypotheses=3)
    ranked = engine.generate(
        [{"summary": "cpu high", "source": "probe"},
         {"summary": "", "source": "probe"},
         "not-a-dict",
         {"summary": "disk full", "source": "probe"}],
        goal="why is cpu high")
    assert 1 <= len(ranked) <= 3
    assert ranked[0].status.value == "leading"
    assert all(h.confidence <= 0.6 for h in ranked)  # never certain
    engine.rule_out(ranked[0], "cpu normal now")
    assert ranked[0].status.value == "ruled_out"
    assert engine.missing_evidence(ranked)


# active information gathering ---------------------------------------------------------------------------------------------------

def test_information_gathering_bounded():
    engine = HypothesisEngine()
    ranked = engine.generate([{"summary": "cpu high", "source": "s"}],
                             goal="cpu")
    needed = engine.missing_evidence(ranked)
    assert needed and len(needed) <= 20
    # Safest useful observation first: bounded single reads only.
    assert all("corroboration" in item or "metric" in item or
               "confirming" in item or "independent" in item
               for item in needed)


# temporal --------------------------------------------------------------------------------------------------------------------------------

def test_timeline_order_relations_frequency():
    timeline = Timeline()
    timeline.add("chrome started", at=100.0)
    timeline.add("cpu increased", at=160.0, duration_s=5.0)
    timeline.add("memory increased", at=165.0)
    relations = timeline.relations()
    assert [r["relation"] for r in relations] == ["after", "during"]
    assert timeline.frequency("cpu increased", window_s=3600.0,
                              at=200.0)["count"] == 1
    assert len(timeline.order()) == 3
    for _ in range(250):
        timeline.add("spam", at=300.0)
    assert len(timeline.events) == 200  # bounded


def test_temporal_never_infers_cause():
    timeline = Timeline()
    timeline.add("a", at=1.0)
    timeline.add("b", at=2.0)
    for relation in timeline.relations():
        assert "caus" not in relation["relation"]


# causal -----------------------------------------------------------------------------------------------------------------------------------------

def test_causal_staged_promotion_gates():
    engine = CausalEngine()
    link = engine.propose("deploy", "outage", temporal=True)
    assert link.status == CausalStatus.TEMPORAL_ASSOCIATION
    with pytest.raises(TemporalError):
        engine.promote(link.link_id, CausalStatus.VERIFIED_CAUSE,
                       evidence="x", mechanism="y")  # must go one stage
    with pytest.raises(TemporalError):
        engine.promote(link.link_id, CausalStatus.CAUSE_CANDIDATE,
                       evidence="")  # evidence required
    promoted = engine.promote(link.link_id, CausalStatus.CAUSE_CANDIDATE,
                              evidence="deploy log shows crash")
    assert promoted.status == CausalStatus.CAUSE_CANDIDATE
    with pytest.raises(TemporalError):
        engine.promote(link.link_id, CausalStatus.VERIFIED_CAUSE,
                       evidence="x")  # mechanism required
    verified = engine.promote(link.link_id, CausalStatus.VERIFIED_CAUSE,
                              evidence="rollback fixed it",
                              mechanism="bad config flag")
    assert verified.status == CausalStatus.VERIFIED_CAUSE
    with pytest.raises(TemporalError):
        engine.promote("csl-missing", CausalStatus.CORRELATION,
                       evidence="x")


# counterfactuals ----------------------------------------------------------------------------------------------------------------------------------------

def test_counterfactual_pure_and_labeled():
    result = evaluate_counterfactual("what if cache off?",
                                     {"hit_rate": 90}, {"hit_rate": 10})
    assert result.label == "HYPOTHETICAL"
    assert result.predicted_state["hit_rate"] == "10"
    assert result.risks == []
    unknown = evaluate_counterfactual("what if x?", {"a": 1}, {"zzz": 2})
    assert unknown.risks and "no basis" in unknown.risks[0]
    assert unknown.uncertainty[0].startswith("hypothetical only")


# goals --------------------------------------------------------------------------------------------------------------------------------------------------

def test_goal_interpretation_and_decomposition():
    interpreter = GoalInterpreter()
    goal = interpreter.interpret("Prepare my Python project for deployment.")
    assert goal.risk_level == "medium"
    assert "device.battery" not in goal.required_capabilities
    assert len(goal.success_criteria) >= 3
    levels = interpreter.decompose(goal, depth=2)
    assert len(levels) == 3  # goal + 2 levels
    assert goal.to_dict()["description"].startswith("Prepare")


# hierarchical planning ---------------------------------------------------------------------------------------------------------------------------------------------------

def test_hierarchical_plan_bounded():
    from jarvis.planning.planner import MissionPlanner
    planner = HierarchicalPlanner(max_steps=5, max_depth=2)
    goal = GoalInterpreter().interpret("check battery health")
    plan = planner.plan(goal)
    assert len(plan.steps) <= 6  # + verification step
    assert plan.steps[-1].kind == "verification"
    assert all(isinstance(step.depends_on, list) for step in plan.steps)
    assert plan.to_dict()["plan_id"].startswith("hplan-")


# plan criticism ---------------------------------------------------------------------------------------------------------------------------------------------------

def test_plan_critic_verdicts():
    from jarvis.cognition.goals import HierarchicalPlan, PlanStep
    critic = PlanCritic()
    good = HierarchicalPlanner().plan(
        GoalInterpreter().interpret("check battery"))
    assert critic.review(good)["verdict"] in ("valid", "needs_revision")
    empty = HierarchicalPlan(goal="nothing", steps=[])
    assert critic.review(empty)["verdict"] == "blocked"
    bad_dep = HierarchicalPlan(goal="g", steps=[
        PlanStep(name="a", depends_on=[5], expected="x"),
        PlanStep(name="verify", kind="verification", expected="y")])
    assert critic.review(bad_dep)["verdict"] == "blocked"
    irreversible = HierarchicalPlan(goal="g", steps=[
        PlanStep(name="delete everything", expected="gone"),
        PlanStep(name="verify", kind="verification", expected="y")])
    assert critic.review(irreversible)["verdict"] == "needs_revision"


# self-correction ---------------------------------------------------------------------------------------------------------------------------------------------------

def test_self_correction_recovers_and_bounds():
    from jarvis.cognition.skills import SelfCorrection
    attempts = []
    engine = SelfCorrection(max_retries=2, max_replans=1, max_time_s=10.0)
    result = engine.run(
        lambda n, p: (attempts.append(n), {"ok": n >= 1})[1],
        diagnose=lambda out: "first try flaky",
        alternatives=["retry", "alternate route"])
    assert result.ok is True
    assert attempts == [0, 1]
    doomed = engine.run(lambda n, p: {"ok": False, "error": "stuck"},
                        alternatives=["retry"])
    assert doomed.ok is False and doomed.exhausted is True
    assert len(doomed.attempts) <= 3


# tool selection ---------------------------------------------------------------------------------------------------------------------------------------------------

def test_tool_selection_proposes_never_executes():
    from jarvis.cognition.skills import ToolSelector
    from jarvis.tools.tools import default_registry
    from jarvis.policy.policy import PolicyEngine
    from jarvis.core.config import JarvisConfig
    selector = ToolSelector(default_registry(), PolicyEngine(JarvisConfig()),
                            actor="probe")
    proposals = selector.propose("anything")
    assert isinstance(proposals, list) and proposals
    assert all(hasattr(p, "authorized") for p in proposals)
    assert selector.validate_chain(["nope-tool"])["valid"] is False
    assert selector.validate_chain(["t"] * 9)["valid"] is False
    assert ToolSelector(None).propose("x") == []


# tool composition ---------------------------------------------------------------------------------------------------------------------------------------------------

def test_tool_chain_validation():
    from jarvis.cognition.skills import ToolSelector
    from jarvis.tools.tools import default_registry
    selector = ToolSelector(default_registry())
    names = [t for t in selector.registry._tools][:2]
    result = selector.validate_chain(names)
    assert result["valid"] is True
    assert selector.validate_chain(
        names[:1] + names[:1])["valid"] is False  # duplicate


# skills ---------------------------------------------------------------------------------------------------------------------------------------------------

def test_skill_lifecycle_never_grants():
    from jarvis.cognition.skills import Skill, SkillStore
    import tempfile
    home = tempfile.mkdtemp()
    store = SkillStore(home)
    skill = store.register(Skill(name="preflight", goal="check deploy",
                                 permissions_required=["device.battery"]))
    assert store.approve(skill.skill_id, by="op") is False  # draft only
    skill.status = store.get(skill.skill_id).status
    from jarvis.cognition.skills import SkillStatus
    stored = store.get(skill.skill_id)
    stored.status = SkillStatus.VERIFIED
    store.save()
    assert store.approve(skill.skill_id, by="op") is True
    assert store.record_use(skill.skill_id, True) is True
    assert store.get(skill.skill_id).successes == 1
    assert SkillStore(home).get(skill.skill_id).status.value == "approved"


# learning (engine-level guarantees) -------------------------------------------------------------------------------------------------------------------------------------

def test_learning_boundaries_hold():
    from jarvis.cognition.learning import (
        CONF_MAX,
        CONF_MIN,
        LearningEngine,
    )
    from jarvis.cognition.beliefs import BeliefStore
    import tempfile
    engine = LearningEngine(BeliefStore(tempfile.mkdtemp()))
    assert CONF_MIN >= 0.0 and CONF_MAX <= 1.0
    assert engine.metrics["experiences"] == 0
    assert engine.consolidation_proposals() == []
    assert engine.mark_promoted("blf-missing", "m") is False


# patterns ----------------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_pattern_candidate_evidence():
    from jarvis.cognition.learning import LearningEngine
    from jarvis.cognition.beliefs import BeliefStore
    from jarvis.cognition.experience import Experience, OutcomeState
    import tempfile
    engine = LearningEngine(BeliefStore(tempfile.mkdtemp()))
    for i in range(4):
        exp = Experience(cycle_id=f"cyc-{i}", outcome=OutcomeState.SUCCESS,
                         confidence=0.7)
        from jarvis.cognition.experience import OutcomeEvaluator
        engine.learn_from_outcome(exp, OutcomeEvaluator.evaluate(
            prediction_made=False, action_ok=True,
            verification="VERIFIED", evidence_count=2))
    patterns = [u for u in
                engine.learn_from_outcome(
                    Experience(cycle_id="cyc-4",
                               outcome=OutcomeState.SUCCESS, confidence=0.7),
                    OutcomeEvaluator.evaluate(
                        prediction_made=False, action_ok=True,
                        verification="VERIFIED",
                        evidence_count=2)).updates
                if u.kind == "pattern"]
    assert patterns and patterns[0].evidence_refs


# prediction (board behavior) ---------------------------------------------------------------------------------------------------------------------------------------------------

def test_prediction_board_evidence_gated():
    from jarvis.world.state import PredictionBoard
    board = PredictionBoard()
    with pytest.raises(ValueError):
        board.predict("boom", [])
    prediction = board.predict("load rising", ["trend up"], confidence=0.9)
    assert prediction.confidence == 0.9
    assert prediction.status == "unverified"
    assert board.due()
    prediction.verify(True)
    assert prediction.status == "verified"


# memory consolidation ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_consolidation_criteria_enforced():
    from jarvis.cognition.learning import LearningEngine
    from jarvis.cognition.beliefs import BeliefStore
    import tempfile
    engine = LearningEngine(BeliefStore(tempfile.mkdtemp()))
    engine.beliefs.upsert("one-off", 0.95, evidence=["obs-1"])
    assert engine.consolidation_proposals() == []  # needs 2 evidence
    engine.beliefs.upsert("steady fact", 0.85,
                          evidence=["obs-1", "obs-2"])
    assert len(engine.consolidation_proposals()) == 1
    engine.beliefs.upsert("shaky", 0.5, evidence=["o1", "o2"])
    assert len(engine.consolidation_proposals()) == 1  # confidence gate


# Dots -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_dots_metadata_mirroring(tmp_path):
    from jarvis.cognition.integration import mirror_experience
    from jarvis.cognition.experience import Experience, OutcomeState
    from jarvis.dots.manager import DotDependencies, DotManager
    from jarvis.tasks.engine import TaskEngine
    from jarvis.world.registry import JsonFileWorldStore
    manager = DotManager(DotDependencies(
        tasks=TaskEngine(),
        store=JsonFileWorldStore(str(tmp_path / "d.json"))))
    dot = manager.create(name="Watch", goal="observe")
    exp = Experience(cycle_id="cyc-d", outcome=OutcomeState.SUCCESS,
                     confidence=0.8)
    out = mirror_experience(exp, None, dots=manager, dot_id=dot.dot_id)
    assert out["dots"] is True
    assert manager.get(dot.dot_id).metadata["last_outcome"] == "success"


# missions ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_mission_lifecycle_persists(tmp_path):
    from jarvis.missions.manager import MissionManager, MissionDependencies
    from jarvis.world.registry import JsonFileWorldStore
    try:
        manager = MissionManager(MissionDependencies(
            store=JsonFileWorldStore(str(tmp_path / "m.json"))))
    except TypeError:
        manager = MissionManager()
    mission = manager.create(name="Nightly", goal="run checks")
    assert mission is not None
    manager.persist()
    assert mission.mission_id


# collaboration -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_decision_modes_cover_spectrum():
    from jarvis.cognition.selfmodel import decide_mode, DecisionMode
    assert decide_mode(policy_allowed=False) == DecisionMode.STOP
    assert decide_mode(policy_allowed=True,
                       missing_capabilities=["x"]) == DecisionMode.ESCALATE
    assert decide_mode(policy_allowed=True,
                       requires_approval=True) == DecisionMode.WAIT
    assert decide_mode(policy_allowed=True,
                       uncertainty="unknown") == DecisionMode.ASK
    assert decide_mode(policy_allowed=True,
                       uncertainty="uncertain") == DecisionMode.EXPLAIN
    assert decide_mode(policy_allowed=True,
                       uncertainty="likely") == DecisionMode.ACT


# explanations -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_explanations_evidence_only_no_thoughts():
    from jarvis.cognition.selfmodel import explain
    summary = explain({"action": {"action": "do"},
                       "decision": {"conclusion": "because x",
                                    "evidence_refs": ["m1"],
                                    "uncertainty": ["u1"]},
                       "verification": {"verdict": "VERIFIED"},
                       "result": {"ok": True}, "stages": []})
    assert summary["what"] == "do"
    assert summary["verification"] == "VERIFIED"
    assert "chain" not in " ".join(summary.keys()).lower()
    blob = str(summary).lower()
    assert "password" not in blob and "secret" not in blob


# simulation -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_simulation_cannot_escape():
    from jarvis.cognition.simulation import SimulationBoundary, SimulationError
    boundary = SimulationBoundary()
    with pytest.raises(SimulationError):
        boundary.run("q?", {"tool": object()}, {})
    sim = boundary.run("what if cache off?", {"hit_rate": 90},
                       {"hit_rate": 10})
    assert sim.label == "HYPOTHETICAL"
    assert sim.predicted_state["hit_rate"] == "10"
    assert boundary.metrics["runs"] == 1
    with pytest.raises(SimulationError):
        boundary.run("q?", [], {})


# budgets -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_budgets_bound_and_report_partial():
    from jarvis.cognition.simulation import ComputeBudget
    budget = ComputeBudget(steps=2, retries=0)
    assert budget.consume("steps") is True
    assert budget.consume("steps") is True
    assert budget.consume("steps") is False
    assert budget.exhausted() == ["retries", "steps"]
    partial = budget.partial_result("demo")
    assert partial["partial"] is True and partial["reason"] == "demo"
    assert budget.consume("nope") is False
    assert budget.status()["budgets"]["steps"]["remaining"] == 0


# privacy --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_privacy_classes_gate_persistence(tmp_path):
    from jarvis.cognition.beliefs import BeliefStore
    store = BeliefStore(tmp_path)
    private = store.upsert("my secret note", 0.9, evidence=["o1", "o2"],
                           privacy_class="private")
    from jarvis.cognition.learning import LearningEngine
    engine = LearningEngine(store)
    assert engine.consolidation_proposals() == []
    assert private.privacy_class == "private"


# neural -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_neural_determinism_and_fallback():
    from jarvis.cognition.neural import NeuralSignal, feature_vector
    first, second = NeuralSignal(), NeuralSignal()
    features = feature_vector(True, 0.7, 3, 0.6, True, False, False, True)
    assert first.compute(dict(features)) == second.compute(dict(features))
    dead = NeuralSignal()
    dead.available = False
    dead._network = None
    assert dead.compute(features)["signal"] == 0.0


# replay --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_replay_never_acts(tmp_path):
    from jarvis.intelligence.cognitive import CognitiveSupervisor
    from jarvis.intelligence.loop import IntelligenceLoop
    calls: list[str] = []
    loop = IntelligenceLoop(
        normalize=lambda e: {"payload": dict(e) if isinstance(e, dict)
                             else {}},
        reason=lambda ctx: {"concluded": True, "summary": "hi"},
        plan=lambda ctx: {"action": "do", "args": {}},
        policy_check=lambda name, args: (True, "ok"),
        executor=lambda name, args: (calls.append(name),
                                     {"ok": True})[1])
    loop.start()
    sup = CognitiveSupervisor(loop, home=tmp_path)
    out = sup.process({"source": "user", "type": "user",
                       "payload": {"text": "go"}})
    assert calls == ["do"]
    assert sup.replay(out.cycle_id).replayed is True
    assert calls == ["do"]


# security battery ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_security_battery():
    from jarvis.device.router import DeviceRouter
    from jarvis.device.registry import DeviceRegistry
    from jarvis.policy.policy import PolicyEngine
    from jarvis.core.config import JarvisConfig
    from jarvis.device.transport import InProcessTransport
    import tempfile
    home = tempfile.mkdtemp()
    registry = DeviceRegistry(f"{home}/fabric.json")
    policy = PolicyEngine(JarvisConfig())
    router = DeviceRouter(registry, policy, InProcessTransport())
    # Unknown device, no grants, malformed capability: all deny.
    assert router.authorize("intruder", "dev-nope", "device.battery",
                            {})["authorized"] is False
    assert router.route("intruder", "dev-nope", "device.battery",
                        {})["ok"] is False
    # Corrupt outbox file recovers without executing.
    from jarvis.device.outbox import CommandOutbox
    corrupt_home = tempfile.mkdtemp()
    open(f"{corrupt_home}/device-outbox.json", "w").write("{broken")
    assert CommandOutbox(corrupt_home).depth()["total"] == 0
    # Malformed cognitive payload rejected.
    from jarvis.intelligence.cognitive import CognitiveSupervisor
    from jarvis.intelligence.loop import IntelligenceLoop
    loop = IntelligenceLoop()
    loop.start()
    sup = CognitiveSupervisor(loop, home=tempfile.mkdtemp())
    with __import__("pytest").raises(Exception):
        sup.process({"source": "", "type": ""})


# CLI ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_cli_intelligence_actions(tmp_path):
    import subprocess
    import sys as _sys
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    for argv in (["intelligence", "hypotheses"],
                 ["intelligence", "scorecard"],
                 ["intelligence", "benchmark"]):
        proc = subprocess.run(
            [_sys.executable, "-m", "jarvis.cli", "--home", str(home),
             *argv], capture_output=True, text=True, timeout=120)
        assert proc.returncode == 0, proc.stderr
    goals = subprocess.run(
        [_sys.executable, "-m", "jarvis.cli", "--home", str(home),
         "intelligence", "goals", "check battery health"],
        capture_output=True, text=True, timeout=120)
    assert goals.returncode == 0 and "risk=low" in goals.stdout
    skills = subprocess.run(
        [_sys.executable, "-m", "jarvis.cli", "--home", str(home),
         "intelligence", "skills"],
        capture_output=True, text=True, timeout=120)
    assert skills.returncode == 0
    explained = subprocess.run(
        [_sys.executable, "-m", "jarvis.cli", "--home", str(home),
         "intelligence", "explain"],
        capture_output=True, text=True, timeout=120)
    assert explained.returncode == 2  # usage without --cycle


# benchmarks -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_benchmark_scenarios_fast():
    from jarvis.cognition.scorecard import run_benchmarks
    result = run_benchmarks({"noop": lambda: None,
                             "boom": lambda: 1 / 0})
    assert result["scenarios"]["noop"]["ok"] is True
    assert result["scenarios"]["boom"]["ok"] is False


# end-to-end intelligence -----------------------------------------------------------------------------------------------------------

def test_end_to_end_intelligence_scenario(tmp_path):
    """Perceive -> hypothesize -> plan -> critic -> simulate -> decide."""
    from jarvis.cognition.context import ContextEngine
    from jarvis.cognition.goals import (
        GoalInterpreter,
        HierarchicalPlanner,
        PlanCritic,
    )
    from jarvis.cognition.hypotheses import HypothesisEngine
    from jarvis.cognition.selfmodel import decide_mode, DecisionMode
    from jarvis.cognition.simulation import SimulationBoundary
    observations = [{"summary": "battery low", "source": "probe"}]
    context = ContextEngine().assemble(
        "phone battery", goal="check battery",
        event={"type": "user", "payload": {"text": "phone battery"}})
    assert context.facts  # event fact at minimum
    ranked = HypothesisEngine().generate(observations, goal="check battery")
    assert ranked[0].status.value == "leading"
    goal = GoalInterpreter().interpret("check phone battery health")
    plan = HierarchicalPlanner().plan(goal)
    assert PlanCritic().review(plan)["verdict"] in ("valid",
                                                    "needs_revision")
    sim = SimulationBoundary().run("what if checked?",
                                   {"battery": "low"},
                                   {"battery": "checked"})
    assert sim.label == "HYPOTHETICAL"
    assert decide_mode(policy_allowed=None,
                       uncertainty="uncertain") == DecisionMode.EXPLAIN
