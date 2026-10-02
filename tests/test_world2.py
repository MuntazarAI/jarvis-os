"""World Model 2.0: snapshots, diffs, temporal, expectations, predictions."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.memory.graph import KnowledgeGraph  # noqa: E402
from jarvis.memory.palace import MemoryPalace  # noqa: E402
from jarvis.world.model import WorldModel  # noqa: E402
from jarvis.world.state import (  # noqa: E402
    UNKNOWN,
    CausalLink,
    ExpectationBoard,
    Prediction,
    PredictionBoard,
    StateChange,
    StateSnapshot,
    StateTracker,
    WorldQuery,
    candidate_correlations,
    compare_snapshots,
    commit_change,
    commit_prediction,
    commit_snapshot,
    describe_relative,
    in_window,
    linear_trend,
    link_world_entity,
)


def _snap(domains, ts=1000.0):
    return StateSnapshot(timestamp=ts, domains=domains)


def test_snapshot_roundtrip_and_hash():
    snap = _snap({"apps": ["a", "b"], "resources": {"x": 1}})
    clone = StateSnapshot.from_dict(snap.to_dict())
    assert clone.content_hash() == snap.content_hash()
    assert clone.snapshot_id == snap.snapshot_id


def test_change_kinds_validated():
    change = StateChange(entity="application:firefox", field="presence",
                         old=None, new="present", kind="opened",
                         timestamp=1001.0)
    assert change.describe() == "application:firefox opened"
    try:
        StateChange(entity="x", field="y", old=1, new=2, kind="exploded")
        raise AssertionError("bad kind must fail")
    except ValueError:
        pass
    assert StateChange.from_dict(change.to_dict()).kind == "opened"


def test_apps_opened_closed():
    changes = compare_snapshots(_snap({"apps": ["a"]}, 1.0),
                                _snap({"apps": ["a", "b"]}, 2.0))
    assert [(c.entity, c.kind) for c in changes] == [("application:b", "opened")]
    changes = compare_snapshots(_snap({"apps": ["a", "b"]}, 1.0),
                                _snap({"apps": ["b"]}, 2.0))
    assert [(c.entity, c.kind) for c in changes] == [("application:a", "closed")]


def test_network_files_rooms_changes():
    changes = compare_snapshots(
        _snap({"network": {"addresses": ["1.1.1.1"]}}, 1.0),
        _snap({"network": {"addresses": ["1.1.1.1", "2.2.2.2"]}}, 2.0))
    assert [(c.entity, c.kind) for c in changes] == [("address:2.2.2.2", "connected")]
    old_files = {"entries": [{"name": "a", "size": 1, "modified": 1.0}]}
    new_files = {"entries": [{"name": "a", "size": 2, "modified": 2.0},
                             {"name": "b", "size": 1, "modified": 2.0}]}
    changes = compare_snapshots(_snap({"files": old_files}, 1.0),
                                _snap({"files": new_files}, 2.0))
    kinds = sorted((c.entity, c.kind) for c in changes)
    assert kinds == [("file:a", "modified"), ("file:b", "created")]
    changes = compare_snapshots(_snap({"rooms": {"desk": {"objects": {"mug": "left"}}}}, 1.0),
                                _snap({"rooms": {"desk": {"objects": {"mug": "right"}}}}, 2.0))
    assert changes[0].kind == "moved"


def test_resources_threshold_and_unknown():
    base = {"disk": {"percent_used": 50.0, "free": 100, "available_mb": 50},
            "memory": {"percent_used": 40.0}}
    same = compare_snapshots(_snap({"resources": base}, 1.0),
                             _snap({"resources": dict(base)}, 2.0))
    assert same == []
    drifted = dict(base, disk={"percent_used": 70.0, "free": 60, "available_mb": 30})
    changes = compare_snapshots(_snap({"resources": base}, 1.0),
                                _snap({"resources": drifted}, 2.0))
    assert changes and all(c.kind == "changed" for c in changes)
    # Unknown on either side: no change emitted, never a negative fact.
    assert compare_snapshots(_snap({"apps": UNKNOWN}, 1.0),
                             _snap({"apps": ["a"]}, 2.0)) == []
    assert compare_snapshots(_snap({"apps": ["a"]}, 1.0),
                             _snap({"apps": {"__unknown__": "no sensor"}}, 2.0)) == []


def test_tracker_history_changes_persistence(tmp_path):
    tracker = StateTracker(max_history=3)
    tracker._ingest(_snap({"apps": ["a"]}, 1.0))
    tracker._ingest(_snap({"apps": ["a", "b"]}, 2.0))
    assert tracker.latest().timestamp == 2.0
    assert tracker.previous().timestamp == 1.0
    assert [c.entity for c in tracker.latest_changes()] == ["application:b"]
    assert len(tracker.changes_since(1.5)) == 1
    path = tracker.save(tmp_path / "state.json")
    fresh = StateTracker()
    assert fresh.load(path) == 2
    assert fresh.latest().timestamp == 2.0
    assert fresh.latest_changes()[0].kind == "opened"
    for i in range(5):
        tracker._ingest(_snap({"apps": ["a"]}, 10.0 + i))
    assert len(tracker.history) == 3  # bounded


def test_temporal_helpers():
    assert describe_relative(90.0, ref=100.0) == "10s ago"
    assert describe_relative(40.0, ref=100.0) == "1m ago"
    assert describe_relative(100.0 - 7200, ref=100.0) == "2h ago"
    assert describe_relative(160.0, ref=100.0).startswith("in ")
    assert in_window(5.0, 1.0, 9.0) and not in_window(10.0, 1.0, 9.0)


def test_expectation_lifecycle():
    board = ExpectationBoard()
    board.expect("ff-open", "application:firefox", True,
                 basis="user said so", ttl=100.0)
    assert board.check_all({"application:firefox": True}) == []
    violations = board.check_all({"application:firefox": False})
    assert violations[0]["status"] == "violated"
    assert violations[0]["basis"] == "user said so"
    # Missing entity: unknown, never a violation.
    assert board.check_all({})[0]["status"] == "unknown"
    assert board.check_all({"other": 1})[0]["status"] == "unknown"
    board.expect("short", "x", True, ttl=-1.0)
    assert board.prune_expired() == 1
    assert len(board.pending()) == 1
    restored = ExpectationBoard()
    restored.restore(board.to_dict())
    assert len(restored.pending()) == 1


def test_prediction_lifecycle_and_trend():
    board = PredictionBoard()
    try:
        board.predict("disk will fill", basis=[])
        raise AssertionError("baseless prediction must fail")
    except ValueError:
        pass
    pred = board.predict("disk fills soon",
                         basis=["disk grew 5% in 1h", "trend slope positive"],
                         confidence=0.6, ttl=3600.0)
    assert pred.status == "unverified"
    assert board.due()[0].text == "disk fills soon"
    pred.verify(True)
    assert pred.status == "verified" and board.due() == []
    assert linear_trend([(0.0, 50.0), (3600.0, 55.0)])["rate_per_second"] > 0
    assert linear_trend([(0.0, 1.0)]) is None
    assert linear_trend([]) is None
    stale = PredictionBoard()
    old = stale.predict("x", basis=["y"], ttl=-1.0)
    assert old.refresh().status == "expired"


def test_causality_labels_candidates():
    link = CausalLink(cause="deploy", effect="latency spike",
                      evidence=["latency rose after deploy"])
    assert link.is_candidate and not link.verified
    assert link.to_dict()["is_candidate"] is True
    link.verify(mechanism="migration locked tables", confidence=0.8)
    assert link.verified and link.mechanism
    cands = candidate_correlations([(1.0, "deploy")], [(30.0, "spike")])
    assert cands[0]["warning"].startswith("correlation only")
    assert candidate_correlations([(50.0, "a")], [(10.0, "b")]) == []


def test_memory_integration_preserves_origin():
    palace = MemoryPalace()
    snap = _snap({"apps": ["a"]})
    mem = commit_snapshot(snap, palace)
    assert mem.origin == "observed" or "observed" in mem.metadata.get("origin", "observed")
    change = StateChange(entity="application:b", field="presence", old=None,
                         new="present", kind="opened", timestamp=2.0)
    mem2 = commit_change(change, palace)
    assert mem2.tier == "observation"
    pred = Prediction(text="x fills", basis=["grew 5%"], confidence=0.6)
    mem3 = commit_prediction(pred, palace)
    assert mem3.tier == "hypothesis"  # predictions are hypotheses, never facts


def test_graph_integration():
    graph = KnowledgeGraph()
    edge = link_world_entity(graph, "application:firefox", "Firefox")
    assert edge.rel == "observed_as"
    assert ("Firefox", "observed_as", edge.confidence) in [
        (dst, rel, conf) for dst, rel, conf in graph.neighbors("application:firefox")]


def test_live_capture_and_loop_integration(tmp_path):
    from jarvis.core.loop import Jarvis
    model = WorldModel()
    tracker = StateTracker()
    snap = tracker.capture(model, source="test")
    assert "resources" in snap.domains and "apps" in snap.domains
    assert snap.confidence > 0
    jarvis = Jarvis(home=str(tmp_path))
    try:
        assert hasattr(jarvis, "state")
        assert isinstance(jarvis.state, StateTracker)
        jarvis.cycle_once("hello")
        assert jarvis.state.latest() is not None
        assert jarvis.state.latest().source.startswith("cycle-")
    finally:
        jarvis.close()
