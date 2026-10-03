"""4.1 tests: neural scale substrate, topology, codec, intelligence loop."""

import pytest

from jarvis.neural.scale import SparseLIFNetwork
from jarvis.neural.topology import (
    ConnectomeSchema,
    FLY_166K_SCHEMA,
    PopulationSpec,
    ProjectionSpec,
    SyntheticGenerator,
    validate_edges,
)
from jarvis.neural.codec import (
    ChannelMap,
    MotorDecoder,
    SensoryEncoder,
    VisualPreprocessor,
    default_sensor_features,
)
from jarvis.neural.interface import MotorIntent, ALLOWED_MOTOR_ACTIONS
from jarvis.intelligence import (
    IntelligenceLoop,
    LoopState,
    SensoryBus,
    SensoryEvent,
    capture,
    compare,
    replay,
)
from jarvis.intelligence import wiring
from jarvis.planning.planner import MissionPlanner


# -- sparse network ------------------------------------------------------

def test_sparse_chain_matches_delay_semantics():
    net = SparseLIFNetwork(3)
    net.stage_edge(0, 1, 1.5, 0)
    net.stage_edge(1, 2, 1.5, 0)
    net.compile()
    assert net.step({0: 1.5}) == [0]
    assert net.step() == [1]
    assert net.step() == [2]


def test_sparse_delay_two_arrives_later():
    net = SparseLIFNetwork(2)
    net.stage_edge(0, 1, 2.0, 2)
    net.compile()
    assert net.step({0: 2.0}) == [0]
    assert net.step() == []
    assert net.step() == [1]


def test_sparse_rejects_bad_edges():
    net = SparseLIFNetwork(2)
    with pytest.raises(IndexError):
        net.stage_edge(0, 5, 1.0)
    with pytest.raises(ValueError):
        net.stage_edge(0, 1, float("nan"))


def test_sparse_snapshot_restore_roundtrip():
    net = SparseLIFNetwork(3)
    net.stage_edge(0, 1, 1.5)
    net.stage_edge(1, 2, 1.5)
    net.compile()
    net.step({0: 1.5})
    snap = net.snapshot()
    assert snap["time"] == 1
    live = net.step()
    net.restore(snap)
    assert net.step() == live
    assert net.time == 2


def test_sparse_determinism_same_seed_same_spikes():
    def build():
        n = SparseLIFNetwork(20)
        import random
        rng = random.Random(7)
        for _ in range(60):
            n.stage_edge(rng.randrange(20), rng.randrange(20),
                       rng.uniform(0.2, 1.0), rng.randrange(3))
        n.compile()
        return n
    a, b = build(), build()
    out_a = [a.step({0: 2.0, 5: 2.0}) for _ in range(5)]
    out_b = [b.step({0: 2.0, 5: 2.0}) for _ in range(5)]
    assert out_a == out_b


# -- topology ------------------------------------------------------------

def test_fly_schema_totals_166k_and_validates():
    assert FLY_166K_SCHEMA.total_neurons() == 166000
    assert FLY_166K_SCHEMA.origin == "synthetic"
    assert FLY_166K_SCHEMA.validate() == []


def test_synthetic_generator_tagged_sorted_and_deterministic():
    schema = ConnectomeSchema(
        name="tiny", origin="synthetic",
        populations=[PopulationSpec("a", 10), PopulationSpec("b", 5)],
        projections=[ProjectionSpec("a", "b", fan_out=2, weight_low=0.1,
                                     weight_high=0.5, delay_min=1, delay_max=1)],
    )
    gen = SyntheticGenerator(seed=3)
    edges = gen.generate(schema)
    assert len(edges) > 0
    # sorted output, valid 4-tuples, all inside network bounds
    assert edges == sorted(edges)
    assert all(isinstance(e, tuple) and len(e) == 4 for e in edges)
    assert validate_edges(15, edges, 32) == []
    # weights/delays honor the projection spec
    assert all(0.1 <= w <= 0.5 and d == 1 for _, _, w, d in edges)
    # same seed -> identical edges (deterministic)
    assert SyntheticGenerator(seed=3).generate(schema) == edges
    # different seed -> different edges (seed actually matters)
    assert SyntheticGenerator(seed=4).generate(schema) != edges


