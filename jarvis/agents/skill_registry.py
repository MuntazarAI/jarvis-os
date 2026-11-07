"""Skill evolution system for Stark AI agents.

Agents can request to learn new tools/capabilities. Each new skill:
- Must be approved by PolicyEngine before being granted
- Is versioned and audited
- Can be revoked at any time
- Is tracked per-agent with a proficiency level

Nothing here grants automatic capability growth. Every new skill
requires explicit PolicyEngine approval.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from ..core.logging import get_module_logger
from ..core.types import ActionPlan, RiskLevel
from ..policy.policy import PolicyEngine

log = get_module_logger(__name__)


@dataclass
class Skill:
    """A learned capability held by an agent."""
    name: str
    description: str
    tool_names: list[str] = field(default_factory=list)
    required_permissions: list[str] = field(default_factory=list)
    version: int = 1
    proficiency: float = 0.0  # 0.0 = novice, 1.0 = expert
    granted_at: float = field(default_factory=time.monotonic)
    last_used_at: float | None = None
    use_count: int = 0
    approved_by: str = ""

    def mark_used(self) -> None:
        self.use_count += 1
        self.last_used_at = time.monotonic()
        # Slowly increase proficiency with use, capped at 1.0
        self.proficiency = min(1.0, self.proficiency + 0.01)


@dataclass
class SkillRequest:
    """A pending request to learn a skill."""
    request_id: str
    agent_id: str
    skill_name: str
    description: str
    tool_names: list[str]
    required_permissions: list[str]
    status: str = "pending"  # pending, approved, denied, revoked
    requested_at: float = field(default_factory=time.monotonic)
    decided_at: float | None = None
    decided_by: str = ""


class SkillRegistry:
    """Manages skill learning and evolution for Stark AI agents.

    Every skill grant requires PolicyEngine approval. Skills are
    versioned, audited, and can be revoked.
    """

    def __init__(self, policy: PolicyEngine) -> None:
        self.policy = policy
        self.skills: dict[str, dict[str, Skill]] = {}  # agent_id -> skill_name -> Skill
        self.pending_requests: dict[str, SkillRequest] = {}  # request_id -> SkillRequest
        self._request_counter: int = 0

    # -- request a skill ----------------------------------------------------

    def request_skill(
        self,
        agent_id: str,
        skill_name: str,
        description: str,
        tool_names: list[str] | None = None,
        required_permissions: list[str] | None = None,
    ) -> dict[str, Any]:
        """Ask PolicyEngine for permission to learn a new skill."""
        tool_names = tool_names or []
        required_permissions = required_permissions or []

        self._request_counter += 1
        request_id = f"skill-{self._request_counter}"

        # Build the policy plan
        plan = ActionPlan(
            action=f"skill.learn.{skill_name}",
            args={
                "agent_id": agent_id,
                "skill_name": skill_name,
                "description": description,
                "tool_names": tool_names,
                "required_permissions": required_permissions,
            },
            required_permissions=required_permissions,
            risk=RiskLevel.MEDIUM,
        )

        decision = self.policy.evaluate(agent_id, plan)

        if not decision.allow:
            return {
                "ok": False,
                "request_id": request_id,
                "agent_id": agent_id,
                "skill_name": skill_name,
                "reason": "; ".join(decision.reasons),
                "risk": decision.risk,
            }

        # Create the skill grant
        skill = Skill(
            name=skill_name,
            description=description,
            tool_names=list(tool_names),
            required_permissions=list(required_permissions),
            version=1,
            proficiency=0.0,
            granted_at=time.monotonic(),
            approved_by=decision.decided_at and "policy-engine" or "policy-engine",
        )
        self.skills.setdefault(agent_id, {})[skill_name] = skill

        request = SkillRequest(
            request_id=request_id,
            agent_id=agent_id,
            skill_name=skill_name,
            description=description,
            tool_names=list(tool_names),
            required_permissions=list(required_permissions),
            status="approved",
            decided_at=time.monotonic(),
        )
        self.pending_requests[request_id] = request

        log.info("Skill granted",
                 agent_id=agent_id, skill_name=skill_name,
                 version=1, tools=tool_names)

        return {
            "ok": True,
            "request_id": request_id,
            "agent_id": agent_id,
            "skill_name": skill_name,
            "version": 1,
            "proficiency": 0.0,
        }

    # -- use a skill --------------------------------------------------------

    def has_skill(self, agent_id: str, skill_name: str) -> bool:
        skill = self.skills.get(agent_id, {}).get(skill_name)
        return skill is not None

    def use_skill(self, agent_id: str, skill_name: str) -> bool:
        """Mark a skill as used (increases proficiency). Returns True if agent has it."""
        skill = self.skills.get(agent_id, {}).get(skill_name)
        if skill is None:
            return False
        skill.mark_used()
        log.debug("Skill used", agent_id=agent_id, skill_name=skill_name,
                  proficiency=skill.proficiency, use_count=skill.use_count)
        return True

    # -- evolve a skill -----------------------------------------------------

    def evolve_skill(
        self,
        agent_id: str,
        skill_name: str,
        new_tools: list[str] | None = None,
        new_permissions: list[str] | None = None,
        version_bump: bool = True,
    ) -> dict[str, Any]:
        """Request to evolve an existing skill (add tools, permissions, bump version).

        Requires PolicyEngine approval for any new tools/permissions.
        """
        skill = self.skills.get(agent_id, {}).get(skill_name)
        if skill is None:
            return {
                "ok": False,
                "agent_id": agent_id,
                "skill_name": skill_name,
                "reason": "skill not found",
            }

        new_tools = new_tools or []
        new_permissions = new_permissions or []

        # Check if anything actually changed
        if not new_tools and not new_permissions and not version_bump:
            return {
                "ok": False,
                "agent_id": agent_id,
                "skill_name": skill_name,
                "reason": "no changes requested",
            }

        # Policy check for new tools/permissions
        all_permissions = list(set(skill.required_permissions + new_permissions))
        plan = ActionPlan(
            action=f"skill.evolve.{skill_name}",
            args={
                "agent_id": agent_id,
                "skill_name": skill_name,
                "new_tools": new_tools,
                "new_permissions": new_permissions,
                "version_bump": version_bump,
            },
            required_permissions=new_permissions,
            risk=RiskLevel.MEDIUM,
        )

        decision = self.policy.evaluate(agent_id, plan)

        if not decision.allow:
            return {
                "ok": False,
                "agent_id": agent_id,
                "skill_name": skill_name,
                "reason": "; ".join(decision.reasons),
                "risk": decision.risk,
            }

        # Apply evolution
        if new_tools:
            skill.tool_names = list(set(skill.tool_names + new_tools))
        if new_permissions:
            skill.required_permissions = all_permissions
        if version_bump:
            skill.version += 1

        log.info("Skill evolved",
                 agent_id=agent_id, skill_name=skill_name,
                 version=skill.version, tools=skill.tool_names)

        return {
            "ok": True,
            "agent_id": agent_id,
            "skill_name": skill_name,
            "version": skill.version,
            "tools": skill.tool_names,
            "permissions": skill.required_permissions,
        }

    # -- list skills --------------------------------------------------------

    def list_skills(self, agent_id: str) -> list[dict[str, Any]]:
        """List all skills for an agent."""
        out: list[dict[str, Any]] = []
        for name, skill in self.skills.get(agent_id, {}).items():
            out.append({
                "name": skill.name,
                "description": skill.description,
                "version": skill.version,
                "proficiency": round(skill.proficiency, 3),
                "use_count": skill.use_count,
                "tools": skill.tool_names,
                "permissions": skill.required_permissions,
                "granted_at": skill.granted_at,
                "last_used_at": skill.last_used_at,
            })
        return out

    # -- revoke -------------------------------------------------------------

    def revoke_skill(self, agent_id: str, skill_name: str) -> bool:
        """Revoke a skill from an agent."""
        agent_skills = self.skills.get(agent_id, {})
        if skill_name in agent_skills:
            del agent_skills[skill_name]
            log.info("Skill revoked", agent_id=agent_id, skill_name=skill_name)
            return True
        return False