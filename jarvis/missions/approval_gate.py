"""Mission Approval Gate — policy-gated mission step execution.

Sits between MissionRuntime and tool execution. Every proposed mission
step is evaluated through PolicyEngine. Steps that require approval
create a persistent token and pause the mission; the operator approves
or denies via `jarvis device approvals approve/deny <token>`.

Never bypasses PolicyEngine. All verdicts are audited.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from ..core.logging import get_module_logger
from ..core.types import ActionPlan
from ..policy.policy import PolicyEngine, PolicyDecision

log = get_module_logger(__name__)


@dataclass
class MissionStepVerdict:
    """Result of a security evaluation for a mission step."""
    allowed: bool
    decision: PolicyDecision
    actor: str
    action: str
    args: dict[str, Any]
    mission_id: str = ""
    objective_id: str = ""
    step_index: int = 0
    evaluated_at: float = field(default_factory=time.time)
    # Populated when the action is allowed but requires human approval.
    approval_token: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "decision": self.decision.to_dict(),
            "actor": self.actor,
            "action": self.action,
            "args": self.args,
            "mission_id": self.mission_id,
            "objective_id": self.objective_id,
            "step_index": self.step_index,
            "evaluated_at": self.evaluated_at,
            "approval_token": self.approval_token,
        }

    def needs_approval(self) -> bool:
        """True if this step is allowed but waiting for human approval."""
        return bool(self.approval_token)


class MissionApprovalGate:
    """Validates mission steps against PolicyEngine before execution.

    Every delegated mission step passes through PolicyEngine (risk
    assessment + permission check + emergency stop + local-only mode).
    Steps that require approval create a persistent token and pause the
    mission.
    """

    def __init__(self, policy: PolicyEngine | None = None,
                 actor: str = "mission-manager") -> None:
        self.policy = policy or PolicyEngine()
        self.actor = actor
        self.verdicts: list[MissionStepVerdict] = []
        self.blocked_count = 0
        self.allowed_count = 0
        self.pending_count = 0

    def evaluate(self, action: str, args: dict[str, Any] | None = None,
                 mission_id: str = "", objective_id: str = "",
                 step_index: int = 0,
                 context: dict[str, Any] | None = None) -> MissionStepVerdict:
        """Evaluate a mission step through PolicyEngine.

        If the action is allowed but requires approval, a persistent
        approval token is created for operator review via CLI.
        """
        args = args or {}
        context = context or {}

        plan = ActionPlan(action=action, args=args)
        decision = self.policy.evaluate(self.actor, plan)

        approval_token = ""
        if decision.allow and decision.requires_approval:
            approval_token = self.policy.request_approval(
                self.actor, plan, decision)
            self.pending_count += 1
            log.info("Mission approval requested",
                     mission_id=mission_id, objective_id=objective_id,
                     step_index=step_index, token=approval_token[:8],
                     action=action, risk=decision.risk,
                     reasons=decision.reasons)

        verdict = MissionStepVerdict(
            allowed=decision.allow,
            decision=decision,
            actor=self.actor,
            action=action,
            args=args,
            mission_id=mission_id,
            objective_id=objective_id,
            step_index=step_index,
            approval_token=approval_token,
        )
        self.verdicts.append(verdict)

        if decision.allow and not approval_token:
            self.allowed_count += 1
            log.info("Mission step allowed",
                     mission_id=mission_id, step_index=step_index,
                     action=action, risk=decision.risk)
        elif decision.allow and approval_token:
            log.info("Mission step approved-pending",
                     mission_id=mission_id, step_index=step_index,
                     token=approval_token[:8])
        else:
            self.blocked_count += 1
            log.warning("Mission step denied",
                        mission_id=mission_id, step_index=step_index,
                        reasons=decision.reasons, risk=decision.risk)

        return verdict

    def check_approval(self, token: str) -> bool:
        """Check if a pending approval has been granted (without consuming)."""
        return self.policy.approved(token)

    def pending(self) -> list[dict[str, Any]]:
        """List pending mission approvals with tokens and details."""
        out = []
        for v in self.verdicts:
            if v.approval_token:
                out.append({
                    "token": v.approval_token,
                    "token_prefix": v.approval_token[:8],
                    "mission_id": v.mission_id,
                    "objective_id": v.objective_id,
                    "step_index": v.step_index,
                    "action": v.action,
                    "actor": v.actor,
                    "risk": v.decision.risk,
                    "risk_level": v.decision.risk_level.value,
                    "reasons": v.decision.reasons,
                    "evaluated_at": v.evaluated_at,
                })
        return out

    def status(self) -> dict[str, Any]:
        return {
            "actor": self.actor,
            "total_evaluations": len(self.verdicts),
            "allowed": self.allowed_count,
            "blocked": self.blocked_count,
            "pending_approvals": self.pending_count,
            "pending": self.pending(),
        }

    def clear_history(self) -> None:
        self.verdicts.clear()
        self.blocked_count = 0
        self.allowed_count = 0
        self.pending_count = 0