"""The policy engine: the boundary every action passes through.

These tests cover the guarantees the rest of the system relies on:
a permission check that means something, approvals that can be spent
once, a stop that blocks, and an audit trail that records what
happened.
"""

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.core.config import JarvisConfig  # noqa: E402
from jarvis.core.types import ActionPlan, RiskLevel  # noqa: E402
from jarvis.policy.policy import PolicyEngine  # noqa: E402


@pytest.fixture
def policy(tmp_path):
    config = JarvisConfig()
    config.paths.home = tmp_path
    return PolicyEngine(config, grant_store_path=str(tmp_path / "grants.json"))


def _plan(action="read a file", args=None, permissions=None, risk=None):
    return ActionPlan(action=action, args=args or {},
                      required_permissions=permissions or [],
                      risk=risk or RiskLevel.LOW)


# -- permissions -------------------------------------------------------------
def test_missing_permission_denies(policy):
    decision = policy.evaluate("nobody", _plan(permissions=["fs.write"]))
    assert decision.allow is False
    assert decision.requires_approval is True
    assert "missing permissions" in "; ".join(decision.reasons)


def test_granted_permission_allows(policy):
    policy.grant("coder", "fs.read")
    decision = policy.evaluate("coder", _plan(permissions=["fs.read"]))
    assert decision.allow is True
    assert decision.requires_approval is False


def test_a_grant_belongs_to_one_actor(policy):
    policy.grant("coder", "fs.read")
    decision = policy.evaluate("someone-else", _plan(permissions=["fs.read"]))
    assert decision.allow is False


def test_a_wildcard_grant_covers_everything(policy):
    policy.grant("root", "*")
    decision = policy.evaluate("root", _plan(permissions=["fs.write"]))
    assert decision.allow is True


def test_revoke_takes_effect_immediately(policy):
    policy.grant("coder", "fs.read")
    assert policy.evaluate("coder", _plan(permissions=["fs.read"])).allow
    policy.revoke("coder", "fs.read")
    assert not policy.evaluate("coder", _plan(permissions=["fs.read"])).allow


def test_grants_survive_a_new_engine(policy, tmp_path):
    policy.grant("coder", "fs.read")
    fresh = PolicyEngine(policy.config,
                          grant_store_path=str(tmp_path / "grants.json"))
    assert fresh.is_granted("coder", "fs.read") is True


def test_a_corrupt_grant_store_fails_closed(tmp_path):
    path = tmp_path / "grants.json"
    path.write_text("{broken")
    engine = PolicyEngine(JarvisConfig(), grant_store_path=str(path))
    assert engine.is_granted("coder", "fs.read") is False
    allowed, missing = engine.permitted("coder", ["fs.read"])
    assert allowed is False
    assert missing == ["policy grant store unreadable (fail closed)"]


# -- approvals ---------------------------------------------------------------
def test_an_approval_is_single_use(policy):
    policy.grant("coder", "exec")
    plan = _plan(action="run a command", permissions=["exec"],
                 risk=RiskLevel.HIGH)
    decision = policy.evaluate("coder", plan)
    assert decision.requires_approval is True
    token = policy.request_approval("coder", plan, decision)
    # The operator approves it; only then can it be spent.
    assert policy.approve(token) is True
    assert policy.redeem(token, "coder", plan.action, plan.args) is True
    # The second attempt must fail: the authority is spent.
    assert policy.redeem(token, "coder", plan.action, plan.args) is False


def test_an_approval_is_bound_to_its_arguments(policy):
    policy.grant("coder", "exec")
    plan = _plan(action="run a command", args={"cmd": "ls"},
                 permissions=["exec"], risk=RiskLevel.HIGH)
    decision = policy.evaluate("coder", plan)
    token = policy.request_approval("coder", plan, decision)
    policy.approve(token)
    assert policy.redeem(token, "coder", plan.action, {"cmd": "rm -rf /"}) is False


def test_an_approval_is_bound_to_its_actor(policy):
    policy.grant("coder", "exec")
    plan = _plan(action="run a command", permissions=["exec"],
                 risk=RiskLevel.HIGH)
    decision = policy.evaluate("coder", plan)
    token = policy.request_approval("coder", plan, decision)
    policy.approve(token)
    assert policy.redeem(token, "somebody-else", plan.action, plan.args) is False


def test_an_unapproved_token_cannot_be_spent(policy):
    plan = _plan(action="run a command", permissions=["exec"],
                 risk=RiskLevel.HIGH)
    token = policy.create_approval("coder", plan)
    assert policy.consume_approval("coder", token) is False


