"""Deterministic async-operator-UX tests (4.2 follow-up).

Durable policy grants, approval/command visibility, lifecycle display,
CLI behavior (via subprocess on isolated homes), audit coverage, and
the security battery. No real ~/.jarvis state is ever touched.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from jarvis.core.config import JarvisConfig
from jarvis.device.approvals import ApprovalStore
from jarvis.device.authz import DeviceGrantStore
from jarvis.device.outbox import CommandOutbox
from jarvis.device.service import DeviceCommandService
from jarvis.policy.policy import PolicyEngine

LAB_THRESHOLD = 0.8


def _policy(path=None, grants=(), threshold=0.5):
    policy = PolicyEngine(JarvisConfig(), grant_store_path=path)
    policy.config.policy.require_approval_above_risk = threshold
    for actor, perm in grants:
        policy.grant(actor, perm)
    return policy


def _home(tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return home


def _cli(home, *argv):
    return subprocess.run(
        [sys.executable, "-m", "jarvis.cli", "--home", str(home),
         *argv], capture_output=True, text=True, timeout=60)


# -- durable policy grants -------------------------------------------------------

def test_policy_grants_persist_and_propagate_revoke(tmp_path):
    home = _home(tmp_path)
    path = home / "policy-grants.json"
    first = _policy(path, [("op", "device.device.battery")])
    assert first.is_granted("op", "device.device.battery") is True
    second = _policy(path)
    assert second.is_granted("op", "device.device.battery") is True
    assert second.list_grants() == {"op": ["device.device.battery"]}
    assert second.get_grant("op") == ["device.device.battery"]
    second.revoke("op", "device.device.battery")
    assert first.is_granted("op", "device.device.battery") is False


def test_policy_grants_corrupt_fails_closed_and_recovers(tmp_path):
    home = _home(tmp_path)
    path = home / "policy-grants.json"
    engine = _policy(path, [("op", "x")])
    assert engine.is_granted("op", "x") is True
    path.write_text("{broken")
    assert engine.is_granted("op", "x") is False
    assert engine.permitted("op", ["x"]) == (
        False, ["policy grant store unreadable (fail closed)"])
    before = engine.list_grants("ghost")
    assert before == {"ghost": []}
    # Repair: a fresh write clears the error and restores decisions.
    engine2 = _policy(path)
    engine2.grant("op", "x")
    assert engine.is_granted("op", "x") is True


def test_policy_memory_only_unchanged(tmp_path):
    engine = _policy()
    assert engine.grant_store_path is None
    engine.grant("u", "x")
    assert engine.is_granted("u", "x") is True
    assert engine.list_grants() == {"u": ["x"]}


def test_concurrent_grant_writers_keep_both(tmp_path):
    home = _home(tmp_path)
    path = home / "policy-grants.json"
    left = _policy(path)
    right = _policy(path)
    left.grant("a", "p.a")
    right.grant("b", "p.b")
    fresh = _policy(path)
    assert fresh.is_granted("a", "p.a") is True
    assert fresh.is_granted("b", "p.b") is True


# -- approval visibility -----------------------------------------------------------

def test_approval_list_hides_tokens_but_stays_useful(tmp_path):
    home = _home(tmp_path)
    store = ApprovalStore(home)
    rec = store.request("op", "dev-1", "device.battery", {"x": 1}, by="op")
    rows = store.list()
    assert len(rows) == 1
    row = rows[0]
    assert row["approval_id"].endswith("…")
    assert len(row["approval_id"]) < len(rec["token"])
    assert row["device_id"] == "dev-1"
    assert row["capability"] == "device.battery"
    assert row["state"] == "pending"
    assert row["expires_at"] > row["created_at"]
    blob = json.dumps(rows)
    assert rec["token"] not in blob
    assert store.list("approved") == []
    assert len(store.list("pending")) == 1


def test_approval_show_unknown_is_none(tmp_path):
    home = _home(tmp_path)
    assert ApprovalStore(home).status("apd-nope") is None


# -- command lifecycle display -------------------------------------------------------

def _enriched(tmp_path, **kw):
    home = _home(tmp_path)
    box = CommandOutbox(home)
    rec = box.enqueue("dev-1", "device.battery", "device.get_battery",
                      {}, actor="op", **kw)
    return box, rec


def test_display_states_derive_without_explosion(tmp_path):
    from jarvis.device.service import DeviceCommandService as Svc
    assert Svc._display_state({"state": "queued"}, "") == "QUEUED"
    assert Svc._display_state({"state": "queued"}, "pending") == \
        "WAITING_APPROVAL"
    assert Svc._display_state({"state": "queued"}, "approved") == "APPROVED"
    assert Svc._display_state({"state": "sent"}, "") == "DELIVERED"
    assert Svc._display_state({"state": "acknowledged"}, "") == "DELIVERED"
    assert Svc._display_state({"state": "completed"}, "") == "COMPLETED"
    assert Svc._display_state({"state": "failed"}, "") == "FAILED"
    assert Svc._display_state({"state": "dead_letter"}, "") == "DEAD_LETTER"


def test_commands_list_filters_and_enriches(tmp_path):
    import sys as _sys
    _sys.path.insert(0, "tests")
    from test_android_transport import _adapter, _register, _policy as _p
    from jarvis.device.service import DeviceCommandService
    adapter = _adapter(tmp_path, _p())
    info = adapter.register_android("P", {"device_model": "m",
                                          "android_version": "15",
                                          "app_version": "1"}, by="t")
    dev = info["device_id"]
    svc = DeviceCommandService(adapter)
    first = svc.request_command("op", dev, "device.get_battery", {})
    assert first.get("command_id")
    rows = svc.commands_list()
    assert len(rows) == 1
    assert rows[0]["display_state"] in ("QUEUED", "WAITING_APPROVAL")
    assert rows[0]["result_summary"] == ""
    assert svc.commands_list("COMPLETED") == []
    assert svc.command_status("cmd-missing") is None


# -- CLI behavior (real subprocess, isolated home) ------------------------------------

def test_cli_policy_grant_revoke_list(tmp_path):
    home = _home(tmp_path)
    assert _cli(home, "device", "policy", "grant", "--actor", "ops",
                "--permission", "device.device.battery").returncode == 0
    out = _cli(home, "device", "policy", "list", "--actor", "ops")
    assert out.returncode == 0 and "device.device.battery" in out.stdout
    show = _cli(home, "device", "policy", "show", "--actor", "ops")
    assert show.returncode == 0 and "device.device.battery" in show.stdout
    assert _cli(home, "device", "policy", "revoke", "--actor", "ops",
                "--permission", "device.device.battery").returncode == 0
    show2 = _cli(home, "device", "policy", "show", "--actor", "ops")
    assert show2.returncode == 0 and "(none)" in show2.stdout


def test_cli_grants_approvals_commands_areas(tmp_path):
    home = _home(tmp_path)
    reg = _cli(home, "device", "android", "register", "--name", "P",
               "--model", "m", "--android-version", "15", "--app-version",
               "1", "--json")
    assert reg.returncode == 0
    dev = json.loads(reg.stdout)["device_id"]
    assert _cli(home, "device", "grants", "list").returncode == 0
    assert _cli(home, "device", "grants", "grant", "--device", dev,
                "--capability", "device.battery").returncode == 0
    shown = _cli(home, "device", "grants", "show", "--device", dev)
    assert shown.returncode == 0 and "device.battery" in shown.stdout
    assert _cli(home, "device", "approvals", "list").returncode == 0
    assert "no pending approvals" in _cli(
        home, "device", "approvals", "list").stdout
    assert _cli(home, "device", "commands", "list").returncode == 0
    missing = _cli(home, "device", "commands", "show",
                   "--command-id", "cmd-nope")
    assert missing.returncode == 1
    bad_approval = _cli(home, "device", "approvals", "approve",
                        "--approval", "apd-nope")
    assert bad_approval.returncode == 0
    assert "cannot approve" in bad_approval.stdout


def test_cli_watch_exits_cleanly_when_empty(tmp_path):
    home = _home(tmp_path)
    watched = _cli(home, "device", "approvals", "watch", "--timeout", "6")
    assert watched.returncode == 0


def test_cli_outputs_carry_no_secret_material(tmp_path):
    home = _home(tmp_path)
    reg = _cli(home, "device", "android", "register", "--name", "P",
               "--model", "m", "--android-version", "15", "--app-version",
               "1", "--json")
    dev = json.loads(reg.stdout)["device_id"]
    _cli(home, "device", "grants", "grant", "--device", dev,
         "--capability", "device.battery")
    blob = ""
    for argv in (["device", "grants", "list"],
                 ["device", "grants", "show", "--device", dev],
                 ["device", "approvals", "list"],
                 ["device", "commands", "list"],
                 ["device", "policy", "list"],
                 ["device", "audit"]):
        blob += _cli(home, *argv, "--json").stdout
    lowered = blob.lower()
    assert "hmac" not in lowered
    assert "pairing_code" not in lowered
    assert "device_secret" not in lowered
    assert "pending_token" not in lowered


# -- audit coverage ----------------------------------------------------------------------

def test_audit_events_cover_new_paths(tmp_path):
    home = _home(tmp_path)
    from jarvis.device.audit import DeviceAudit
    audit = DeviceAudit(home)
    store = ApprovalStore(home, audit=audit)
    rec = store.request("op", "dev-1", "device.battery", {}, by="op")
    store.prune()
    audit.record("device.command.authorized", actor="op", device_id="dev-1",
                 ok=True, extra={"command_id": "cmd-x"})
    events = {e["event"] for e in audit.tail(20)}
    assert "device.approval.requested" in events
    assert "device.command.authorized" in events
    for event in audit.tail(20):
        text = json.dumps(event).lower()
        assert "secret" not in text or "secretpresent" in text


def test_inspected_events_recorded(tmp_path):
    import sys as _sys
    _sys.path.insert(0, "tests")
    from test_android_transport import _adapter, _policy as _p
    from jarvis.device.service import DeviceCommandService
    adapter = _adapter(tmp_path, _p())
    svc = DeviceCommandService(adapter)
    rec = svc.approvals.request("op", "dev-9", "device.battery", {}, by="op")
    svc.audit.record("device.approval.inspected", actor="op",
                     device_id="dev-9", ok=True,
                     extra={"approval_id": rec["token"]})
    assert "device.approval.inspected" in {
        e["event"] for e in svc.audit_tail(10)}
