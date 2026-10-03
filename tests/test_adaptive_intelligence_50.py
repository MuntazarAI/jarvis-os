from __future__ import annotations

import json

from jarvis.intelligence.adaptive import (
    AdaptiveIntelligence,
    Belief,
    BeliefStatus,
    Evidence,
    EvidenceStatus,
    Experience,
    ExperienceStore,
    GoalInterpreter,
    HypothesisEngine,
    InformationGatherer,
    InformationRequest,
    LearningEngine,
    Outcome,
    Plan,
    PlanCritic,
    PlanStep,
    Prediction,
    capability_fingerprint,
)


def test_evidence_confidence_is_bounded() -> None:
    assert Evidence("x", "test", 9).confidence == 1.0
    assert Evidence("x", "test", -2).confidence == 0.0


def test_belief_support_and_contradiction() -> None:
    belief = Belief("server is healthy", confidence=0.5)
    belief.add_evidence(Evidence("health check passed", "doctor", 1.0), supports=True)
    assert belief.confidence > 0.5
    belief.add_evidence(Evidence("server returned error", "monitor", 1.0), supports=False)
    assert belief.status in {BeliefStatus.WEAKENED, BeliefStatus.CONTRADICTED}
    assert belief.evidence_status in {
        EvidenceStatus.UNCERTAIN,
        EvidenceStatus.CONTRADICTED,
        EvidenceStatus.LIKELY,
    }


def test_hypothesis_engine_is_deterministic() -> None:
    engine = HypothesisEngine()
    evidence = [
        Evidence("chrome cpu usage is high", "screen", 0.9),
        Evidence("chrome process exists", "process", 0.8),
    ]
    first = engine.generate(evidence, ["chrome caused cpu load", "thermal issue"])
    second = engine.generate(evidence, ["chrome caused cpu load", "thermal issue"])
    assert [h.statement for h in first] == [h.statement for h in second]
    assert first[0].statement == "chrome caused cpu load"


def test_information_gatherer_prefers_gain_over_raw_cost() -> None:
    gatherer = InformationGatherer()
    chosen = gatherer.choose([
        InformationRequest("inspect process", "process", 0.8, cost=1, risk=0.0),
        InformationRequest("take expensive sample", "camera", 0.95, cost=5, risk=0.1),
    ])
    assert chosen is not None
    assert chosen.source == "process"


def test_goal_interpreter_bounds_input() -> None:
    goal = GoalInterpreter().interpret("  deploy my project  ", constraints=["network only"])
    assert goal.description == "deploy my project"
    assert goal.constraints == ("network only",)


def test_plan_critic_rejects_missing_verification() -> None:
    plan = Plan(
        goal_id="g1",
        steps=(PlanStep("run tests", verification=""),),
    )
    ok, problems = PlanCritic().review(plan)
    assert not ok
    assert "missing verification" in problems[0]


def test_learning_does_not_touch_security() -> None:
    belief = Belief("tool is reliable", confidence=0.5)
    outcome = Outcome(status="success", observed="ok", verified=True)
    LearningEngine().update_belief(belief, outcome)
    assert 0.0 <= belief.confidence <= 1.0
    assert not hasattr(LearningEngine(), "grant_permission")


def test_experience_store_is_bounded_and_scrubbed(tmp_path) -> None:
    store = ExperienceStore(tmp_path, max_records=2)
    for i in range(3):
        exp = Experience(
            observation=f"event-{i}",
            context={"api_key": "do-not-store", "n": i},
            belief_ids=(),
            prediction=Prediction("future", 0.5),
            decision="observe",
            outcome=Outcome("success", "ok", verified=True),
        )
        assert store.append(exp)
    rows = store.read(10)
    assert len(rows) == 2
    assert rows[0]["context"]["api_key"] == "[REDACTED]"


def test_adaptive_digest_keeps_unknown_explicit() -> None:
    result = AdaptiveIntelligence().digest(
        "something happened",
        candidate_hypotheses=["a different thing"],
    )
    assert result["status"] in {"unknown", "uncertain", "likely", "known", "contradicted"}


def test_capability_fingerprint_is_stable() -> None:
    a = capability_fingerprint({"camera": True, "screen": False})
    b = capability_fingerprint({"screen": False, "camera": True})
    assert a == b
    assert len(a) == 16


def test_experience_serializes_json(tmp_path) -> None:
    store = ExperienceStore(tmp_path)
    exp = Experience(
        observation="hello",
        context={"scope": "local"},
        belief_ids=("b1",),
        prediction=None,
        decision="wait",
        outcome=Outcome("unknown", "unknown"),
    )
    assert store.append(exp)
    json.loads((tmp_path / "experiences.jsonl").read_text())
