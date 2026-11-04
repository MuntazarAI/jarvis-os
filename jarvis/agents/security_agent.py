"""Security Agent — guards every tool/action before execution.

Sits between the Supervisor and tool execution. Every proposed action is
evaluated through PolicyEngine (risk assessment + permission check +
emergency stop + local-only mode). Produces an allow/deny decision with
full audit trail. When an action requires human approval, creates a
persistent approval token so the operator can approve/deny via CLI.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from ..core.logging import get_module_logger
from ..core.types import ActionPlan, RiskLevel
from ..policy.policy import PolicyEngine, PolicyDecision

log = get_module_logger(__name__)


@dataclass
class SecurityVerdict:
    """Result of a security evaluation."""
    allowed: bool
    decision: PolicyDecision
    actor: str
    action: str
    args: dict[str, Any]
    evaluated_at: float = field(default_factory=time.time)
    # Populated when the action is allowed but requires human approval.
    # The operator can approve/deny via `jarvis device approvals ...`.
    approval_token: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "decision": self.decision.to_dict(),
            "actor": self.actor,
            "action": self.action,
            "args": self.args,
            "evaluated_at": self.evaluated_at,
            "approval_token": self.approval_token,
        }

    def needs_approval(self) -> bool:
        """True if this action is allowed but waiting for human approval."""
        return bool(self.approval_token)


class SecurityAgent:
    """Validates actions against PolicyEngine before execution.

    Never bypasses PolicyEngine. Every verdict is audited. Denied
    actions include the policy reasons so the caller can explain why.
    Actions that are allowed but require approval get a persistent
    approval token for operator review via CLI.
    """

    def __init__(self, policy: PolicyEngine | None = None,
                 actor: str = "security") -> None:
        self.policy = policy or PolicyEngine()
        self.actor = actor
        self.verdicts: list[SecurityVerdict] = []
        self.blocked_count = 0
        self.allowed_count = 0
        self.pending_count = 0

    def evaluate(self, action: str, args: dict[str, Any] | None = None,
                 context: dict[str, Any] | None = None) -> SecurityVerdict:
        """Evaluate a single action through PolicyEngine.

        If the action is allowed but requires approval, a persistent
        approval token is created so the operator can review it via CLI.
        """
        args = args or {}
        context = context or {}

        # Build a minimal ActionPlan from the raw action for risk assessment
        plan = ActionPlan(action=action, args=args)

        decision = self.policy.evaluate(self.actor, plan)

        approval_token = ""
        if decision.allow and decision.requires_approval:
            # Create a persistent approval token for operator review.
            approval_token = self.policy.request_approval(
                self.actor, plan, decision)
            self.pending_count += 1
            log.info("Security: approval requested",
                     action=action, actor=self.actor,
                     token=approval_token[:8], risk=decision.risk,
                     reasons=decision.reasons)

        verdict = SecurityVerdict(
            allowed=decision.allow,
            decision=decision,
            actor=self.actor,
            action=action,
            args=args,
            approval_token=approval_token,
        )
        self.verdicts.append(verdict)

        if decision.allow and not approval_token:
            self.allowed_count += 1
            log.info("Security: action allowed",
                     action=action, actor=self.actor,
                     risk=decision.risk, risk_level=decision.risk_level.value)
        elif decision.allow and approval_token:
            log.info("Security: action approved-pending",
                     action=action, actor=self.actor,
                     token=approval_token[:8],
                     risk=decision.risk)
        else:
            self.blocked_count += 1
            log.warning("Security: action denied",
                        action=action, actor=self.actor,
                        reasons=decision.reasons,
                        risk=decision.risk)

        return verdict

    def evaluate_plan(self, plan: ActionPlan,
                      context: dict[str, Any] | None = None) -> SecurityVerdict:
        """Evaluate a full ActionPlan through PolicyEngine."""
        context = context or {}

        decision = self.policy.evaluate(self.actor, plan)

        approval_token = ""
        if decision.allow and decision.requires_approval:
            approval_token = self.policy.request_approval(
                self.actor, plan, decision)
            self.pending_count += 1

        verdict = SecurityVerdict(
            allowed=decision.allow,
            decision=decision,
            actor=self.actor,
            action=plan.action,
            args=plan.args,
            approval_token=approval_token,
        )
        self.verdicts.append(verdict)

        if decision.allow:
            self.allowed_count += 1
        else:
            self.blocked_count += 1

        return verdict

    def requires_approval(self, verdict: SecurityVerdict) -> bool:
        """True if the verdict needs human approval before execution."""
        return verdict.needs_approval()

    def check_approval(self, token: str) -> bool:
        """Check if a pending approval has been granted (without consuming it)."""
        return self.policy.approved(token)

    def status(self) -> dict[str, Any]:
        return {
            "actor": self.actor,
            "total_evaluations": len(self.verdicts),
            "allowed": self.allowed_count,
            "blocked": self.blocked_count,
            "pending_approvals": self.pending_count,
            "recent_decisions": [v.to_dict() for v in self.verdicts[-10:]],
        }

    def clear_history(self) -> None:
        self.verdicts.clear()
        self.blocked_count = 0
        self.allowed_count = 0
        self.pending_count = 0