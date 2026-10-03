"""Deterministic 4.2 tests: persistent device intelligence.

Persistence, authorization, approvals, outbox lifecycle, security
(no-bypass), and integration against the real 3.10 building blocks.
No network, no emulator, no sleeps beyond millisecond TTLs.
"""

from __future__ import annotations

import json
import time

import pytest

from jarvis.core.config import JarvisConfig
from jarvis.device.android import AndroidNodeAdapter
from jarvis.device.approvals import ApprovalStore
from jarvis.device.audit import DeviceAudit
from jarvis.device.authz import DeviceGrantStore
from jarvis.device.fabric import DeviceFabric
from jarvis.device.outbox import CommandOutbox, OutboxError
from jarvis.device.protocol import FabricMessage, MessageType
from jarvis.device.registry import DeviceRegistry
from jarvis.device.router import DeviceRouter
from jarvis.device.service import DeviceCommandService
from jarvis.device.transport import InProcessTransport, LocalNode
from jarvis.policy.policy import PolicyEngine

META = {"device_model": "TestPhone", "android_version": "15",
        "app_version": "4.2.0"}
LAB_THRESHOLD = 0.8  # above the 0.75 device floor: no approval gating


def _policy(grants=(), threshold=0.5):
    policy = PolicyEngine(JarvisConfig())
    policy.config.policy.require_approval_above_risk = threshold
    for actor, perm in grants:
        policy.grant(actor, perm)
    return policy


def _fabric(tmp_path, policy=None):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    registry = DeviceRegistry(home / "device-fabric.json")
    return DeviceFabric(home=home, registry=registry,
                        policy=policy or _policy(),
                        transport=InProcessTransport())


def _adapter(tmp_path, policy=None):
    return AndroidNodeAdapter(_fabric(tmp_path, policy))


def _online_device(adapter, name="Pixel"):
    info = adapter.register_android(name, dict(META), by="tester")
    device_id = info["device_id"]
    adapter.trust_android(device_id, by="tester", reason="test")
    adapter.declare_android_capabilities(device_id, ["device.battery"],
                                         by="tester")
    adapter.connect(device_id, by="tester")
    return device_id


def _loopback_node(adapter, device_id, result="battery 77%"):
    node = LocalNode(device_id)

    def handle(msg):
        return FabricMessage(
            sender_node=device_id, recipient_node=msg.sender_node,
            message_type=MessageType.COMMAND_RESULT.value,
            capability="device.battery",
            correlation_id=msg.message_id,
            payload={"ok": True, "result": result})

    node.on("device.battery", handle)
    adapter.fabric.transport.register_node(node)
    return node


def _service(tmp_path, policy=None, **kw):
    adapter = _adapter(tmp_path, policy)
    return DeviceCommandService(adapter, **kw), adapter


# -- persistence ---------------------------------------------------------------

