"""Agent reach views: permission map, health, registry/roster.

Deterministic and offline: real PolicyEngine/Orchestrator/DeviceFabric,
temporary homes, and synthetic OpenCode harness assets. No network.
"""

from __future__ import annotations

import json

from jarvis.agents.agents import AgentRegistry, Planner
from jarvis.agents.orchestrator import Orchestrator, OrchestratorContext
from jarvis.agents.reach import (
    build_reach,
    harness_inventory,
    permission_map,
    reach_summary,
    reachability_health,
    registry_roster,
)
from jarvis.core.config import JarvisConfig
from jarvis.device.authz import DeviceGrantStore
from jarvis.device.fabric import DeviceFabric
from jarvis.policy.policy import PolicyEngine
from jarvis.tools.tools import default_registry


def _policy(home):
    config = JarvisConfig()
    config.paths.home = home
    return PolicyEngine(config)


def _orchestrator(tmp_path, policy):
    ctx = OrchestratorContext(
        registry=AgentRegistry(), planner=Planner(), policy=policy,
        tools=default_registry(), home=str(tmp_path / "home"))
    return Orchestrator(ctx)


def _harness(tmp_path):
    root = tmp_path / ".opencode"
    skill = root / "skills" / "demo-skill" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "---\nname: Demo Skill\ndescription: test skill\n"
        "metadata:\n  origin: ECC\n---\n\nBody.\n")
    agent = root / "agents" / "demo-reviewer.md"
    agent.parent.mkdir(parents=True)
    agent.write_text(
        "---\ndescription: test subagent\nmode: subagent\n---\n\n"
        "Review only.\n")
    return root


def _online_device(tmp_path):
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    fabric = DeviceFabric(home)
    device = fabric.registry.register("Phone", "phone", node_id="n1")
    fabric.registry.set_trust(device.device_id, True, by="tester",
                              reason="test")
    fabric.registry.mark_online(device.device_id)
    fabric.registry.declare_capabilities(
        device.device_id, [])
    return fabric, device