def test_validate_edges_rejects_bad_edges():
    good = [(0, 1, 0.5, 1), (1, 2, -0.2, 0)]
    assert validate_edges(3, good, 32) == []
    assert validate_edges(3, [(0, 9, 0.5, 1)], 32) != []      # bad target
    assert validate_edges(3, [(9, 0, 0.5, 1)], 32) != []      # bad source
    assert validate_edges(3, [(0, 1, float("nan"), 1)], 32) != []  # NaN
    assert validate_edges(3, [(0, 1, 0.5, 99)], 32) != []     # bad delay
    assert validate_edges(3, [(0, 1, 0.5, 1), (0, 1, 0.3, 2)], 32) != []  # duplicate


def test_schema_json_roundtrip(tmp_path):
    import json
    from jarvis.neural.topology import load_schema
    path = tmp_path / "schema.json"
    path.write_text(json.dumps(FLY_166K_SCHEMA.to_dict(), sort_keys=True))
    loaded = load_schema(str(path))
    assert loaded.total_neurons() == 166000
    assert loaded.origin == "synthetic"


# -- codec ---------------------------------------------------------------

def test_encoder_ignores_unknown_features():
    cmap = ChannelMap(["a", "b"])
    enc = SensoryEncoder(cmap)
    currents = enc.encode({"a": 0.5, "zzz": 9.0})
    assert list(currents.keys()) == [0]
    assert 0.0 < currents[0] <= 1.2


def test_visual_preprocessor_bounded():
    proc = VisualPreprocessor(regions=4)
    feats = proc.process([0.0, 0.5, 1.0, 0.75] * 10)
    assert len(feats) == 4
    assert all(0.0 <= v <= 1.0 for v in feats.values())
    assert proc.process([]) == {}


def test_visual_preprocessor_no_sample_dropped():
    # every sample contributes to exactly one region: the weighted mean of
    # region means must equal the overall mean
    import random
    rng = random.Random(11)
    for n, regions in [(1, 4), (2, 4), (3, 4), (4, 4), (7, 4), (10, 4),
                       (100, 16), (1000, 16), (17, 16)]:
        samples = [rng.random() for _ in range(n)]
        feats = VisualPreprocessor(regions=regions).process(samples)
        assert 1 <= len(feats) <= min(regions, n)
        overall = sum(samples) / n
        # reconstruct: region sizes are deterministic (first `extra` get +1)
        sizes = []
        base, extra = divmod(n, len(feats))
        for r in range(len(feats)):
            sizes.append(base + (1 if r < extra else 0))
        rebuilt = sum(feats[f"visual_region_{r:02d}"] * s
                      for r, s in enumerate(sizes)) / n
        assert abs(rebuilt - overall) < 1e-9


def test_visual_preprocessor_clamps_and_bounds():
    feats = VisualPreprocessor(regions=4).process([-5.0, 99.0, 0.5, 0.5])
    assert all(0.0 <= v <= 1.0 for v in feats.values())
    assert len(feats) == 4


def test_motor_decoder_allowlist_enforced():
    with pytest.raises(ValueError):
        MotorDecoder({0: ("rm -rf", 1.0)})
    dec = MotorDecoder({0: ("ATTEND", 0.9)})
    intents = dec.decode([0, 5], tick=4)
    assert len(intents) == 1
    assert isinstance(intents[0], MotorIntent)
    assert intents[0].action == "ATTEND"


def test_default_features_stable():
    feats = default_sensor_features()
    assert len(feats) == 24
    assert feats[0] == "visual_region_00"


# -- intelligence loop ---------------------------------------------------

def test_loop_runs_bounded_passthrough_cycle():
    loop = IntelligenceLoop()
    loop.start()
    records = loop.run([{"text": "hello"}, {"text": "again"}], max_cycles=5)
    assert len(records) == 2
    assert all(r.ok for r in records)
    assert loop.state is LoopState.PAUSED
    assert loop.total_cycles == 2


