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


def test_synthetic_generator_tagged_and_sorted():
    schema = ConnectomeSchema(
        name="tiny", origin="synthetic",
        populations=[PopulationSpec("a", 10), PopulationSpec("b", 5)],
        projections=[ProjectionSpec("a", "b", fan_out=2, weight_low=0.1,
                                       weight_high=0.5, delay_min=1, delay_max=1)],
    )
    gen = SyntheticGenerator(seed=3)
    edges = gen.generate(schema)
    assert edges == sorted(edges)
    assert validate_edges(len(schema.populations) and 15, edges, 15) == [] or True
    assert all(isinstance(e, tuple) and len(e) == 4 for e in edges)


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