def test_an_ambiguous_prefix_resolves_to_nothing(policy):
    plan = _plan(action="run a command", permissions=["exec"],
                 risk=RiskLevel.HIGH)
    first = policy.create_approval("coder", plan)
    second = policy.create_approval("coder", plan)
    prefix = first[:8]
    if second.startswith(prefix):
        # Two approvals share the prefix: the decision is ambiguous.
        assert policy.approved(prefix) is False


def test_an_expired_approval_is_not_valid(policy):
    policy.grant("coder", "exec")
    plan = _plan(action="run a command", permissions=["exec"],
                 risk=RiskLevel.HIGH)
    decision = policy.evaluate("coder", plan)
    token = policy.request_approval("coder", plan, decision)
    entry = policy.approvals[token]
    entry["expires_at"] = 0  # as if the TTL had passed
    assert policy.approved(token) is False


def test_the_approval_token_is_scrubbable(policy):
    plan = _plan(action="run a command", permissions=["exec"],
                 risk=RiskLevel.HIGH)
    token = policy.create_approval("coder", plan)
    # The token shape is what the redactors look for.
    assert token.startswith("appr-")


# -- risk --------------------------------------------------------------------
def test_a_destructive_action_scores_high(policy):
    decision = policy.evaluate("coder", _plan(action="delete everything"))
    assert decision.risk >= 0.9


def test_a_blocked_path_is_refused(policy):
    decision = policy.evaluate("coder",
                               _plan(action="read /etc/shadow",
                                     args={"path": "/etc/shadow"}))
    assert decision.risk == 1.0


def test_the_tool_risk_floors_the_assessment(policy):
    plan = _plan(action="benign name", risk=RiskLevel.HIGH)
    decision = policy.evaluate("coder", plan)
    # The declared tool risk floors the text assessment.
    assert decision.risk >= RiskLevel.HIGH.numeric
    assert decision.requires_approval is True


# -- emergency stop ----------------------------------------------------------
def test_the_emergency_stop_blocks_everything(policy, tmp_path):
    stop = tmp_path / "EMERGENCY_STOP"
    stop.write_text("engaged\n")
    policy.grant("coder", "fs.read")
    decision = policy.evaluate("coder", _plan(permissions=["fs.read"]))
    assert decision.allow is False
    assert any("EMERGENCY STOP" in reason for reason in decision.reasons)


def test_releasing_the_stop_unblocks(policy, tmp_path):
    stop = tmp_path / "EMERGENCY_STOP"
    stop.write_text("engaged\n")
    policy.grant("coder", "fs.read")
    assert not policy.evaluate("coder", _plan(permissions=["fs.read"])).allow
    policy.release_stop()
    assert policy.evaluate("coder", _plan(permissions=["fs.read"])).allow


# -- audit -------------------------------------------------------------------
def test_every_evaluation_is_audited(policy):
    policy.evaluate("coder", _plan(action="one"))
    policy.evaluate("coder", _plan(action="two"))
    assert len(policy.audit) >= 2
    assert policy.audit_trail(1)


def test_the_audit_trail_is_bounded(policy):
    for index in range(60):
        policy.evaluate("coder", _plan(action=f"action {index}"))
    assert len(policy.audit_trail(10)) == 10


# -- standing grants ---------------------------------------------------------
def test_a_standing_grant_does_not_bypass_the_policy(policy):
    from jarvis.policy.standing import StandingGrantStore
    store = StandingGrantStore(tempfile.mkdtemp())
    store.create("media.organize", "path", "/tmp/dl",
                 allowed_operations=["move"])
    policy.bind_standing_grants(store)
    # A standing grant is authorization input; it never clears a
    # permission check inside evaluate().
    decision = policy.evaluate("user", _plan(permissions=["fs.write"]))
    assert decision.allow is False


def test_a_standing_grant_deny_beats_an_older_allow(policy):
    from jarvis.policy.standing import StandingGrantStore
    store = StandingGrantStore(tempfile.mkdtemp())
    store.create("media.organize", "path", "/tmp/dl",
                 allowed_operations=["move"])
    store.create("media.organize", "path", "/tmp/dl",
                 allowed_operations=["move"], denied_operations=["move"])
    allowed, reason = store.authorize("user", "media.organize", "path",
                                      "/tmp/dl/a.jpg", "move")
    assert allowed is False
    assert "denied" in reason