def test_loop_policy_fail_closed_no_executor_call():
    calls: list = []
    loop = IntelligenceLoop(
        plan=lambda ctx: {"action": "filesystem_read", "args": {}},
        executor=lambda a, args: calls.append(a) or {"ok": True},
    )
    loop.start()
    record = loop.cycle_once({"text": "read stuff"})
    assert record.ok
    assert record.policy_allowed is False
    assert calls == []
    assert record.action_taken == "filesystem_read"


def test_loop_stage_failure_isolated():
    def boom(normalized):
        raise RuntimeError("world exploded")
    loop = IntelligenceLoop(world_update=boom)
    loop.start()
    record = loop.cycle_once({"text": "x"})
    assert not record.ok
    assert record.failed_stage == "world"
    assert loop.total_failures == 1


def test_loop_lifecycle_pause_resume_stop():
    loop = IntelligenceLoop()
    assert loop.state is LoopState.START
    loop.start()
    loop.pause()
    assert loop.run([1, 2, 3]) == []
    loop.resume()
    assert len(loop.run([1])) == 1
    loop.stop()
    assert loop.state is LoopState.STOPPED


def test_snapshot_replay_never_executes():
    calls: list = []
    loop = IntelligenceLoop(
        plan=lambda ctx: {"action": "do_thing", "args": {}},
        policy_check=lambda a, args: (True, "test allow"),
        executor=lambda a, args: calls.append(a) or {"ok": True},
    )
    loop.start()
    record = loop.cycle_once({"text": "go"})
    assert calls == ["do_thing"]
    snap = capture(record, {"text": "go"})
    assert snap.snapshot_id.startswith("snap-")
    replayed = replay(snap, loop)
    assert calls == ["do_thing"]  # replay added no new executions
    assert replayed.ok
    result = compare(record, replayed)
    assert result["match"]


def test_sensory_bus_types_and_bounds():
    bus = SensoryBus()
    seen: list = []
    bus.subscribe("user", seen.append)
    event = SensoryEvent(source="user", type="user", payload={"text": "hi"})
    assert bus.publish(event) == 1
    assert seen == [event]
    with pytest.raises(ValueError):
        SensoryEvent(source="x", type="nope")
    with pytest.raises(ValueError):
        SensoryEvent(source="x", type="user", payload={"blob": "x" * 5000})


def test_planner_rules_and_observe_only_default():
    planner = MissionPlanner()
    planner.register("battery", "device.get_battery")
    hit = planner.plan({"conclusion": {"summary": "battery low"}})
    assert hit["action"] == "device.get_battery"
    miss = planner.plan({"conclusion": {"summary": "all calm"}})
    assert miss["action"] == ""


def test_wiring_build_loop_with_real_policy_deny():
    from jarvis.policy.policy import PolicyEngine
    loop = wiring.build_loop(policy=PolicyEngine())
    loop.start()
    record = loop.cycle_once({"text": "test"})
    assert record.ok  # no action proposed -> observe-only, no denial failure


def test_wiring_neural_hook_with_sparse_net():
    net = SparseLIFNetwork(4)
    net.stage_edge(0, 2, 2.0)
    net.compile()
    cmap = ChannelMap(["novelty", "urgency"])
    hook = wiring.make_neural_hook(net, SensoryEncoder(cmap))
    out = hook({"payload": {"text": "urgent alert"}})
    assert "fired" in out and "tick" in out


def test_wired_loop_executes_every_stage():
    executed: list[str] = []

    def tracking(stage_name):
        def hook(*args, **kwargs):
            executed.append(stage_name)
            return {}
        return hook

    loop = IntelligenceLoop(
        normalize=lambda e: (executed.append("normalize"), {"text": "hi"})[1],
        world_update=tracking("world"),
        recall=lambda n: (executed.append("recall"), [])[1],
        neural_step=tracking("neural"),
        reason=lambda ctx: (executed.append("reason"), {"summary": "s"})[1],
        plan=lambda ctx: (executed.append("plan"), {"action": "do_thing", "args": {}})[1],
        policy_check=lambda a, args: (executed.append("policy"), (False, "test"))[1],
        executor=lambda a, args: (executed.append("act"), {"ok": True})[1],
        observe=tracking("observe"),
        learn=tracking("learn"),
    )
    loop.start()
    record = loop.cycle_once({"text": "hi"})
    assert record.ok
    for stage in ("normalize", "world", "recall", "neural", "reason",
                  "plan", "policy", "observe", "learn"):
        assert stage in executed, f"stage did not execute: {stage}"
    assert "act" not in executed  # policy denied -> executor never runs


