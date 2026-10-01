"""Policy engine and risk assessment: every action gated before execution."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core.config import JarvisConfig
from ..core.types import ActionPlan, RiskLevel, now


@dataclass
class PolicyDecision:
    allow: bool
    risk: float
    risk_level: RiskLevel
    requires_approval: bool
    reasons: list[str] = field(default_factory=list)
    mitigations: list[str] = field(default_factory=list)
    decided_at: float = field(default_factory=now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allow": self.allow,
            "risk": round(self.risk, 4),
            "risk_level": self.risk_level.value,
            "requires_approval": self.requires_approval,
            "reasons": self.reasons,
            "mitigations": self.mitigations,
        }


class RiskEngine:
    """Impact × probability × reversibility scoring with blast-radius checks."""

    DESTRUCTIVE_VERBS = {"delete", "rm ", "format", "wipe", "drop", "shutdown",
                         "kill -9", "chmod -r", "chown -r", "mkfs"}

    def __init__(self, config: JarvisConfig | None = None) -> None:
        self.config = config or JarvisConfig()

    def assess(self, action: str, args: dict[str, Any] | None = None,
               context: dict[str, Any] | None = None) -> PolicyDecision:
        args = args or {}
        context = context or {}
        risk, reasons = 0.05, []
        low = action.lower()

        for verb in self.DESTRUCTIVE_VERBS:
            if verb in low:
                risk = max(risk, 0.95)
                reasons.append(f"destructive verb detected: {verb.strip()}")
        if "delete" in low and "system" in low:
            risk = max(risk, 0.9)
            reasons.append("system file deletion")
        # NOTE: apt/pip/npm match on word boundaries only — naive
        # substring matching false-positives on words like "capture".
        words = set(re.findall(r"[a-z0-9_]+", low))
        if "install" in low or words & {"apt", "pip", "npm", "dnf", "apk"}:
            risk = max(risk, 0.5)
            reasons.append("software installation changes system state")
        if any(k in low for k in ("network", "ssh", "curl", "wget", "fetch")):
            risk = max(risk, 0.4)
            reasons.append("network egress")
        if "write" in low or "create" in low:
            risk = max(risk, 0.35)
            reasons.append("filesystem mutation")

        blocked = [str(p) for p in self.config.policy.block_high_risk_paths]
        haystack = f"{action} {args}"
        for path in blocked:
            expanded = str(Path(path).expanduser())
            if expanded in haystack or path in haystack:
                risk = 1.0
                reasons.append(f"blocked path: {path}")

        if context.get("unverified_input"):
            risk = min(1.0, risk + 0.15)
            reasons.append("unverified external input in arguments")
        if context.get("quiet_hours"):
            risk = min(1.0, risk + 0.1)
            reasons.append("quiet hours — prefer deferring non-urgent actions")

        reversibility = 1.0 if risk < 0.4 else 0.3
        blast = self._blast_radius(action, args)
        risk = min(1.0, risk * (1.0 + 0.2 * blast))
        if reversibility < 0.5 and risk > 0.4:
            reasons.append("action may not be reversible")

        level = (
            RiskLevel.SAFE if risk < 0.1 else RiskLevel.LOW if risk < 0.35
            else RiskLevel.MEDIUM if risk < 0.6 else RiskLevel.HIGH
            if risk < 0.85 else RiskLevel.DESTRUCTIVE
        )
        threshold = self.config.policy.require_approval_above_risk
        return PolicyDecision(
            allow=risk < 1.0,
            risk=round(risk, 4),
            risk_level=level,
            requires_approval=risk >= threshold,
            reasons=reasons or ["routine low-risk action"],
            mitigations=self._mitigations(level, risk),
        )

    @staticmethod
    def _blast_radius(action: str, args: dict[str, Any]) -> float:
        text = f"{action} {args}".lower()
        if any(w in text for w in ("/etc", "/usr", "/boot", "c:\\windows", "system32")):
            return 1.0
        if any(w in text for w in ("home", "~", "documents", "projects")):
            return 0.5
        if "tmp" in text or "temp" in text:
            return 0.2
        return 0.3

    @staticmethod
    def _mitigations(level: RiskLevel, risk: float) -> list[str]:
        if level in (RiskLevel.HIGH, RiskLevel.DESTRUCTIVE):
            return ["require explicit user approval", "dry-run first",
                    "snapshot state for rollback", "record full audit trail"]
        if level == RiskLevel.MEDIUM:
            return ["confirm scope before executing", "record audit trail"]
        if risk >= 0.3:
            return ["record audit trail"]
        return []


class PolicyEngine:
    """Permission policies, privacy boundaries, approval workflow, audit."""

    def __init__(self, config: JarvisConfig | None = None) -> None:
        self.config = config or JarvisConfig()
        self.risk = RiskEngine(self.config)
        self.grants: dict[str, set[str]] = {}
        self.approvals: dict[str, dict[str, Any]] = {}
        self.audit: list[dict[str, Any]] = []

    # -- permissions -----------------------------------------------------
    def grant(self, actor: str, permission: str) -> None:
        self.grants.setdefault(actor, set()).add(permission)

    def revoke(self, actor: str, permission: str) -> None:
        self.grants.get(actor, set()).discard(permission)

    def permitted(self, actor: str, required: list[str]) -> tuple[bool, list[str]]:
        held = self.grants.get(actor, set())
        if "*" in held:
            return True, []
        missing = [p for p in required if p not in held]
        return (not missing), missing

    # -- evaluation ------------------------------------------------------
    def evaluate(self, actor: str, plan: ActionPlan) -> PolicyDecision:
        permitted, missing = self.permitted(actor, plan.required_permissions)
        decision = self.risk.assess(plan.action, plan.args)
        # The tool's declared risk floors the text assessment: a tool
        # marked HIGH can never score 0.05 just because its name is benign.
        floor = plan.risk.numeric if isinstance(plan.risk, RiskLevel) else 0.0
        if floor > decision.risk:
            decision.risk = round(floor, 4)
            decision.risk_level = RiskLevel.from_score(floor)
            decision.reasons.append(f"tool declares {plan.risk.value} risk")
            if floor >= self.config.policy.require_approval_above_risk:
                decision.requires_approval = True
        if not permitted:
            decision.allow = False
            decision.requires_approval = True
            decision.reasons.append(f"actor '{actor}' lacks permissions: {missing}")
            decision.mitigations.append("grant permission or escalate to authorized actor")
        if self.config.policy.local_only and self._is_egress(plan):
            decision.reasons.append("local-only mode: external egress restricted")
            if decision.risk < 0.5:
                decision.risk = 0.5
                decision.requires_approval = True
        if self._emergency_stop():
            decision.allow = False
            decision.reasons.append("EMERGENCY STOP engaged — all actions blocked")
        self._audit(actor, plan, decision)
        return decision

    @staticmethod
    def _is_egress(plan: ActionPlan) -> bool:
        text = f"{plan.action} {plan.args}".lower()
        return any(w in text for w in ("http", "curl", "ssh ", "upload", "publish", "send"))

    def _emergency_stop(self) -> bool:
        home = self.config.paths.home
        return (Path(home) / self.config.policy.emergency_stop_file).exists()

    def engage_stop(self) -> Path:
        target = Path(self.config.paths.home) / self.config.policy.emergency_stop_file
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"engaged at {now()}\n")
        return target

    def release_stop(self) -> bool:
        target = Path(self.config.paths.home) / self.config.policy.emergency_stop_file
        if target.exists():
            target.unlink()
            return True
        return False

    # -- approvals ---------------------------------------------------------
    def request_approval(self, actor: str, plan: ActionPlan,
                         decision: PolicyDecision) -> str:
        from ..core.types import new_id
        token = new_id("appr")
        self.approvals[token] = {
            "actor": actor, "action": plan.action, "args": plan.args,
            "risk": decision.risk, "requested_at": now(), "status": "pending",
        }
        return token

    def approve(self, token: str, by: str = "user") -> bool:
        entry = self.approvals.get(token)
        if not entry or entry["status"] != "pending":
            return False
        entry["status"] = "approved"
        entry["by"] = by
        entry["decided_at"] = now()
        return True

    def deny(self, token: str, by: str = "user") -> bool:
        entry = self.approvals.get(token)
        if not entry or entry["status"] != "pending":
            return False
        entry["status"] = "denied"
        entry["by"] = by
        entry["decided_at"] = now()
        return True

    def approved(self, token: str) -> bool:
        return self.approvals.get(token, {}).get("status") == "approved"

    # -- privacy -------------------------------------------------------------
    def privacy_check(self, data_kind: str, destination: str) -> tuple[bool, str]:
        if data_kind in ("secret", "credential", "private_key") and destination != "vault":
            return False, f"{data_kind} must only go to the vault, not {destination}"
        if destination in ("external", "cloud") and self.config.policy.local_only:
            return False, "local-only mode blocks external sharing"
        return True, "ok"

    # -- audit ---------------------------------------------------------------
    def _audit(self, actor: str, plan: ActionPlan, decision: PolicyDecision) -> None:
        if not self.config.policy.record_audit:
            return
        self.audit.append({
            "actor": actor, "action": plan.action, "args": plan.args,
            "allow": decision.allow, "risk": decision.risk,
            "requires_approval": decision.requires_approval,
            "reasons": decision.reasons, "at": now(),
        })

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.audit[-limit:]

    def conflicts(self) -> list[str]:
        notes = []
        if self.config.policy.local_only and self.config.models.cloud_enabled:
            notes.append("local-only mode conflicts with cloud_enabled models")
        return notes
