"""Bounded self-correction, tool intelligence, skills (5.0).

SelfCorrection: diagnose -> alternatives -> replan, with hard budgets
on retries, replans, and time. Never loops forever; exhaustion fails
safely with a diagnosis.

ToolSelector proposes tools (never executes): capability/risk/cost/
availability matching over ToolRegistry specs. ToolChain validates
typed composition without running anything.

Skill: reusable verified workflows. Skills NEVER grant permissions;
automation use requires an explicit, separately audited approval.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable


def _utcnow() -> float:
    return time.time()


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class CorrectionError(ValueError):
    """Malformed correction/skill/tool request."""


@dataclass
class CorrectionAttempt:
    attempt: int
    diagnosis: str
    alternative: str
    ok: bool
    detail: str = ""
    at: float = field(default_factory=_utcnow)


@dataclass
class CorrectionResult:
    ok: bool
    attempts: list[CorrectionAttempt] = field(default_factory=list)
    diagnosis: str = ""
    exhausted: bool = False


class SelfCorrection:
    """Bounded failure recovery driver."""

    def __init__(self, *, max_retries: int = 2, max_replans: int = 1,
                 max_time_s: float = 60.0) -> None:
        self.max_retries = max(0, max_retries)
        self.max_replans = max(0, max_replans)
        self.max_time_s = max(1.0, max_time_s)

    def run(self, attempt: Callable[[int, str], dict[str, Any]],
              diagnose: Callable[[dict[str, Any]], str] | None = None,
              alternatives: list[str] | None = None) -> CorrectionResult:
        """Try, diagnose, retry alternatives. Bounded always."""
        deadline = time.monotonic() + self.max_time_s
        attempts: list[CorrectionAttempt] = []
        options = list(alternatives or ["retry same action"])
        plan = "original plan"
        replans = 0
        attempt_no = 0
        while True:
            if time.monotonic() > deadline:
                return CorrectionResult(
                    ok=False, attempts=attempts,
                    diagnosis="budget exhausted: time",
                    exhausted=True)
            try:
                out = attempt(attempt_no, plan) or {}
            except Exception as exc:
                out = {"ok": False,
                       "error": f"{type(exc).__name__}: {exc}"[:200]}
            if out.get("ok"):
                return CorrectionResult(ok=True, attempts=attempts,
                                        diagnosis="recovered")
            diagnosis = diagnose(out) if diagnose else str(
                out.get("error", "failed"))[:200]
            if attempt_no >= self.max_retries:
                return CorrectionResult(
                    ok=False, attempts=attempts, diagnosis=diagnosis,
                    exhausted=True)
            if attempt_no >= len(options) - 1 and replans >= self.max_replans:
                attempts.append(CorrectionAttempt(
                    attempt=attempt_no, diagnosis=diagnosis,
                    alternative="(none left)", ok=False,
                    detail="retry/replan budget exhausted"))
                return CorrectionResult(
                    ok=False, attempts=attempts, diagnosis=diagnosis,
                    exhausted=True)
            if attempt_no >= len(options) - 1:
                replans += 1
                plan = f"revised plan v{replans}"
            alternative = options[min(attempt_no + 1, len(options) - 1)]
            attempts.append(CorrectionAttempt(
                attempt=attempt_no, diagnosis=diagnosis,
                alternative=alternative, ok=False,
                detail=str(out.get("error", ""))[:200]))
            attempt_no += 1


@dataclass
class ToolProposal:
    tool: str
    capability: str
    risk: str
    cost: float
    latency_ms: float | None
    reliability: float
    authorized: bool
    reasons: list[str] = field(default_factory=list)


class ToolSelector:
    """Propose-only tool matching. Execution is never performed here."""

    def __init__(self, registry: Any = None, policy: Any = None,
                 actor: str = "cognitive-loop") -> None:
        self.registry = registry
        self.policy = policy
        self.actor = actor

    def propose(self, capability: str, *,
                max_risk: str = "high") -> list[ToolProposal]:
        """Ranked proposals for a capability. No execution, ever."""
        if self.registry is None:
            return []
        order = {"safe": 0, "low": 1, "medium": 2, "high": 3}
        ceiling = order.get(max_risk, 3)
        proposals: list[ToolProposal] = []
        tools = getattr(self.registry, "_tools", {}) or {}
        for name, tool in tools.items():
            spec = getattr(tool, "spec", None)
            if spec is None:
                continue
            risk = str(getattr(getattr(spec, "risk", ""), "value",
                               getattr(spec, "risk", "low")))
            if order.get(risk, 3) > ceiling:
                continue
            perms = list(getattr(spec, "required_permissions", []) or [])
            authorized, reasons = True, []
            if self.policy is not None and perms:
                try:
                    authorized, missing = self.policy.permitted(
                        self.actor, perms)
                    if not authorized:
                        reasons = [f"lacks {missing}"]
                except Exception as exc:
                    authorized, reasons = False, [str(exc)[:120]]
            proposals.append(ToolProposal(
                tool=name, capability=capability, risk=risk,
                cost=float(getattr(spec, "timeout", 30.0) or 30.0),
                latency_ms=None, reliability=0.5, authorized=authorized,
                reasons=reasons))
        proposals.sort(key=lambda p: (not p.authorized, p.cost, p.tool))
        return proposals

    def validate_chain(self, tools: list[str]) -> dict[str, Any]:
        """Check a tool sequence for permission/risk/dependency issues
        without running anything."""
        if len(tools) > 8:
            return {"valid": False, "issues": ["chain exceeds 8 tools"]}
        issues: list[str] = []
        seen: set[str] = set()
        registry_tools = getattr(self.registry, "_tools", {}) or {} \
            if self.registry else {}
        for name in tools:
            if name in seen:
                issues.append(f"duplicate tool in chain: {name}")
            seen.add(name)
            tool = registry_tools.get(name)
            if tool is None:
                issues.append(f"unknown tool: {name}")
                continue
            spec = getattr(tool, "spec", None)
            risk = str(getattr(getattr(spec, "risk", ""), "value", "low"))
            if risk == "high":
                issues.append(f"high-risk tool in chain: {name}")
        return {"valid": not issues, "issues": issues}


class SkillStatus(str, Enum):
    DRAFT = "draft"
    VERIFIED = "verified"
    APPROVED = "approved"
    RETIRED = "retired"


@dataclass
class Skill:
    skill_id: str = field(default_factory=lambda: _new_id("skl"))
    name: str = ""
    goal: str = ""
    prerequisites: list[str] = field(default_factory=list)
    steps: list[dict[str, Any]] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    permissions_required: list[str] = field(default_factory=list)
    expected_outputs: list[str] = field(default_factory=list)
    verification: dict[str, Any] = field(default_factory=dict)
    evidence_refs: list[str] = field(default_factory=list)
    successes: int = 0
    failures: int = 0
    version: int = 1
    status: SkillStatus = SkillStatus.DRAFT
    created_at: float = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        if isinstance(self.status, str):
            try:
                self.status = SkillStatus(self.status)
            except ValueError:
                raise CorrectionError(f"invalid status: {self.status!r}")
        if not self.name:
            raise CorrectionError("skill needs a name")
        if len(self.steps) > 12:
            raise CorrectionError("skill exceeds 12 steps")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


class SkillStore:
    """Durable skills. Automation use needs explicit approval recorded
    on the skill; approval NEVER grants permissions (checked by the
    existing policy layer at execution time, as always)."""

    FILENAME = "cognitive-skills.json"

    def __init__(self, home: str | Path | None) -> None:
        self.home = Path(home) if home else None
        self._skills: dict[str, Skill] = {}
        self.load()

    @property
    def path(self) -> Path | None:
        if self.home is None:
            return None
        return self.home / self.FILENAME

    def load(self) -> int:
        path = self.path
        if path is None or not path.exists():
            return 0
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return 0
        if not isinstance(raw, dict):
            return 0
        loaded = 0
        for sid, item in (raw.get("skills") or {}).items():
            if not isinstance(item, dict):
                continue
            try:
                skill = Skill(**{k: v for k, v in item.items()
                                 if k in Skill.__dataclass_fields__})
            except (CorrectionError, TypeError):
                continue
            if skill.skill_id != sid:
                continue
            self._skills[sid] = skill
            loaded += 1
        return loaded

    def save(self) -> None:
        path = self.path
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".cognitive-skills-",
                                       dir=str(path.parent))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump({"version": 1, "skills": {
                        sid: skill.to_dict()
                        for sid, skill in self._skills.items()}},
                        handle, indent=2, sort_keys=True, default=str)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp, path)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
        except OSError:
            pass

    def register(self, skill: Skill) -> Skill:
        self.load()
        self._skills[skill.skill_id] = skill
        self.save()
        return skill

    def get(self, skill_id: str) -> Skill | None:
        self.load()
        return self._skills.get(skill_id)

    def approve(self, skill_id: str, *, by: str = "") -> bool:
        """Mark verified for automation. Grants NOTHING by itself."""
        self.load()
        skill = self._skills.get(skill_id)
        if skill is None or skill.status != SkillStatus.VERIFIED:
            return False
        skill.status = SkillStatus.APPROVED
        skill.version += 1
        self.save()
        return True

    def record_use(self, skill_id: str, ok: bool) -> bool:
        self.load()
        skill = self._skills.get(skill_id)
        if skill is None:
            return False
        if ok:
            skill.successes += 1
        else:
            skill.failures += 1
        self.save()
        return True


__all__ = [
    "CorrectionAttempt",
    "CorrectionError",
    "CorrectionResult",
    "SelfCorrection",
    "Skill",
    "SkillStatus",
    "SkillStore",
    "ToolProposal",
    "ToolSelector",
]
