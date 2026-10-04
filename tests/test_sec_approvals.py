"""Permission-every-time: durable approvals, single-use redemption.

Proves security tools (and any HIGH-risk tool) cannot run without a
fresh interactive approval, approvals survive restarts, redeemed
tokens cannot be re-spent, and standing grants can never cover sec.*.
"""

from __future__ import annotations

import pytest

from jarvis.core.config import JarvisConfig
from jarvis.policy.policy import PolicyEngine


def _policy(home, **kw):
    config = JarvisConfig()
    config.paths.home = home
    return PolicyEngine(config, **kw)


def test_approvals_persist_across_restart(tmp_path):
    from jarvis.core.types import ActionPlan
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    first = _policy(home)
    token = first.request_approval(
        "security", ActionPlan(action="net_inventory x", args={},
                               required_permissions=["sec.audit"]),
        type("D", (), {"risk": 0.9})())
    second = _policy(home)
    assert second.approved(token) is False  # still pending, not approved
    assert second.approve(token, by="cli") is True
    third = _policy(home)
    assert third.approved(token) is True  # approval survived restart


def test_redeem_single_use_with_bindings(tmp_path):
    from jarvis.core.types import ActionPlan
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    policy = _policy(home)
    token = policy.request_approval(
        "security", ActionPlan(action="net_inventory x", args={"a": 1},
                               required_permissions=["sec.audit"]),
        type("D", (), {"risk": 0.9})())
    policy.approve(token, by="cli")
    assert policy.redeem(token, "security", "net_inventory x",
                         {"a": 1}) is True
    assert policy.redeem(token, "security", "net_inventory x",
                         {"a": 1}) is False  # spent
    # Wrong bindings never redeem.
    token2 = policy.request_approval(
        "security", ActionPlan(action="net_inventory y", args={},
                               required_permissions=["sec.audit"]),
        type("D", (), {"risk": 0.9})())
    policy.approve(token2, by="cli")
    assert policy.redeem(token2, "intruder", "net_inventory y",
                         {}) is False
    assert policy.redeem(token2, "security", "net_inventory OTHER",
                         {}) is False
    assert policy.redeem(token2, "security", "net_inventory y",
                         {"different": True}) is False
    assert policy.redeem("nope", "security", "x", {}) is False
    # Unapproved token never redeems.
    token3 = policy.request_approval(
        "security", ActionPlan(action="net_inventory z", args={},
                               required_permissions=["sec.audit"]),
        type("D", (), {"risk": 0.9})())
    assert policy.redeem(token3, "security", "net_inventory z",
                         {}) is False


def test_standing_grant_never_covers_sec(tmp_path):
    from jarvis.policy.standing import StandingGrantStore
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    policy = _policy(home)
    store = StandingGrantStore(home)
    policy.bind_standing_grants(store)
    store.create("sec.audit", "capability", "sec.audit",
                 allowed_operations=["scan"], risk_class="critical")
    assert policy.authorize_standing(
        "user", "sec.audit", "capability", "sec.audit",
        "scan") == (False, "security tools require live approval")


def test_gated_tool_full_cycle_approve_redeem(tmp_path):
    from jarvis.agents.orchestrator import Budgets, Orchestrator
    from jarvis.agents.orchestrator import OrchestratorContext
    from jarvis.agents.agents import AgentRegistry, Planner
    from jarvis.tools.tools import ToolResult, default_registry
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    policy = _policy(home)
    policy.grant("security", "sec.audit")
    reg = default_registry()
    real_call = reg.call
    calls = {"n": 0}

    def _fake_call(name, **kw):
        calls["n"] += 1
        assert name == "net_inventory"
        return ToolResult(tool=name, ok=True, output={"ran": True})

    reg.call = _fake_call  # type: ignore[method-assign]
    try:
        ctx = OrchestratorContext(
            registry=AgentRegistry(), planner=Planner(),
            policy=policy, tools=reg)
        orch = Orchestrator(ctx)
        state = {"tool_calls": 0, "agents_used": 0}
        args = {"target": "192.168.1.0/24"}
        first = orch._gated_tool("security", "net_inventory", args,
                                 state, Budgets(), "audit scan")
        assert first.success is False
        assert "needs approval" in "; ".join(first.errors)
        assert calls["n"] == 0  # nothing executed pre-approval
        pending = policy.list_approvals("pending")
        assert len(pending) == 1
        full = next(t for t in policy.approvals
                    if t.startswith(pending[0]["approval_id"][:12]))
        assert policy.approve(full, by="cli") is True
        second = orch._gated_tool("security", "net_inventory", args,
                                  state, Budgets(), "audit scan",
                                  approval=full)
        assert second.success is True
        assert calls["n"] == 1 and state["tool_calls"] == 1
        # Same token cannot buy a second execution.
        third = orch._gated_tool("security", "net_inventory", args,
                                 state, Budgets(), "audit scan",
                                 approval=full)
        assert third.success is False
        assert calls["n"] == 1
    finally:
        reg.call = real_call  # type: ignore[method-assign]


def test_cli_approvals_roundtrip(tmp_path):
    import subprocess
    import sys as _sys
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    policy = _policy(home)
    from jarvis.core.types import ActionPlan
    token = policy.request_approval(
        "security", ActionPlan(action="net_inventory x", args={},
                               required_permissions=["sec.audit"]),
        type("D", (), {"risk": 0.9})())
    prefix = token[:8]

    def _cli(*argv):
        return subprocess.run(
            [_sys.executable, "-m", "jarvis.cli", "--home", str(home),
             *argv], capture_output=True, text=True, timeout=120)

    listed = _cli("approvals", "list")
    assert listed.returncode == 0
    assert prefix in listed.stdout
    assert token not in listed.stdout  # truncated, never dumped
    approved = _cli("approvals", "approve", "--token", prefix)
    assert approved.returncode == 0
    assert _policy(home).approved(token) is True
    # Double approve refused.
    again = _cli("approvals", "approve", "--token", prefix)
    assert again.returncode == 1


def test_cli_approvals_deny(tmp_path):
    import subprocess
    import sys as _sys
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    policy = _policy(home)
    from jarvis.core.types import ActionPlan
    token = policy.request_approval(
        "security", ActionPlan(action="x", args={},
                               required_permissions=["sec.audit"]),
        type("D", (), {"risk": 0.9})())
    proc = subprocess.run(
        [_sys.executable, "-m", "jarvis.cli", "--home", str(home),
         "approvals", "deny", "--token", token[:8]],
        capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0
    assert _policy(home).approved(token) is False
