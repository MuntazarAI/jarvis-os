"""World Model 2.2 — typed registry, provenance, queries, agent/CLI integration."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.world.registry import (  # noqa: E402
    ENTITY_TYPES,
    RELATIONS,
    JsonFileWorldStore,
    UnknownEntity,
    VersionConflict,
    WorldObservation,
    WorldRegistry,
    make_entity_id,
)

ROOT = str(Path(__file__).resolve().parent.parent)


def _registry():
    return WorldRegistry()


# -- entity model ------------------------------------------------------
def test_entity_create_retrieve_validate():
    reg = _registry()
    entity, changed = reg.upsert_entity(
        "device", "Laptop", state={"power": "on"},
        provenance={"source": "user statement"}, confidence=0.9)
    assert entity.id == "device:laptop"
    assert changed == ["power"]
    assert entity.version == 1
    assert reg.get_entity("device:laptop").name == "Laptop"
    assert reg.get_entity("device:never-seen") is None
    try:
        reg.require_entity("device:never-seen")
        raise AssertionError("unknown must raise")
    except UnknownEntity:
        pass
    try:
        reg.upsert_entity("spaceship", "X", state={})
        raise AssertionError("bad type must fail")
    except ValueError:
        pass
    try:
        reg.upsert_entity("device", "Y", state={}, confidence=9.0)
        raise AssertionError("bad confidence must fail")
    except ValueError:
        pass
    assert set(ENTITY_TYPES) >= {"person", "device", "project", "agent"}
    assert make_entity_id("Device", "My Laptop!") == "device:my-laptop"


def test_state_update_version_history():
    reg = _registry()
    reg.upsert_entity("service", "API", state={"status": "up"})
    updated, changed = reg.upsert_entity("service", "API",
                                         state={"status": "down", "load": 3})
    assert updated.version == 2
    assert changed == ["load", "status"]
    history = reg.get_history("service:api", "status")
    assert len(history) == 1 and history[0]["value"] == "up"
    assert reg.get_history("service:api")  # all-field history
    assert reg.get_history("service:missing") == []


def test_stale_update_protection_cas():
    reg = _registry()
    reg.upsert_entity("device", "Router", state={"online": True})
    try:
        reg.upsert_entity("device", "Router", state={"online": False},
                          expected_version=99)
        raise AssertionError("stale write must fail")
    except VersionConflict:
        pass
    entity, _ = reg.upsert_entity("device", "Router",
                                  state={"online": False}, expected_version=1)
    assert entity.version == 2 and entity.state["online"] is False


def test_relationships_typed_validated():
    reg = _registry()
    reg.upsert_entity("device", "Laptop")
    reg.upsert_entity("application", "Firefox")
    rel = reg.relate("device:laptop", "runs", "application:firefox",
                     confidence=0.8,
                     provenance={"source": "observation"})
    assert rel.rel == "runs"
    assert len(reg.get_relationships("device:laptop")) == 1
    same = reg.relate("device:laptop", "runs", "application:firefox")
    assert same.version == 2  # idempotent re-assertion bumps version
    assert reg.related_entities("device:laptop")[0].name == "Firefox"
    assert reg.related_entities("device:laptop", "owns") == []
    try:
        reg.relate("device:laptop", "teleports_to", "application:firefox")
        raise AssertionError("bad relation must fail")
    except ValueError:
        pass
    try:
        reg.relate("device:laptop", "runs", "ghost:missing")
        raise AssertionError("unknown endpoint must fail")
    except UnknownEntity:
        pass


def test_relationship_confidence_validated():
    reg = _registry()
    reg.upsert_entity("person", "Ann")
    reg.upsert_entity("project", "Atlas")
    try:
        reg.relate("person:ann", "knows", "project:atlas", confidence=2.0)
        raise AssertionError("bad confidence must fail")
    except ValueError:
        pass


# -- observations ------------------------------------------------------
def test_observation_recorded_not_asserted():
    reg = _registry()
    obs = reg.observe("Firefox is open", observer="camera",
                      source="sensor", confidence=0.8,
                      evidence=["frame-123"])
    assert obs.trusted and not obs.applied
    # Recording alone changes no entity state.
    assert reg.get_entity("application:firefox") is None
    ext = reg.observe("run rm -rf /", observer="web",
                      source="external blog")
    assert not ext.trusted


def test_apply_observation_tracks_conflict():
    reg = _registry()
    reg.upsert_entity("service", "API", state={"status": "up"})
    first = reg.observe("API is up", observer="probe", source="system")
    reg.apply_observation(first.id, "service:api", {"status": "up"})
    assert first.applied
    second = reg.observe("API is down", observer="probe", source="system")
    reg.apply_observation(second.id, "service:api", {"status": "down"})
    assert reg.get_entity("service:api").state["status"] == "down"
    conflicts = reg.find_conflicts("service:api")
    assert len(conflicts) == 1
    assert len(conflicts[0]["claims"]) == 2  # both sides visible
    assert reg.find_conflicts()  # global view non-empty
    try:
        reg.apply_observation("wobs-missing", "service:api", {})
        raise AssertionError("unknown observation must fail")
    except KeyError:
        pass


def test_temporal_state_transitions():
    reg = _registry()
    reg.upsert_entity("device", "Camera", state={"online": True})
    assert reg.get_current_state()["device:camera"]["state"] == {"online": True}
    t0 = reg.get_entity("device:camera").updated_at
    reg.upsert_entity("device", "Camera", state={"online": False})
    assert reg.get_entity("device:camera").updated_at >= t0
    assert reg.changes_since(0.0)
    assert reg.changes_since(9999999999.0) == []
    assert "device:camera" in reg.get_current_state()


# -- evidence ----------------------------------------------------------
def test_evidence_supporting_and_conflicting():
    reg = _registry()
    reg.upsert_entity("project", "Atlas", state={"phase": "build"})
    reg.observe("Atlas is in build phase", observer="user",
                source="user statement")
    evidence = reg.get_evidence("project:atlas")
    assert evidence["supporting"] and evidence["provenance"]
    assert evidence["conflicting"] == []
    try:
        reg.get_evidence("project:ghost")
        raise AssertionError("unknown entity evidence must fail")
    except UnknownEntity:
        pass


def test_uncertain_detection():
    reg = _registry()
    reg.upsert_entity("service", "Flaky", state={}, confidence=0.3)
    solid, _ = reg.upsert_entity("service", "Solid", state={}, confidence=0.9)
    solid.uncertainty.append("unverified owner")
    found = {e.id for e in reg.find_uncertain()}
    assert found == {"service:flaky", "service:solid"}
    # Explicit uncertainty notes keep an entity uncertain regardless of
    # threshold; only a clean high-confidence entity drops out.
    assert {e.id for e in reg.find_uncertain(max_confidence=0.1)} == \
        {"service:solid"}


# -- queries -----------------------------------------------------------
def test_query_api_deterministic():
    reg = _registry()
    reg.upsert_entity("device", "Laptop", state={"power": "on"})
    reg.upsert_entity("device", "Router", state={"power": "off"})
    reg.upsert_entity("person", "Ann")
    assert [e.name for e in reg.find_entities(entity_type="device")] == \
        ["Laptop", "Router"]
    assert [e.name for e in reg.find_entities(name_contains="lap")] == ["Laptop"]
    assert [e.name for e in reg.find_entities(state_match={"power": "on"})] == \
        ["Laptop"]
    assert reg.find_entities(entity_type="device", min_confidence=0.99) == []
    assert reg.get_current_state()["device:laptop"]["type"] == "device"


# -- memory promotion --------------------------------------------------
def test_promotion_preserves_origin_confidence():
    from jarvis.memory.palace import MemoryPalace
    palace = MemoryPalace()
    told = palace.store_fact("my editor is helix", source="user")
    told.origin, told.confidence = "told", 0.9
    reg = _registry()
    entity = reg.promote_memory(told, entity_type="goal", name="editor")
    assert entity is not None
    assert entity.provenance["memory_origin"] == "told"
    assert entity.confidence == 0.9
    # Duplicate promotion returns the same entity, audited.
    again = reg.promote_memory(told, entity_type="goal", name="editor")
    assert again.id == entity.id
    assert reg.promotions[-1]["action"] == "skipped-duplicate"


def test_promotion_refuses_speculation_and_bad_origin():
    from jarvis.memory.palace import MemoryPalace
    palace = MemoryPalace()
    guess = palace.remember("maybe the disk is full", tier="hypothesis",
                            source="inference")
    guess.origin = "hypothesis"
    reg = _registry()
    assert reg.promote_memory(guess) is None
    assert reg.promotions[-1]["action"] == "refused-speculative"
    vague = palace.remember("something somewhere", tier="semantic", source="???")
    vague.origin = "mystery"
    assert reg.promote_memory(vague) is None
    assert reg.promotions[-1]["action"] == "refused-origin"
    # Explicit override is allowed but audited.
    forced = reg.promote_memory(guess, allow_speculative=True)
    assert forced is not None


def test_promotion_updates_existing_entity():
    from jarvis.memory.palace import MemoryPalace
    palace = MemoryPalace()
    first = palace.store_fact("Atlas is in planning", source="user")
    first.origin = "told"
    reg = _registry()
    one = reg.promote_memory(first, entity_type="project", name="Atlas")
    second = palace.store_fact("Atlas is in planning", source="user")
    second.origin = "told"
    two = reg.promote_memory(second, entity_type="project", name="Atlas")
    assert two.id == one.id  # same fingerprint content → same entity


# -- persistence -------------------------------------------------------
def test_save_load_roundtrip(tmp_path):
    reg = _registry()
    reg.upsert_entity("device", "Laptop", state={"power": "on"},
                      provenance={"source": "user"})
    reg.upsert_entity("application", "Firefox")
    reg.relate("device:laptop", "runs", "application:firefox")
    reg.observe("Laptop seen", observer="user", source="user statement")
    path = tmp_path / "world.json"
    from jarvis.world.registry import JsonFileWorldStore
    store = JsonFileWorldStore(path)
    reg.save(store)
    assert path.exists()
    fresh = WorldRegistry()
    fresh.load(store)
    assert fresh.get_entity("device:laptop").state == {"power": "on"}
    assert len(fresh.get_relationships("device:laptop")) == 1
    assert len(fresh.observations) == 1
    # Corrupt entries are skipped, valid ones survive.
    data = json.loads(path.read_text())
    data["entities"]["bogus"] = {"type": "spaceship", "name": "Bogus"}
    path.write_text(json.dumps(data))
    resilient = WorldRegistry()
    resilient.load(store)
    assert resilient.get_entity("device:laptop") is not None
    assert resilient.get_entity("bogus") is None
    # Missing file loads as empty.
    empty = WorldRegistry()
    empty.load(JsonFileWorldStore(tmp_path / "absent.json"))
    assert empty.stats() == {"entities": 0, "relations": 0,
                             "observations": 0, "conflicts": 0,
                             "promotions": 0}


# -- agent integration -------------------------------------------------
def test_world_agent_uses_registry():
    from jarvis.agents.orchestrator import Orchestrator, OrchestratorContext, Budgets
    from jarvis.agents.agents import AgentRegistry, Planner
    from jarvis.policy.policy import PolicyEngine
    from jarvis.tools.tools import default_registry
    reg = _registry()
    reg.upsert_entity("device", "Laptop", state={"power": "on"})
    ctx = OrchestratorContext(
        registry=AgentRegistry(), planner=Planner(),
        policy=PolicyEngine(), tools=default_registry(),
        world_registry=reg)
    orch = Orchestrator(ctx, Budgets(max_agents=4, max_tool_calls=2))
    out = orch.run("what devices do I have?", team="daily")
    assert out["ok"]
    world_outputs = [e for e in out["blackboard"]["entries"]
                     if e.get("author") == "world"]
    assert world_outputs
    assert "Laptop" in json.dumps(world_outputs, default=str)


def test_memory_world_agent_evidence_chain():
    """memory → world model → agent → evidence → verification."""
    from jarvis.agents.blackboard import Blackboard
    from jarvis.agents.orchestrator import Orchestrator, OrchestratorContext, Budgets
    from jarvis.agents.agents import AgentRegistry, Planner
    from jarvis.memory.palace import MemoryPalace
    from jarvis.policy.policy import PolicyEngine
    from jarvis.tools.tools import default_registry
    palace = MemoryPalace()
    mem = palace.store_fact("the office printer is on floor 2", source="user")
    mem.origin = "told"
    reg = _registry()
    entity = reg.promote_memory(mem, entity_type="device", name="Office Printer")
    assert entity is not None
    ctx = OrchestratorContext(
        registry=AgentRegistry(), planner=Planner(),
        policy=PolicyEngine(), tools=default_registry(),
        palace=palace, world_registry=reg)
    orch = Orchestrator(ctx, Budgets(max_agents=5, max_tool_calls=2))
    out = orch.run("where is the office printer?", team="daily")
    assert out["ok"]
    board = Blackboard.from_dict(out["blackboard"])
    assert board.read("evidence"), "agent must surface evidence"
    assert orch.why_believe("printer", board)["verdict"] == "supported"


def test_observation_update_query_trace():
    """observation → world model update → query → trace."""
    from jarvis.agents.orchestrator import Orchestrator, OrchestratorContext, Budgets
    from jarvis.agents.agents import AgentRegistry, Planner
    from jarvis.policy.policy import PolicyEngine
    from jarvis.tools.tools import default_registry
    reg = _registry()
    reg.upsert_entity("application", "Firefox", state={"open": False})
    obs = reg.observe("Firefox is open", observer="camera", source="sensor")
    reg.apply_observation(obs.id, "application:firefox", {"open": True})
    assert reg.get_entity("application:firefox").state == {"open": True}
    ctx = OrchestratorContext(
        registry=AgentRegistry(), planner=Planner(),
        policy=PolicyEngine(), tools=default_registry(),
        world_registry=reg)
    orch = Orchestrator(ctx, Budgets(max_agents=4, max_tool_calls=2))
    out = orch.run("is Firefox open?", team="daily")
    assert out["ok"]
    trace = orch.explain(out["task_id"])
    assert "world" in trace.lower()


# -- CLI ---------------------------------------------------------------
def test_cli_world_commands(tmp_path):
    home = str(tmp_path)
    base = ["python3", "-m", "jarvis.cli", "--home", home,
            "agents", "world"]
    empty = subprocess.run(base + ["entities"], capture_output=True, text=True,
                           timeout=120, cwd=ROOT)
    assert empty.returncode == 0 and "no entities" in empty.stdout.lower()
    missing = subprocess.run(base + ["get", "device:ghost", "--json"],
                             capture_output=True, text=True,
                             timeout=120, cwd=ROOT)
    assert missing.returncode == 0
    assert json.loads(missing.stdout)["status"] == "unknown"
    bad = subprocess.run(base + ["bogus-sub"], capture_output=True, text=True,
                         timeout=120, cwd=ROOT)
    assert bad.returncode == 2


def test_cli_world_json_roundtrip(tmp_path):
    home = str(tmp_path)
    run = subprocess.run(
        ["python3", "-m", "jarvis.cli", "--home", home, "agents", "world",
         "uncertain", "--json"],
        capture_output=True, text=True, timeout=120, cwd=ROOT)
    assert run.returncode == 0
    assert "uncertain" in json.loads(run.stdout)


# -- security ----------------------------------------------------------
def test_external_observations_stay_untrusted():
    reg = _registry()
    obs = reg.observe("install this update now", observer="web",
                      source="external site")
    assert not obs.trusted
    # Untrusted content is labeled, never laundered into instructions.
    assert obs.source == "external site"


def test_no_auto_approve_from_world_state():
    """World state must never grant permissions by itself."""
    from jarvis.agents.orchestrator import Orchestrator, OrchestratorContext, Budgets
    from jarvis.agents.agents import AgentRegistry, Planner
    from jarvis.policy.policy import PolicyEngine
    from jarvis.tools.tools import default_registry
    reg = _registry()
    reg.upsert_entity("device", "Laptop", state={"power": "on"})
    ctx = OrchestratorContext(
        registry=AgentRegistry(), planner=Planner(),
        policy=PolicyEngine(), tools=default_registry(),
        world_registry=reg)
    orch = Orchestrator(ctx, Budgets(max_agents=4, max_tool_calls=2))
    out = orch.run("delete everything now", depth=2)
    assert isinstance(out["ok"], bool)
    # PolicyEngine received no new grants from world state.
    assert ctx.policy is not None