def test_grants_survive_restart(tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    first = DeviceGrantStore(home)
    first.grant("dev-1", "device.battery", by="op", reason="lab")
    first.suspend_device("dev-2", by="op")
    second = DeviceGrantStore(home)
    assert second.is_allowed("anyone", "dev-1", "device.battery")[0] is True
    assert second.is_suspended("dev-2") is True


def test_approvals_survive_restart(tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    first = ApprovalStore(home)
    rec = first.request("u", "dev-1", "device.battery", {"x": 1}, by="op")
    assert first.approve(rec["token"], by="op") is True
    second = ApprovalStore(home)
    assert second.status(rec["token"])["state"] == "approved"
    assert second.consume(rec["token"], actor="u", device_id="dev-1",
                          capability="device.battery",
                          args={"x": 1})[0] is True


def test_outbox_survives_restart(tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    first = CommandOutbox(home)
    rec = first.enqueue("dev-1", "device.battery", "device.get_battery",
                        {}, actor="u")
    second = CommandOutbox(home)
    assert second.get(rec["command_id"])["state"] == "queued"
    assert [c["command_id"] for c in second.claim_due()] == [rec["command_id"]]


def test_corrupt_persistence_recovers_empty(tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    (home / "device-grants.json").write_text("{broken")
    (home / "device-approvals.json").write_text("[1,2,3]")
    (home / "device-outbox.json").write_text("oops")
    assert DeviceGrantStore(home).is_allowed("u", "d", "c") == (
        False, "no grant for device/capability")
    assert ApprovalStore(home).status("nope") is None
    assert CommandOutbox(home).depth() == {"total": 0, "by_state": {}}


# -- authorization ---------------------------------------------------------------

def _router_with_store(tmp_path, policy=None):
    fabric = _fabric(tmp_path, policy)
    store = DeviceGrantStore(fabric.home)
    router = DeviceRouter(fabric.registry, fabric.policy,
                          fabric.transport, grant_store=store)
    return fabric, router, store


def _permissive_policy():
    # Policy side passes so tests isolate the grant layer.
    return _policy([("op", "device.device.battery")],
                   threshold=LAB_THRESHOLD)


def test_default_deny_without_grant(tmp_path):
    fabric, router, _ = _router_with_store(tmp_path, _permissive_policy())
    adapter = AndroidNodeAdapter(fabric)
    device_id = _online_device(adapter)
    out = router.authorize("op", device_id, "device.battery", {})
    assert out["authorized"] is False
    assert "device grant" in " ".join(out["reasons"])


def test_grant_allows_and_revoke_blocks(tmp_path):
    # No policy grants at all: the durable device grant alone must
    # satisfy the permission check (risk/approval stay authoritative,
    # so default-threshold policy still demands approval first).
    fabric, router, store = _router_with_store(tmp_path)
    adapter = AndroidNodeAdapter(fabric)
    device_id = _online_device(adapter)
    store.grant(device_id, "device.battery", by="op")
    asked = router.authorize("op", device_id, "device.battery", {})
    assert asked["authorized"] is False
    assert asked.get("approval_token")
    assert router.policy.approve(asked["approval_token"], by="op") is True
    assert router.authorize("op", device_id, "device.battery", {},
                            approval_token=asked["approval_token"])[
        "authorized"] is True
    store.revoke(device_id, "device.battery", by="op")
    out = router.authorize("op", device_id, "device.battery", {})
    assert out["authorized"] is False
    assert "device grant" in " ".join(out["reasons"])


def test_suspend_blocks_and_restore_works(tmp_path):
    fabric, router, store = _router_with_store(tmp_path)
    adapter = AndroidNodeAdapter(fabric)
    device_id = _online_device(adapter)
    store.grant(device_id, "device.battery", by="op")
    store.suspend_device(device_id, by="op")
    assert router.authorize("op", device_id, "device.battery", {})[
        "authorized"] is False
    assert store.restore_device(device_id, by="op") is True
    # Restored: grant substitutes permission; approval still required.
    asked = router.authorize("op", device_id, "device.battery", {})
    assert asked["authorized"] is False
    assert asked.get("approval_token")


def test_expired_grant_blocks(tmp_path):
    fabric, router, store = _router_with_store(tmp_path, _permissive_policy())
    adapter = AndroidNodeAdapter(fabric)
    device_id = _online_device(adapter)
    store.grant(device_id, "device.battery", by="op", ttl_s=0.01)
    time.sleep(0.02)
    out = router.authorize("op", device_id, "device.battery", {})
    assert out["authorized"] is False
    assert "expired" in " ".join(out["reasons"])


def test_capability_mismatch_denied(tmp_path):
    fabric, router, store = _router_with_store(tmp_path, _permissive_policy())
    adapter = AndroidNodeAdapter(fabric)
    device_id = _online_device(adapter)
    store.grant(device_id, "device.battery", by="op")
    out = router.authorize("op", device_id, "device.info", {})
    assert out["authorized"] is False


def test_untrusted_device_denied_despite_grant(tmp_path):
    fabric, router, store = _router_with_store(tmp_path, _permissive_policy())
    adapter = AndroidNodeAdapter(fabric)
    info = adapter.register_android("Pixel", dict(META), by="tester")
    device_id = info["device_id"]
    store.grant(device_id, "device.battery", by="op")
    out = router.authorize("op", device_id, "device.battery", {})
    assert out["authorized"] is False
    assert "not online" in " ".join(out["reasons"])


def test_router_without_store_is_backward_compatible(tmp_path):
    fabric = _fabric(tmp_path, _policy([("op", "device.device.battery")],
                                       threshold=LAB_THRESHOLD))
    adapter = AndroidNodeAdapter(fabric)
    device_id = _online_device(adapter)
    assert fabric.router.authorize("op", device_id, "device.battery", {})[
        "authorized"] is True


# -- approvals -------------------------------------------------------------------

def test_durable_approval_full_cycle(tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    store = ApprovalStore(home)
    rec = store.request("u", "dev-1", "device.battery", {"x": 1}, by="op")
    token = rec["token"]
    assert store.consume(token, actor="u", device_id="dev-1",
                         capability="device.battery",
                         args={"x": 1})[0] is False  # still pending
    assert store.approve(token, by="op") is True
    assert store.approve(token, by="op") is False  # no double approve
    assert store.consume(token, actor="u", device_id="dev-1",
                         capability="device.battery",
                         args={"x": 1}) == (True, "consumed")
    assert store.consume(token, actor="u", device_id="dev-1",
                         capability="device.battery",
                         args={"x": 1})[0] is False  # replay loses


def test_approval_wrong_bindings_rejected(tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    store = ApprovalStore(home)
    token = store.request("u", "dev-1", "device.battery", {"x": 1},
                          by="op")["token"]
    assert store.approve(token, by="op") is True
    assert "another device" in store.consume(
        token, actor="u", device_id="dev-2",
        capability="device.battery", args={"x": 1})[1]
    assert "another capability" in store.consume(
        token, actor="u", device_id="dev-1",
        capability="device.info", args={"x": 1})[1]
    assert "other arguments" in store.consume(
        token, actor="u", device_id="dev-1",
        capability="device.battery", args={"x": 2})[1]
    assert "another actor" in store.consume(
        token, actor="mallory", device_id="dev-1",
        capability="device.battery", args={"x": 1})[1]
    # Untouched by the failed attempts: the real call still consumes.
    assert store.consume(token, actor="u", device_id="dev-1",
                         capability="device.battery",
                         args={"x": 1})[0] is True


def test_approval_expiry_deny_revoke(tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    store = ApprovalStore(home)
    short = store.request("u", "dev-1", "device.battery", {}, by="op",
                          ttl_s=0.01)["token"]
    time.sleep(0.02)
    assert store.approve(short, by="op") is False
    assert "expired" in store.consume(
        short, actor="u", device_id="dev-1",
        capability="device.battery", args={})[1]
    doomed = store.request("u", "dev-1", "device.battery", {}, by="op")[
        "token"]
    assert store.deny(doomed, by="op", reason="no") is True
    assert store.consume(doomed, actor="u", device_id="dev-1",
                         capability="device.battery", args={})[0] is False
    pending = store.request("u", "dev-1", "device.battery", {}, by="op")[
        "token"]
    assert store.revoke(pending, by="op") is True
    assert store.consume(pending, actor="u", device_id="dev-1",
                         capability="device.battery", args={})[0] is False


def test_router_consumes_durable_approval_once(tmp_path):
    fabric = _fabric(tmp_path, _policy([("op", "device.device.battery")]))
    adapter = AndroidNodeAdapter(fabric)
    device_id = _online_device(adapter)
    node = LocalNode(device_id)

    def handle(msg):
        return FabricMessage(
            sender_node=device_id, recipient_node=msg.sender_node,
            message_type=MessageType.COMMAND_RESULT.value,
            capability="device.battery",
            correlation_id=msg.message_id,
            payload={"ok": True, "result": "battery 77%"})

    node.on("device.battery", handle)
    fabric.transport.register_node(node)
    approvals = ApprovalStore(fabric.home)
    router = DeviceRouter(fabric.registry, fabric.policy,
                          fabric.transport, approval_store=approvals)
    rec = approvals.request("op", device_id, "device.battery", {}, by="op")
    approvals.approve(rec["token"], by="op")
    # authorize() peeks (pure check, twice fine); delivery consumes once.
    assert router.authorize("op", device_id, "device.battery", {},
                            approval_token=rec["token"])["authorized"] is True
    first = router.route("op", device_id, "device.battery", {},
                         approval_token=rec["token"])
    assert first["ok"] is True, first
    second = router.route("op", device_id, "device.battery", {},
                          approval_token=rec["token"])
    assert second["ok"] is False  # single use: replay denied at delivery
    assert "consumed" in second.get("error", "")


# -- outbox / service --------------------------------------------------------------

def _lab_service(tmp_path):
    policy = _policy([("op", "device.device.battery")],
                     threshold=LAB_THRESHOLD)
    svc, adapter = _service(tmp_path, policy)
    device_id = _online_device(adapter)
    svc.grants.grant(device_id, "device.battery", by="op")
    _loopback_node(adapter, device_id)
    return svc, adapter, device_id


def test_service_request_completes(tmp_path):
    svc, _, device_id = _lab_service(tmp_path)
    out = svc.request_command("op", device_id, "device.get_battery", {})
    assert out["ok"] is True
    assert "77" in str(out.get("result", ""))
    assert svc.command_status(out["command_id"])["state"] == "completed"


def test_service_approval_flow_then_completes(tmp_path):
    policy = _policy([("op", "device.device.battery")])  # default threshold
    svc, adapter = _service(tmp_path, policy)
    device_id = _online_device(adapter)
    svc.grants.grant(device_id, "device.battery", by="op")
    _loopback_node(adapter, device_id)
    asked = svc.request_command("op", device_id, "device.get_battery", {})
    assert asked["ok"] is False
    assert asked["requires_approval"] is True
    approval_id = asked["approval_id"]
    assert svc.approve_command(approval_id, by="op") is True
    done = svc.request_command("op", device_id, "device.get_battery", {},
                               approval_id=approval_id)
    assert done["ok"] is True, done
    assert svc.command_status(done["command_id"])["state"] == "completed"
    # The token is spent: re-presenting it cannot authorize again.
    again = svc.request_command("op", device_id, "device.get_battery", {},
                               approval_id=approval_id)
    assert again.get("requires_approval") is True
    assert again["approval_id"] != approval_id


def test_service_malformed_never_enqueues_but_denials_are_recorded(tmp_path):
    svc, adapter, device_id = _lab_service(tmp_path)
    bad = svc.request_command("op", device_id, "device.self_destruct", {})
    assert bad["ok"] is False and bad.get("command_id") is None
    # Wildcard grant covers any actor: a stranger's request parks for
    # human approval (the approver sees actor=intruder and can deny).
    parked = svc.request_command("intruder", device_id,
                                 "device.get_battery", {})
    assert parked["ok"] is False
    assert parked.get("requires_approval") is True
    assert svc.command_status(parked["command_id"])["state"] == "queued"
    # No grant at all: hard FAILED record (auditable, not silent).
    naked = svc.request_command("op", "dev-unknown", "device.get_battery",
                                {})
    assert naked["ok"] is False
    assert naked.get("command_id")
    assert svc.command_status(naked["command_id"])["state"] == "failed"


def test_service_offline_defers_for_reconnect(tmp_path):
    svc, adapter, device_id = _lab_service(tmp_path)
    adapter.disconnect(device_id, by="op")  # lane-less drain defers
    out = svc.request_command("op", device_id, "device.get_battery", {})
    assert out["ok"] is False  # offline at request time: fast deny w/ record
    assert out.get("command_id")
    # Draining while offline leaves it queued (reconnect may come).
    svc.tick()
    assert svc.command_status(out["command_id"])["state"] == "queued"


def test_outbox_retry_dead_letter_and_cancel(tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    box = CommandOutbox(home)
    rec = box.enqueue("dev-1", "c", "cmd", {}, actor="u", max_retries=1)
    cid = rec["command_id"]
    box.transition(cid, "dispatching")
    failed = box.fail(cid, "boom", retryable=True)
    assert failed["state"] == "retrying"
    box.transition(cid, "dispatching")
    dead = box.fail(cid, "boom again", retryable=True)
    assert dead["state"] == "dead_letter"
    live = box.enqueue("dev-1", "c", "cmd", {}, actor="u")
    cancelled = box.cancel(live["command_id"], by="u", reason="stop")
    assert cancelled["state"] == "cancelled"
    with pytest.raises(OutboxError):
        box.transition(live["command_id"], "dispatching")


def test_outbox_recover_stale_inflight(tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    box = CommandOutbox(home)
    rec = box.enqueue("dev-1", "c", "cmd", {}, actor="u", timeout_s=10)
    box.transition(rec["command_id"], "dispatching")
    out = box.recover(at=1e12)
    assert out == {"recovered": 1}
    again = box.get(rec["command_id"])
    assert again["state"] == "retrying"
    assert again["recovered"] is True


def test_outbox_duplicate_result_ignored(tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    box = CommandOutbox(home)
    rec = box.enqueue("dev-1", "c", "cmd", {}, actor="u")
    assert box.complete(rec["command_id"], {"ok": True}) == (True, "completed")
    assert box.complete(rec["command_id"], {"ok": True})[0] is False


def test_tick_delivers_and_counts(tmp_path):
    svc, _, device_id = _lab_service(tmp_path)
    first = svc.request_command("op", device_id, "device.get_battery", {})
    assert first["ok"] is True
    counts = svc.tick()
    assert counts["completed"] == 0  # nothing left pending
    assert svc.outbox_status()["by_state"].get("completed") == 1


# -- security: bypass attempts -------------------------------------------------------

def test_direct_route_without_grant_is_denied(tmp_path):
    """Lower-level router.route cannot bypass the grant store."""
    fabric = _fabric(tmp_path, _policy([("op", "device.device.battery")],
                                       threshold=LAB_THRESHOLD))
    adapter = AndroidNodeAdapter(fabric)
    device_id = _online_device(adapter)
    _loopback_node(adapter, device_id)
    store = DeviceGrantStore(fabric.home)
    router = DeviceRouter(fabric.registry, fabric.policy,
                          fabric.transport, grant_store=store)
    out = router.route("op", device_id, "device.battery", {})
    assert out["ok"] is False
    assert "device grant" in out.get("error", "")


def test_direct_host_path_without_grant_is_denied(tmp_path):
    """host.send_command authorizes through the same attached router."""
    from jarvis.device.android_transport import AndroidSocketHost
    fabric = _fabric(tmp_path, _policy([("op", "device.device.battery")],
                                       threshold=LAB_THRESHOLD))
    adapter = AndroidNodeAdapter(fabric)
    device_id = _online_device(adapter)
    store = DeviceGrantStore(fabric.home)
    approvals = ApprovalStore(fabric.home)
    fabric.router.grant_store = store
    fabric.router.approval_store = approvals
    host = AndroidSocketHost(adapter)
    try:
        out = host.send_command("op", device_id, "device.get_battery", {})
        assert out["ok"] is False
        assert "device grant" in out.get("error", "")
    finally:
        host.stop()


def test_audit_trail_covers_lifecycle(tmp_path):
    svc, _, device_id = _lab_service(tmp_path)
    svc.request_command("op", device_id, "device.get_battery", {})
    events = {e["event"] for e in svc.audit_tail(20)}
    assert {"device.grant.created", "device.command.requested",
            "device.command.queued", "device.command.completed",
            "device.command.dispatched"} <= events
    for event in svc.audit_tail(20):
        assert "secret" not in json.dumps(event).lower()
        assert "pending_token" not in json.dumps(event).lower()