def test_full_stack_wiring_uses_neural_and_meta_reasoner():
    from jarvis.inference.reasoning import MetaReasoner
    network, encoder, decoder = wiring.default_neural_stack(seed=9)
    loop = wiring.build_loop(network=network, encoder=encoder,
                             decoder=decoder, reasoner=MetaReasoner())
    loop.start()
    record = loop.cycle_once({"payload": {"text": "definitely urgent"}})
    stages = {s.stage: s for s in record.stages}
    assert record.ok
    assert stages["neural"].ok and stages["neural"].detail.get("signals") is not None
    assert stages["reason"].detail["concluded"] is True
    assert stages["reason"].detail["summary"] == "definitely urgent"
    reason_stage = next(s for s in record.stages if s.stage == "reason")
    assert reason_stage.ok


def test_meta_reasoner_adapter_returns_structured_conclusion():
    """The CLI path must use MetaReasoner, not the passthrough fallback."""
    from jarvis.inference.reasoning import MetaReasoner
    adapter = wiring.make_meta_reasoner_adapter(MetaReasoner())
    # "definitely" is a MetaReasoner overconfidence marker.
    conclusion = adapter({"normalized": {"payload": {"text": "definitely urgent"}},
                         "neural": {"fired": 9}, "memories": [{"id": "m1"}]})
    assert conclusion["mode"] == "meta-audit"
    assert conclusion["spikes"] == 9
    assert conclusion["memory_count"] == 1
    assert any("overconfidence" in b for b in conclusion["biases"]), conclusion["biases"]

    # No reasoner bound -> honest passthrough marker, never a fake audit.
    plain = wiring.make_meta_reasoner_adapter(None)(
        {"normalized": {"payload": {"text": "hi"}}})
    assert plain["mode"] == "passthrough"


# -- P1: timeout contract ------------------------------------------------

def test_timeout_slow_stage_enters_timeout_state():
    import time

    def slow(normalized):
        time.sleep(0.05)
        return {}

    loop = IntelligenceLoop(world_update=slow)
    loop.start()
    record = loop.cycle_once({"text": "slow"}, timeout_s=0.01)
    assert not record.ok
    assert record.failed_stage.startswith("timeout:")
    from jarvis.intelligence import LoopState
    assert loop.state is LoopState.TIMEOUT
    assert loop.status()["total_timeouts"] == 1


def test_timeout_success_within_budget():
    loop = IntelligenceLoop()
    loop.start()
    record = loop.cycle_once({"text": "fast"}, timeout_s=5.0)
    assert record.ok
    from jarvis.intelligence import LoopState
    assert loop.state is not LoopState.TIMEOUT


def test_timeout_across_multiple_events_bounded():
    import time

    def slow(normalized):
        time.sleep(0.05)
        return {}

    loop = IntelligenceLoop(world_update=slow)
    records = loop.run([{"t": 1}, {"t": 2}, {"t": 3}], max_cycles=3, timeout_s=0.01)
    assert len(records) == 1  # loop stops at first timeout
    assert records[0].failed_stage.startswith("timeout:")
    assert all(s.detail.get("timeout") is True for s in records[0].stages if not s.ok)


def test_timeout_uses_monotonic_clock():
    import jarvis.intelligence.loop as loop_mod
    assert "monotonic" in open(loop_mod.__file__).read()


# -- P2: dry-run side-effect freedom -------------------------------------

def _dirty_world_spatial_memory():
    from jarvis.world.registry import WorldRegistry
    from jarvis.memory.palace import MemoryPalace
    registry = WorldRegistry()
    return registry, MemoryPalace(path=":memory:")