def test_permission_map_shows_declared_and_granted(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    policy = _policy(home)
    orch = _orchestrator(tmp_path, policy)
    policy.grant("coder", "fs.read")
    policy.grant("coder", "fs.write")
    policy.grant("coder", "exec")
    policy.grant("coder", "exec.eval")

    reach = permission_map(orchestrator=orch, policy=policy,
                           tools=orch.ctx.tools)
    roles = {role["role_id"]: role for role in reach["roles"]}
    coder = {tool["name"]: tool for tool in roles["coder"]["tools"]}
    assert coder["filesystem_write"]["reachable"] is True
    assert coder["terminal_run"]["policy_granted"] is True
    # The tester declares test execution but was granted no exec.
    tester = {tool["name"]: tool for tool in roles["tester"]["tools"]}
    assert tester["terminal_run"]["reachable"] is False
    assert "not granted" in tester["terminal_run"]["reason"]
    # Reviewer is reasoning-only; a declaration never creates authority.
    assert roles["reviewer"]["may_act"] is False
    assert all(tool["reachable"] is False for tool in roles["reviewer"]["tools"])


def test_permission_map_marks_unknown_instead_of_ok():
    reach = permission_map()
    assert reach["policy_known"] is False
    assert reach["tools_known"] is False
    acting = [role for role in reach["roles"] if role["may_act"]]
    assert acting
    for role in acting:
        for tool in role["tools"]:
            assert tool["reachable"] is None, (role["role_id"], tool["name"])
            assert "unknown" in tool["reason"]


def test_device_grants_are_scoped_and_suspension_revokes_reach(tmp_path):
    fabric, device = _online_device(tmp_path)
    store = DeviceGrantStore(fabric.home)
    store.grant(device.device_id, "device.battery", actor="coder",
                by="tester", reason="test grant")
    home = tmp_path / "home"
    policy = _policy(home)

    reach = permission_map(policy=policy, grant_store=store,
                           registry=fabric.registry)
    roles = {role["role_id"]: role for role in reach["roles"]}
    coder_grants = roles["coder"]["device_grants"]
    assert len(coder_grants) == 1
    assert coder_grants[0]["device_id"] == device.device_id
    assert coder_grants[0]["reachable"] is True
    assert roles["research"]["device_grants"] == []

    store.suspend_device(device.device_id, by="tester", reason="lost")
    reach = permission_map(policy=policy, grant_store=store,
                           registry=fabric.registry)
    roles = {role["role_id"]: role for role in reach["roles"]}
    grant = roles["coder"]["device_grants"][0]
    assert grant["suspended"] is True
    assert grant["reachable"] is False


def test_health_reports_online_device_and_ecc_harness(tmp_path):
    fabric, device = _online_device(tmp_path)
    policy = _policy(tmp_path / "home")
    orch = _orchestrator(tmp_path, policy)
    harness = _harness(tmp_path)

    health = reachability_health(
        supervisor=None, fabric=fabric, policy=policy,
        grant_store=DeviceGrantStore(fabric.home), orchestrator=orch,
        harness_root=harness)
    # No supervisor is bound here, so agent registry is honestly unknown.
    assert health["status"] == "unknown"
    assert health["devices"]["executable"] == 1
    assert health["devices"]["items"][0]["device_id"] == device.device_id
    assert health["devices"]["items"][0]["connectivity"] == "online"
    assert health["harness"]["skill_count"] == 1
    assert health["harness"]["agent_count"] == 1
    checks = {check["name"]: check for check in health["checks"]}
    assert checks["agent-registry"]["ok"] is None
    assert checks["device-registry"]["ok"] is True
    assert checks["device-grants"]["ok"] is True


def test_health_is_ok_with_supervisor_and_degraded_on_emergency(tmp_path):
    from jarvis.agents.agents import Supervisor

    fabric, _device = _online_device(tmp_path)
    policy = _policy(tmp_path / "home")
    supervisor = Supervisor()
    harness = _harness(tmp_path)

    health = reachability_health(
        supervisor=supervisor, fabric=fabric, policy=policy,
        grant_store=DeviceGrantStore(fabric.home), harness_root=harness)
    assert health["status"] == "ok", health["checks"]
    assert health["agents"]["total"] >= 1
    assert health["agents"]["reachable"] >= 1

    (tmp_path / "home" / "EMERGENCY_STOP").write_text("engaged\n")
    health = reachability_health(
        supervisor=supervisor, fabric=fabric, policy=policy,
        grant_store=DeviceGrantStore(fabric.home), harness_root=harness)
    assert health["status"] == "degraded"
    assert health["emergency_stop"] is True
    assert {check["name"]: check for check in health["checks"]}[
        "policy"]["ok"] is False


def test_health_never_claims_missing_subsystems_are_ok():
    health = reachability_health()
    assert health["status"] == "unknown"
    assert health["agents"]["known"] is False
    assert health["devices"]["known"] is False
    checks = {check["name"]: check for check in health["checks"]}
    assert checks["agent-registry"]["ok"] is None
    assert checks["device-registry"]["ok"] is None
    assert checks["policy"]["ok"] is None


def test_registry_search_finds_personas_roles_and_ecc_assets(tmp_path):
    harness = _harness(tmp_path)
    roles = registry_roster(query="friday", harness_root=harness)
    assert roles["matches"] == 1
    assert roles["named"][0]["id"] == "friday"
    assert "jarvis agents ask friday" in roles["named"][0]["dispatch"]
    assert roles["roles"] == [] and roles["harness"] == []

    roles = registry_roster(query="tester", harness_root=harness)
    assert any(role["id"] == "tester" for role in roles["roles"])
    assert all(role["dispatch"].startswith("jarvis agents run")
               for role in roles["roles"])

    harness_rows = registry_roster(query="demo", harness_root=harness)
    kinds = {row["kind"] for row in harness_rows["harness"]}
    assert kinds == {"ecc-skill", "ecc-agent"}
    assert all(row["source"] == "ecc" for row in harness_rows["harness"])


def test_registry_has_no_match_and_empty_results_are_explicit(tmp_path):
    harness = _harness(tmp_path)
    roles = registry_roster(query="definitely-not-an-agent",
                            harness_root=harness)
    assert roles["matches"] == 0
    assert roles["roles"] == [] and roles["named"] == []
    assert roles["counts"]["roles"] > 0


def test_build_reach_is_json_safe_and_has_no_secret_material(tmp_path):
    fabric, device = _online_device(tmp_path)
    store = DeviceGrantStore(fabric.home)
    store.grant(device.device_id, "device.battery", actor="coder",
                by="tester", reason="secret-hunter2-token")
    policy = _policy(tmp_path / "home")
    orch = _orchestrator(tmp_path, policy)

    class FakeJarvis:
        pass

    fake = FakeJarvis()
    fake.policy = policy
    fake.supervisor = orch.ctx.registry
    fake.orchestrator = orch
    fake.device_fabric = fabric
    fake.tools = orch.ctx.tools
    fake.config = JarvisConfig()
    fake.config.paths.home = tmp_path / "home"

    payload = build_reach(fake, harness_root=_harness(tmp_path))
    blob = json.dumps(payload, default=str)
    assert "secret-hunter2-token" not in blob
    assert payload["permissions"]["summary"]["roles"] > 0
    assert payload["health"]["devices"]["total"] == 1
    assert payload["registry"]["counts"]["roles"] > 0
    summary = reach_summary(fake)
    assert summary["status"] in ("ok", "degraded", "unknown")
    assert summary["roles"] > 0


def test_harness_inventory_reports_unavailable_root(tmp_path):
    inventory = harness_inventory(tmp_path / "missing")
    assert inventory["available"] is False
    assert inventory["skills"] == [] and inventory["agents"] == []
