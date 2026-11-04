"""Controlled internet access for Stark AI agents.

All outbound requests are:
- Gated through PolicyEngine (every call requires approval)
- Limited to an allowlisted set of domains
- Rate-limited per agent
- Audited for traceability

Nothing here grants unbounded internet access. Agents must request
permission for each domain, and PolicyEngine decides whether to allow it.
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
class InternetGrant:
    """A time-bounded grant for an agent to reach a specific domain."""
    agent_id: str
    domain: str
    allowed_until: float
    max_requests_per_hour: int
    requests_made: int = 0
    last_request_at: float | None = None

    def is_expired(self) -> bool:
        return time.monotonic() > self.allowed_until

    def is_rate_limited(self) -> bool:
        if self.last_request_at is None:
            return False
        # Simple hourly window reset
        elapsed = time.monotonic() - (self.last_request_at or 0)
        if elapsed > 3600.0:
            self.requests_made = 0
        return self.requests_made >= self.max_requests_per_hour

    def record_request(self) -> None:
        self.requests_made += 1
        self.last_request_at = time.monotonic()


class InternetAccess:
    """Controlled internet access manager.

    Agents request access to a domain; PolicyEngine evaluates the
    request. Grants are time-bounded and rate-limited.
    """

    DEFAULT_MAX_REQUESTS_PER_HOUR = 60
    DEFAULT_GRANT_SECONDS = 3600.0  # 1 hour

    def __init__(
        self,
        policy: PolicyEngine,
        allowed_domains: set[str] | None = None,
    ) -> None:
        self.policy = policy
        # Domains agents are allowed to request (still need per-request approval)
        self.allowed_domains: set[str] = allowed_domains or {
            # Safe, read-only reference domains
            "pypi.org",
            "docs.python.org",
            "github.com",
            "raw.githubusercontent.com",
            "developer.mozilla.org",
            "stackoverflow.com",
        }
        self.grants: dict[str, dict[str, InternetGrant]] = {}  # agent_id -> domain -> grant

    # -- request access -----------------------------------------------------

    def request_domain_access(
        self,
        agent_id: str,
        domain: str,
        max_requests_per_hour: int | None = None,
        grant_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Ask PolicyEngine for permission to reach a domain.

        Returns a grant if approved; otherwise returns a denial.
        """
        max_rph = max_requests_per_hour or self.DEFAULT_MAX_REQUESTS_PER_HOUR
        grant_s = grant_seconds or self.DEFAULT_GRANT_SECONDS

        plan = ActionPlan(
            action=f"internet.access.{domain}",
            args={
                "agent_id": agent_id,
                "domain": domain,
                "max_requests_per_hour": max_rph,
                "grant_seconds": grant_s,
            },
            required_permissions=[f"internet:{domain}"],
            risk=RiskLevel.LOW,
        )

        decision = self.policy.evaluate(agent_id, plan)

        if not decision.allow:
            return {
                "ok": False,
                "agent_id": agent_id,
                "domain": domain,
                "reason": "; ".join(decision.reasons),
                "risk": decision.risk,
            }

        # Check domain is on the allowlist
        if domain not in self.allowed_domains:
            return {
                "ok": False,
                "agent_id": agent_id,
                "domain": domain,
                "reason": f"domain not on allowlist: {domain}",
                "risk": decision.risk,
            }

        # Create the grant
        grant = InternetGrant(
            agent_id=agent_id,
            domain=domain,
            allowed_until=time.monotonic() + grant_s,
            max_requests_per_hour=max_rph,
        )
        self.grants.setdefault(agent_id, {})[domain] = grant

        log.info("Internet grant created",
                 agent_id=agent_id, domain=domain,
                 max_requests_per_hour=max_rph, grant_seconds=grant_s)

        return {
            "ok": True,
            "agent_id": agent_id,
            "domain": domain,
            "allowed_until": grant.allowed_until,
            "max_requests_per_hour": max_rph,
            "expires_in_seconds": grant_s,
        }

    # -- check access -------------------------------------------------------

    def can_access(self, agent_id: str, domain: str) -> bool:
        """Return True if the agent has a valid, non-rate-limited grant."""
        agent_grants = self.grants.get(agent_id, {})
        grant = agent_grants.get(domain)
        if grant is None:
            return False
        if grant.is_expired():
            return False
        if grant.is_rate_limited():
            return False
        return True

    def record_request(self, agent_id: str, domain: str) -> None:
        """Mark that a request was made (for rate limiting)."""
        grant = self.grants.get(agent_id, {}).get(domain)
        if grant is not None:
            grant.record_request()

    def list_grants(self, agent_id: str) -> list[dict[str, Any]]:
        """List all active grants for an agent."""
        out: list[dict[str, Any]] = []
        for domain, grant in self.grants.get(agent_id, {}).items():
            out.append({
                "domain": domain,
                "allowed_until": grant.allowed_until,
                "expires_in_seconds": max(0, grant.allowed_until - time.monotonic()),
                "requests_made": grant.requests_made,
                "max_requests_per_hour": grant.max_requests_per_hour,
                "rate_limited": grant.is_rate_limited(),
                "expired": grant.is_expired(),
            })
        return out

    def revoke(self, agent_id: str, domain: str) -> bool:
        """Revoke an agent's grant for a domain."""
        agent_grants = self.grants.get(agent_id, {})
        if domain in agent_grants:
            del agent_grants[domain]
            log.info("Internet grant revoked", agent_id=agent_id, domain=domain)
            return True
        return False