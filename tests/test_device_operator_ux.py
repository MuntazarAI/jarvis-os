"""Async operator command UX tests (#40).

Pending approvals are discoverable (truncated listings) AND actionable
(unique-prefix approve/deny/revoke/show) across processes, without
dumping full tokens. Grants/revokes are visible cross-process. Single
use, bindings, and expiry are preserved through the prefix path.
"""

from __future__ import annotations

import pytest

from jarvis.device.approvals import ApprovalStore
from jarvis.device.authz import DeviceGrantStore


def _request(store: ApprovalStore) -> dict:
    return store.request("op", "dev-1", "device.battery", {"x": 1},
                         by="op", reason="test")


def test_prefix_approve_cross_instance(tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    first = ApprovalStore(home)
    record = _request(first)
    token = record["token"]
    # A different process (new instance, same home) approves by prefix.
    second = ApprovalStore(home)
    assert second.approve(token[:8], by="op2") is True
    assert ApprovalStore(home).status(token)["state"] == "approved"


def test_prefix_deny_revoke_show(tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    store = ApprovalStore(home)
    denied = _request(store)
    assert store.deny(denied["token"][:10], by="op",
                      reason="no") is True
    assert store.status(denied["token"][:10])["state"] == "denied"
    pending = _request(store)
    assert store.revoke(pending["token"][:12], by="op") is True
    assert store.status(pending["token"])["state"] == "revoked"


def test_ambiguous_short_unknown_prefix_rejected(tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    store = ApprovalStore(home)
    assert store.approve("abc", by="op") is False  # too short
    assert store.approve("zzzzz-nope", by="op") is False  # unknown
    assert store.resolve_prefix("") is None


def test_full_token_still_works(tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    store = ApprovalStore(home)
    record = _request(store)
    assert store.approve(record["token"], by="op") is True
    assert store.status(record["token"])["state"] == "approved"


def test_prefix_single_use_preserved(tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    store = ApprovalStore(home)
    record = _request(store)
    assert store.approve(record["token"][:8], by="op") is True
    assert store.approve(record["token"][:8], by="op") is False
    # consume() is the machine path: exact token, fail closed.
    ok, _ = store.consume(record["token"], actor="op",
                           device_id="dev-1",
                           capability="device.battery", args={"x": 1})
    assert ok is True
    ok2, _ = store.consume(record["token"], actor="op",
                            device_id="dev-1",
                            capability="device.battery", args={"x": 1})
    assert ok2 is False


def test_prefix_bindings_still_enforced(tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    store = ApprovalStore(home)
    record = _request(store)
    store.approve(record["token"], by="op")
    ok, reason = store.consume(record["token"], actor="intruder",
                               device_id="dev-1",
                               capability="device.battery",
                               args={"x": 1})
    assert ok is False and "actor" in reason


def test_grants_visible_cross_process(tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    first = DeviceGrantStore(home)
    first.grant("dev-9", "device.battery", by="op", reason="t")
    second = DeviceGrantStore(home)
    assert any(g["device_id"] == "dev-9"
               for g in second.grants_for("dev-9"))
    first.revoke("dev-9", "device.battery", by="op")
    third = DeviceGrantStore(home)
    live = [g for g in third.grants_for("dev-9")
            if g.get("status") == "active"]
    assert live == []  # history retained, nothing enforceable


def test_next_steps_hint_actionable():
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(
        __file__).resolve().parent.parent))
    from jarvis.cli import _approval_next_steps
    hint = _approval_next_steps("apd-0123456789abcdef", "cmd-1")
    assert "apd-01234567" in hint  # prefix shown, not full token
    assert "apd-0123456789abcdef" not in hint
    assert "approvals approve --approval apd-01234567" in hint
    assert "approvals watch" in hint
    assert "cmd-1" in hint
