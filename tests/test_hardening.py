"""Hardening regression tests: sandbox, scrubbing, fail-closed, recovery.

Each test here exists because a real defect or audit gap was found during
the 4.1 hardening pass. No network, no device, no threads.
"""

from __future__ import annotations

import json

import pytest

from jarvis.tools.tools import default_registry, python_run
from jarvis.intelligence.loop import IntelligenceLoop
from jarvis.intelligence.snapshot import CycleSnapshot, scrub
from jarvis.intelligence.wiring import make_policy_hook
from jarvis.policy.policy import PolicyEngine


# -- H1: python_run AST whitelist ---------------------------------------

def test_python_run_allows_pure_expression():
    result = python_run("sum([1, 2, 3]) * 2")
    assert result.ok
    assert result.output["result"] == 12


def test_python_run_allows_assignment_in_exec_branch():
    result = python_run("result = max(3, 9)")
    assert result.ok
    assert result.output["result"] == 9


@pytest.mark.parametrize("code", [
    "import os",
    "from os import system",
    "__import__('os')",
    "().__class__",
    "open('/etc/passwd')",
    "eval('1+1')",
    "exec('x=1')",
    "globals()",
    "getattr(1, 'x')",
    "(lambda: 1)()",
    "def f():\n    return 1",
    "class C:\n    pass",
    "while True:\n    pass",
    "for i in range(10):\n    pass",
    "with open('/etc/passwd') as f:\n    pass",
    "raise ValueError('x')",
    "try:\n    x = 1\nexcept Exception:\n    pass",
    "print('hello')",
])
def test_python_run_blocks_unsafe_constructs(code):
    result = python_run(code)
    assert not result.ok, f"unsafe code accepted: {code!r}"
    assert "blocked" in result.error or "not allowed" in result.error


def test_python_run_string_concat_is_inert_not_smuggled():
    """Concatenation only ever yields a string; no dangerous use can reach it."""
    result = python_run('"im" + "port" + " os"')
    assert result.ok
    assert result.output["result"] == "import os"  # a plain value, never executed
    # every way of *using* such a string dynamically stays blocked
    for code in ('getattr(1, "_" + "_class")',
                 'eval("1+1")',
                 'open("/etc/passwd")'):
        blocked = python_run(code)
        assert not blocked.ok, f"dangerous use accepted: {code!r}"


def test_python_run_rejects_oversized_source():
    result = python_run("1 + " * 2000 + "1")
    assert not result.ok
    assert "4000" in result.error or "exceeds" in result.error


def test_python_run_result_is_capped():
    result = python_run("list(range(5000))")
    assert result.ok
    text = json.dumps(result.output, default=str)
    assert len(text) < 6000


# -- H3: snapshot scrubbing --------------------------------------------

def test_scrub_redacts_secret_keys_recursively():
    payload = {"api_key": "abc123", "nested": {"password": "hunter2",
                                               "safe": "ok"},
               "list": [{"token": "t0ken"}]}
    cleaned = scrub(payload)
    assert cleaned["api_key"] == "[redacted]"
    assert cleaned["nested"]["password"] == "[redacted]"
    assert cleaned["nested"]["safe"] == "ok"
    assert cleaned["list"][0]["token"] == "[redacted]"


def test_scrub_truncates_long_strings():
    assert scrub({"text": "x" * 2000})["text"].endswith("[truncated]")


def test_cycle_snapshot_to_json_contains_no_secrets():
    loop = IntelligenceLoop()
    loop.start()
    record = loop.cycle_once({"password": "topsecret", "text": "hello"})
    from jarvis.intelligence.snapshot import capture
    snapshot = capture(record, {"password": "topsecret"})
    blob = snapshot.to_json()
    assert "topsecret" not in blob
    assert "[redacted]" in blob
    assert CycleSnapshot.from_dict(snapshot.to_dict()).snapshot_id == snapshot.snapshot_id


# -- H4: policy fails closed -------------------------------------------

def test_policy_hook_denies_when_policy_missing():
    allowed, reason = make_policy_hook(None)("filesystem_write", {})
    assert allowed is False
    assert "fail closed" in reason


def test_policy_hook_denies_without_tool_registry():
    """Cannot verify permissions without a registry -> fail closed."""
    allowed, reason = make_policy_hook(PolicyEngine())("filesystem_write", {})
    assert allowed is False
    assert "cannot verify permissions" in reason


def test_policy_hook_denies_unknown_tool():
    allowed, reason = make_policy_hook(PolicyEngine(), tools=default_registry())(
        "definitely_not_a_tool", {})
    assert allowed is False
    assert "unknown tool" in reason


def test_policy_hook_denies_ungranted_permission():
    allowed, reason = make_policy_hook(PolicyEngine(), tools=default_registry())(
        "filesystem_write", {})
    assert allowed is False
    assert "lacks permissions" in reason