def test_replay_leaves_world_memory_policy_untouched():
    from jarvis.policy.policy import PolicyEngine
    registry, palace = _dirty_world_spatial_memory()
    policy = PolicyEngine()
    audit_before = len(policy.audit)
    approvals_before = len(policy.approvals)
    memories_before = len(palace.all(limit=1000))
    entities_before = len(registry.entities)

    loop = wiring.build_loop(registry=registry, palace=palace, policy=policy)
    loop.start()
    record = loop.cycle_once({"payload": {"text": "record this event"}})
    live_entities = len(registry.entities)
    live_memories = len(palace.all(limit=1000))
    audit_after_live = len(policy.audit)
    assert live_entities >= entities_before  # live run may record
    assert live_memories >= memories_before  # live run may record

    snap = capture(record, {"payload": {"text": "record this event"}})
    replayed = replay(snap, loop)
    assert replayed.ok
    # dry-run must not add anything beyond the live run
    assert len(registry.entities) == live_entities
    assert len(palace.all(limit=1000)) == live_memories
    assert len(policy.audit) == audit_after_live
    assert len(policy.approvals) == approvals_before
    assert len(palace.all(limit=1000)) == live_memories
    assert len(registry.entities) == live_entities


def test_replay_executor_never_called_with_side_effects():
    calls: list = []
    loop = IntelligenceLoop(
        plan=lambda ctx: {"action": "do_thing", "args": {}},
        policy_check=lambda a, args: (True, "allow"),
        executor=lambda a, args: calls.append((a, dict(args))) or {"ok": True},
    )
    loop.start()
    record = loop.cycle_once({"x": 1})
    assert len(calls) == 1
    snap = capture(record, {"x": 1})
    for _ in range(3):
        replay(snap, loop)
    assert len(calls) == 1  # replays added zero executions


def test_dry_run_loop_rejects_executor():
    import pytest as _pytest
    from jarvis.intelligence import IntelligenceLoop as IL
    with _pytest.raises(ValueError):
        IL(dry_run=True, executor=lambda a, args: {})
    sb = IL(dry_run=True).sandbox()
    assert sb.executor is None and sb.dry_run is True


# -- P4: snapshot contract ------------------------------------------------

def test_snapshot_full_and_diagnostic_modes():
    from jarvis.neural.scale import SnapshotError
    net = SparseLIFNetwork(6)
    net.stage_edge(0, 1, 1.5)
    net.compile()
    full = net.snapshot(mode="full")
    assert "weights" in full and full["mode"] == "full"
    diag = net.snapshot(mode="diagnostic")
    assert "weights" not in diag and "weights_digest" in diag
    net.restore(full, exact=True)
    try:
        net.restore(diag, exact=True)
    except SnapshotError:
        pass
    else:
        raise AssertionError("diagnostic restore with exact=True must fail")


def test_snapshot_stdp_homeostasis_continuation_identical():
    from jarvis.neural.plasticity import HomeostaticPlasticity, STDPRule
    def build():
        n = SparseLIFNetwork(8)
        n.stdp = STDPRule()
        n.homeostasis = HomeostaticPlasticity()
        n.stage_edge(0, 1, 1.0)
        n.stage_edge(1, 2, 1.0)
        n.compile()
        return n
    a, b = build(), build()
    for _ in range(3):
        a.step({0: 2.0})
    snap = a.snapshot(mode="full")
    b.restore(snap, exact=True)
    future_a = [a.step({0: 2.0}) for _ in range(4)]
    future_b = [b.step({0: 2.0}) for _ in range(4)]
    assert future_a == future_b


def test_snapshot_rejects_malformed_and_mismatch():
    from jarvis.neural.scale import SnapshotError
    net = SparseLIFNetwork(4)
    net.stage_edge(0, 1, 1.0)
    net.compile()
    for bad in ({}, {"version": 999}, {"version": 1},
                {"version": 1, "size": 999, "topology_digest": net.snapshot()["topology_digest"],
                 "edge_count": 1, "potentials": [], "thresholds": [], "leaks": [],
                 "refractory_left": [], "refractory_steps": [], "spike_counts": [],
                 "last_spike": [], "time": 0, "total_spikes": 0, "max_delay": 8,
                 "queue": [], "mode": "full", "weights": []}):
        try:
            net.restore(bad, exact=True)
        except SnapshotError:
            continue
        raise AssertionError(f"malformed snapshot accepted: {sorted(bad.keys())}")
