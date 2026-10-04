"""Learning & belief drift tests (1.0).

Controlled repeated observations against the real LearningEngine +
BeliefStore. Asserts conservatism properties: bounded confidence,
no runaway certainty, no oscillation blowup, private never promoted,
duplicates collapse. Deterministic, offline.
"""

from __future__ import annotations

import pytest

from jarvis.cognition.beliefs import BeliefStore
from jarvis.cognition.experience import (
    Experience,
    OutcomeEvaluator,
    PredictionEvaluation,
    PredictionVerdict,
)
from jarvis.cognition.learning import CONF_MAX, CONF_MIN, LearningEngine


def _engine(home):
    store = BeliefStore(home)
    return LearningEngine(store), store


def _experience(cycle: str, evaluations=None, privacy="local"):
    return Experience(cycle_id=cycle, confidence=0.6,
                      privacy_class=privacy,
                      evaluations=evaluations or [])


def _correct(n: int, pid: str = "p1"):
    return PredictionEvaluation(
        prediction_id=pid, experience_id=f"exp-{n}",
        expected="x", actual="x", verdict=PredictionVerdict.CORRECT,
        confidence_before=0.6)


def _incorrect(n: int, pid: str = "p1"):
    return PredictionEvaluation(
        prediction_id=pid, experience_id=f"exp-{n}",
        expected="x", actual="y", verdict=PredictionVerdict.INCORRECT,
        confidence_before=0.6)


def _evaluate_learn(engine, store, experience):
    evaluation = OutcomeEvaluator.evaluate(
        prediction_made=bool(experience.evaluations),
        action_ok=None, verification="UNKNOWN", evidence_count=1)
    # Force learnability for drift probing: resolved evaluations only.
    if not evaluation.should_learn:
        evaluation.should_learn = True
    report = engine.learn_from_outcome(experience, evaluation,
                                       by="drift-test")
    return evaluation, report


def test_consistent_evidence_stabilizes_bounded(tmp_path):
    engine, store = _engine(tmp_path)
    for n in range(50):
        _evaluate_learn(engine, store, _experience(f"c{n}", [_correct(n)]))
    matches = [b for b in store.find(limit=1000)
               if "is reliable" in b.statement]
    assert len(matches) == 1  # one belief, not 50
    assert matches[0].confidence <= CONF_MAX
    assert matches[0].confidence > 0.5  # moved, then asymptoted


def test_contradictory_evidence_no_certainty(tmp_path):
    engine, store = _engine(tmp_path)
    for n in range(30):
        evaluation = _correct(n) if n % 2 == 0 else _incorrect(n)
        _evaluate_learn(engine, store, _experience(f"c{n}", [evaluation]))
    matches = [b for b in store.find(limit=1000)
               if "is reliable" in b.statement]
    assert len(matches) == 1
    assert CONF_MIN <= matches[0].confidence <= CONF_MAX
    assert matches[0].confidence < 0.9  # never certain under conflict


def test_repeated_failure_weakens_with_floor(tmp_path):
    engine, store = _engine(tmp_path)
    for n in range(40):
        _evaluate_learn(engine, store, _experience(f"c{n}",
                                                   [_incorrect(n)]))
    matches = [b for b in store.find(limit=1000)
               if "is reliable" in b.statement]
    assert len(matches) == 1
    assert matches[0].confidence == CONF_MIN  # floored, not negative


def test_private_experience_never_learned(tmp_path):
    engine, store = _engine(tmp_path)
    for n in range(10):
        _evaluate_learn(engine, store,
                        _experience(f"c{n}", [_correct(n)],
                                    privacy="private"))
    assert store.find(limit=1000) == []
    assert engine.metrics["skipped"] == 10


def test_duplicate_observations_collapse(tmp_path):
    engine, store = _engine(tmp_path)
    for n in range(10):
        store.upsert("sky is blue", 0.8, evidence=[f"ev-{n}"])
    matches = [b for b in store.find(limit=1000)
               if b.statement == "sky is blue"]
    assert len(matches) == 1
    assert matches[0].revision == 9
    assert len(matches[0].evidence_refs) <= 10


def test_belief_prune_bounded(tmp_path):
    import jarvis.cognition.beliefs as beliefs_mod
    old_max, beliefs_mod.MAX_BELIEFS = beliefs_mod.MAX_BELIEFS, 5
    try:
        store = BeliefStore(tmp_path)
        for i in range(12):
            store.upsert(f"drift statement {i}", 0.5)
        assert len(store._beliefs) == 5
    finally:
        beliefs_mod.MAX_BELIEFS = old_max