def test_policy_hook_allows_granted_low_risk_action():
    policy = PolicyEngine()
    policy.grant("intelligence-loop", "fs.read")
    allowed, _ = make_policy_hook(policy, tools=default_registry())(
        "filesystem_read", {"path": "README.md"})
    assert allowed is True


def test_policy_hook_requires_approval_for_high_risk_action():
    policy = PolicyEngine()
    policy.grant("intelligence-loop", "exec")
    allowed, reason = make_policy_hook(policy, tools=default_registry())(
        "terminal_run", {"command": "ls"})
    assert allowed is False
    assert "needs approval" in reason


def test_policy_hook_denies_on_policy_exception():
    class Exploding:
        def evaluate(self, actor, plan):
            raise RuntimeError("policy backend down")
    allowed, reason = make_policy_hook(Exploding(), tools=default_registry())(
        "filesystem_read", {"path": "README.md"})
    assert allowed is False
    assert "fail closed" in reason


# -- H8: corrupt state recovery ----------------------------------------

def test_corrupt_snapshot_json_recovers_to_empty(tmp_path):
    path = tmp_path / "android-pairings.json"
    path.write_text("{not json")
    from jarvis.device.android import PairingManager
    manager = PairingManager(path=str(path))
    assert manager.pending_devices() == []


def test_corrupt_world_store_recovers(tmp_path):
    from jarvis.world.registry import JsonFileWorldStore, WorldRegistry
    store_path = tmp_path / "world.json"
    store_path.write_text("{broken")
    store = JsonFileWorldStore(str(store_path))
    registry = WorldRegistry()
    registry.load(store)
    assert registry.find_entities() == []
    assert store.last_load_error, "corruption must be reported, not hidden"
    registry.save(store)
    assert store_path.exists()


def test_corrupt_world_bytes_survive_save_for_forensics(tmp_path):
    """Jarvis.close() saves the world store; corrupt bytes must not vanish."""
    from jarvis.world.registry import JsonFileWorldStore, WorldRegistry
    store_path = tmp_path / "world.json"
    store_path.write_text("{broken")
    store = JsonFileWorldStore(str(store_path))
    registry = WorldRegistry()
    registry.load(store)
    registry.save(store)  # same call Jarvis.close() makes
    quarantined = [p for p in tmp_path.iterdir() if ".corrupt-" in p.name]
    assert len(quarantined) == 1, "corrupt bytes must be preserved off to the side"
    assert quarantined[0].read_text() == "{broken"
    assert store.quarantined_path == str(quarantined[0])


def test_non_dict_world_payload_is_quarantined(tmp_path):
    from jarvis.world.registry import JsonFileWorldStore, WorldRegistry
    store_path = tmp_path / "world.json"
    store_path.write_text("[1, 2, 3]")
    store = JsonFileWorldStore(str(store_path))
    registry = WorldRegistry()
    registry.load(store)
    assert registry.find_entities() == []
    assert "not an object" in store.last_load_error
    assert store.quarantined_path, "wrong-shaped payload is also evidence"
    registry.save(store)
    assert (tmp_path / "world.json").exists()
    quarantined = [p for p in tmp_path.iterdir() if ".corrupt-" in p.name][0]
    assert quarantined.read_text() == "[1, 2, 3]"


def test_jarvis_boots_on_corrupt_world_and_preserves_evidence(tmp_path):
    """End-to-end: boot + close() must not destroy a corrupt world file."""
    from jarvis.core.config import JarvisConfig
    from jarvis.core.loop import Jarvis
    config = JarvisConfig()
    config.paths.home = tmp_path
    (tmp_path / "world.json").write_text("{broken")
    jarvis = Jarvis(config=config)
    assert jarvis.world_registry.find_entities() == []
    jarvis.close()
    quarantined = [p for p in tmp_path.iterdir() if ".corrupt-" in p.name]
    assert len(quarantined) == 1
    assert quarantined[0].read_text() == "{broken"


def test_corrupt_connectome_schema_rejected_not_crashed(tmp_path):
    from jarvis.neural.topology import ConnectomeSchema
    path = tmp_path / "schema.json"
    path.write_text("{oops")
    with pytest.raises(Exception):
        ConnectomeSchema.load_json(str(path))


def test_registry_roundtrip_survives_corrupt_entries(tmp_path):
    from jarvis.world.registry import JsonFileWorldStore, WorldRegistry
    store = JsonFileWorldStore(str(tmp_path / "world.json"))
    registry = WorldRegistry()
    registry.upsert_entity("device", "lamp", state={"power": "on"})
    registry.save(store)
    store.path.write_text(json.dumps({"entities": {"device:lamp": {"broken": True}},
                                      "relations": {}, "observations": {},
                                      "history": {}, "conflicts": []}))
    fresh = WorldRegistry()
    fresh.load(store)
    assert fresh.find_entities() == []


# -- registry sanity: default_registry still exposes the tool ----------

def test_default_registry_python_run_permission_gated():
    registry = default_registry()
    entry = next(t for t in registry.list_tools() if t["name"] == "python_run")
    assert "exec.eval" in entry["permissions"]