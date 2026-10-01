"""Locked-in verification tests for all jarvis-os modules built so far.

Every assertion here was executed against the real code and passed.
Run with: pytest tests/ -q
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.core.config import JarvisConfig  # noqa: E402
from jarvis.core.types import (  # noqa: E402
    CognitiveReport,
    Confidence,
    Observation,
    RiskLevel,
)
from jarvis.events.store import Event, EventBus, EventStore  # noqa: E402
from jarvis.inference.analysis import (  # noqa: E402
    Claim,
    ContradictionDetector,
    InformationGapDetector,
    QuestionStrategy,
    Timeline,
    deception_guard,
    safe_deception_analysis,
)
from jarvis.inference.evidence import EvidenceEngine  # noqa: E402
from jarvis.inference.hypothesis import HypothesisEngine, HypothesisLab  # noqa: E402
from jarvis.inference.reasoning import (  # noqa: E402
    AbductiveReasoner,
    DeductiveReasoner,
    InductiveReasoner,
    MetaReasoner,
    RedTeamReasoner,
)
from jarvis.memory.consolidation import MemoryConsolidator, summarize_text  # noqa: E402
from jarvis.memory.graph import KnowledgeGraph, extract_entities  # noqa: E402
from jarvis.memory.palace import MemoryPalace  # noqa: E402
from jarvis.world.model import WorldModel  # noqa: E402


# -- config / types ------------------------------------------------------
def test_config_validate_and_roundtrip():
    c = JarvisConfig()
    assert c.validate() == []
    c2 = JarvisConfig.from_dict(c.to_dict())
    assert c2.cognitive.tool_budget == c.cognitive.tool_budget


def test_config_rejects_bad_values():
    for mutate in (
        lambda c: setattr(c.server, "port", 99999),
        lambda c: setattr(c.policy, "proactivity", "nope"),
        lambda c: setattr(c.cognitive, "tool_budget", 0),
    ):
        bad = JarvisConfig()
        mutate(bad)
        try:
            bad.validate()
        except ValueError:
            continue
        raise AssertionError("validation should have failed")


def test_confidence_scale():
    assert Confidence.from_score(0.05) == Confidence.UNKNOWN
    assert Confidence.from_score(0.3) == Confidence.LOW
    assert Confidence.from_score(0.6) == Confidence.MEDIUM
    assert Confidence.from_score(0.9) == Confidence.HIGH
    assert RiskLevel.HIGH.numeric == 0.75


def test_cognitive_report_renders():
    r = CognitiveReport(
        observations=[Observation(kind="text", content="hello")],
        confidence=Confidence.MEDIUM,
        next_test="ask",
    )
    text = r.render()
    assert "OBSERVATIONS" in text and "CONFIDENCE: medium" in text


# -- events --------------------------------------------------------------
def test_event_dedup_and_replay():
    s = EventStore()
    b = EventBus(s)
    seen = []
    b.subscribe("agent.*", seen.append)
    b.publish(Event(type="agent.started", payload={"a": 1}))
    d1 = b.publish(Event(type="agent.done", payload={}, dedup_key="k1"))
    d2 = b.publish(Event(type="agent.done", payload={}, dedup_key="k1"))
    assert d1.seq == d2.seq
    assert len(seen) == 3
    c = s.record("task.done", {"ok": True}, correlation_id="c1", causation_id=d1.event_id)
    assert c.payload == {"ok": True}
    assert len(s.by_correlation("c1")) == 1
    assert len(s.causes(d1.event_id)) == 1
    s.snapshot({"base": 100})
    s.record("a", {"n": 1})
    assert s.replay(lambda st, e: {**st, "n": st.get("n", 0) + 1}) == {"base": 100, "n": 1}


def test_bus_handler_isolation():
    s = EventStore()
    b = EventBus(s)
    good = []

    def bad(ev):  # noqa: ANN001, ANN202
        raise RuntimeError("boom")

    b.subscribe("*", bad)
    b.subscribe("x.*", good.append)
    b.publish(Event(type="x.y", payload={}))
    assert len(good) == 1


# -- memory palace -------------------------------------------------------
def test_palace_dedup_search_merge():
    p = MemoryPalace()
    a = p.remember("deploy failed: DB migration timed out", tier="episodic",
                   room="Projects Room", importance=0.8)
    assert p.remember("deploy failed: DB migration timed out",
                      tier="episodic", room="Projects Room").id == a.id
    res = p.search("why did deploy fail", limit=3)
    assert res and "deploy" in res[0][0].content
    b = p.remember("Migration retried twice", tier="episodic", room="Projects Room")
    m = p.merge([a.id, b.id])
    assert p.get(a.id).archived and p.get(b.id).archived
    assert not p.get(m.id).archived


def test_palace_forget_archive_restore_expire_update():
    p = MemoryPalace()
    mid = p.remember("temp", tier="short_term").id
    assert p.forget(mid) and p.get(mid) is None
    aid = p.remember("old", tier="short_term").id
    assert p.archive(aid) and p.get(aid).archived
    assert p.restore(aid) and not p.get(aid).archived
    assert p.expire(aid) and p.get(aid).expired
    assert p.update(aid, importance=0.99).importance == 0.99
    assert p.temporal_search(0, 9999999999)
    assert p.stats()["total"] >= 1


def test_consolidation_dedups_and_promotes():
    p = MemoryPalace()
    for i in range(7):
        p.remember(f"Incident {i} caused by database connection pool exhaustion",
                   tier="episodic", room="Experiences", importance=0.5)
    p.remember("Server room temperature is high", tier="episodic",
               room="Observation Room", importance=0.85)
    r = MemoryConsolidator(p).run()
    assert r.reviewed == 8 and r.duplicates >= 1
    assert "Server room temperature is high" in r.facts_extracted
    assert summarize_text([]) == ""


# -- graph / world -------------------------------------------------------
def test_graph_traverse_paths_identity():
    g = KnowledgeGraph()
    for name, kind in (("user", "user"), ("jarvis-os", "project"), ("laptop", "device")):
        g.upsert_node(name, kind=kind)
    g.relate("user", "works_on", "jarvis-os", 0.9)
    g.relate("jarvis-os", "runs_on", "laptop", 0.8)
    assert g.stats() == {"nodes": 3, "edges": 2, "identities": 0}
    assert "jarvis-os" in g.traverse("user", 2)["hop1"]
    assert g.paths("user", "laptop") == [["user", "jarvis-os", "laptop"]]
    assert g.get_node("user").kind == "user", "relate() must not clobber node kinds"
    assert g.ensure_node("user").kind == "user"
    g.relate("user", "owns", "laptop", 0.7)
    assert g.paths("user", "laptop") == [["user", "laptop"]]
    assert g.get_node("laptop").kind == "device"
    iid = g.register_identity("person", "Darren", ["daz"], 0.9)
    assert g.resolve_identity("DAZ")["id"] == iid
    assert "Darren" in extract_entities("Darren deployed jarvis-os")


def test_world_gaps_and_rooms():
    w = WorldModel()
    w.record_event("b", timestamp=2000)
    w.record_event("a", timestamp=1000)
    assert any(x["kind"] == "impossible_sequence" for x in w.timeline_gaps())
    assert [e.description for e in w.timeline()] == ["a", "b"]
    w.record_room("office", {"chair": "left"})
    w.record_room("office", {"chair": "center", "book": "desk"})
    d = w.room_diff("office")
    assert d["moved"] == ["chair"] and d["added"] == ["book"]
    assert w.system_state()["disk"]["percent_used"] >= 0
    assert w.filesystem_state("/nonexistent-xyz")["exists"] is False


def test_world_snapshot_preserves_arrival_order():
    w = WorldModel()
    for i in range(120):
        w.record_event(f"e{i}", timestamp=1000 + i)
    w.record_event("late", timestamp=1050)
    w2 = WorldModel()
    w2.restore(w.snapshot())
    assert any(x["kind"] == "impossible_sequence" for x in w2.timeline_gaps())


# -- inference -----------------------------------------------------------
def test_evidence_conflicts_and_separation():
    e = EvidenceEngine()
    e.collect("wet floor", "sensor", reliability=0.9)
    ev = e.collect("floor near sink is wet", "direct_measurement", reliability=0.95)
    e.link(ev.evidence_id, supports="spill")
    ev2 = e.collect("mop used earlier", "user_stated", reliability=0.6)
    e.link(ev2.evidence_id, contradicts="spill")
    assert e.stats()["conflicts"] == 1
    facts, interp = e.separated()
    assert len(facts) == 2 and len(interp) == 1
    assert e.missing_evidence(["spill", "x"]) == ["x"]


def test_hypothesis_no_recursion_and_normalizes():
    h = HypothesisEngine(limit=3)
    a = h.propose("spill", 0.4)
    h.propose("mopped", 0.3)
    h.propose("condensation", 0.2)
    h.propose("leak", 0.25)
    assert len(h.active) == 3 and a.hypothesis_id not in h.active
    ka = list(h.active)[0]
    h.support(ka, "floor near sink", 0.2)
    r = h.bayesian_update([("floor near sink", 2.0)])
    assert abs(sum(x.probability for x in r.ranked()) - 1.0) < 1e-6
    assert r.distinguishing_evidence
    lab = HypothesisLab(h)
    assert lab.reality_check("always crashes")["verdict"] == "unsupported"
    assert lab.reality_check("latency rose")["verdict"] == "acceptable"


def test_contradiction_and_timeline():
    det = ContradictionDetector()
    ctr = det.detect(Claim("u", "deploy at 10:05"), Claim("u", "deploy did not happen at 10:05"))
    assert ctr and ctr.kind == "direct" and "honesty" in det.report(ctr)
    num = det.detect(Claim("u", "deploy took 5 minutes"), Claim("u", "deploy took 9 minutes"))
    assert num and num.kind == "numerical"
    assert det.detect(Claim("u", "all good"), Claim("u", "all good")) is None
    t = Timeline()
    t.add("deploy", 1000, "log")
    assert "deploy" in t.render() and len(t.window(999, 1001)) == 1
    g = InformationGapDetector()
    an = g.analyze("cause", ["logs"], ["logs", "db"], {"db": 0.9})
    assert an["high_impact_unknowns"] == ["db"]
    assert QuestionStrategy().generate("diagnose", ["db"], ["logs"])["best_question"]
    assert "person is lying" in deception_guard()["prohibited_claims"]
    assert safe_deception_analysis(0.9, 0.9, [])["findings"] == []


def test_reasoners():
    d = DeductiveReasoner().deduce("the object is wet", ["indoor location", "near kitchen sink"])
    assert d.remaining
    assert DeductiveReasoner().deduce("something odd", []).remaining == []
    i = InductiveReasoner().induce(["morning standup at 9", "morning deploys take 5 min"])
    assert i.sample_size == 2
    ab = AbductiveReasoner().best_explanation(["floor near sink wet"], ["spill", "rain"])
    assert ab.best and ab.alternatives_retained
    rt = RedTeamReasoner().review("spill", Confidence.HIGH, ["one item"], ["cleaning"])
    assert rt.weak_assumptions
    assert MetaReasoner().audit("obviously correct", Confidence.HIGH, ["a", "b", "c", "d"])[
        "detected_biases"
    ]
