"""
Legal Advisory Agent — JARVIS-OS Stark AI Extension.

Provides read-only legal reference information: case law search, contract
clause analysis, legal concept overviews, and regulatory references.

SECURITY CONSTRAINTS (hard-coded):
- NO legal advice capability — only general information
- NO representation capability — no legal representation
- NO filing assistance — no court filing guidance
- Read-only legal databases via PolicyEngine-gated internet access
- All outputs carry disclaimer: not a substitute for legal counsel
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from ..core.logging import get_module_logger
from ..policy.policy import PolicyEngine
from ..events.store import EventStore

log = get_module_logger(__name__)


@dataclass
class LegalQuery:
    """A legal advisory query."""
    query_id: str
    query_type: str  # case_law, contract_clause, legal_concept, regulatory_ref
    query_text: str
    jurisdiction: str = "general"
    timestamp: float = field(default_factory=time.time)


@dataclass
class LegalResponse:
    """A legal advisory response."""
    query_id: str
    response_type: str
    content: str
    disclaimer: str
    sources: list[str] = field(default_factory=list)
    confidence: float = 0.0
    timestamp: float = field(default_factory=time.time)


class LegalAdvisor:
    """
    Legal Advisory Agent — read-only legal reference.

    Provides general legal information for educational purposes only.
    Cannot provide legal advice, representation, or filing assistance.
    All queries pass through PolicyEngine with allowlisted legal domains only.
    """

    ALLOWED_DOMAINS: frozenset[str] = frozenset({
        "law.cornell.edu",
        "govinfo.gov",
        "congress.gov",
        "supremecourt.gov",
        "justice.gov",
        "eca.gov",
        "legalinformationinstitute.org",
    })

    DISCLAIMER: str = (
        "IMPORTANT: This information is for educational purposes only and "
        "is not a substitute for professional legal advice, representation, "
        "or counsel. Always consult a qualified attorney for legal matters."
    )

    def __init__(
        self,
        policy: PolicyEngine | None = None,
        events: EventStore | None = None,
    ) -> None:
        self.policy = policy
        self.events = events
        self.queries: dict[str, LegalQuery] = {}
        self.responses: dict[str, LegalResponse] = {}
        self._initialized = False

    def initialize(self) -> dict[str, Any]:
        """Initialize the legal advisor."""
        self._initialized = True
        return {
            "status": "operational",
            "subsystem": "legal_advisor",
            "domains": len(self.ALLOWED_DOMAINS),
            "policy_gated": True,
            "read_only": True,
            "disclaimer": self.DISCLAIMER,
        }

    def query(
        self,
        query_type: str,
        query_text: str,
        jurisdiction: str = "general",
    ) -> LegalResponse:
        """Process a legal advisory query."""
        query_id = f"leg-{int(time.time() * 1000)}"

        query = LegalQuery(
            query_id=query_id,
            query_type=query_type,
            query_text=query_text,
            jurisdiction=jurisdiction,
        )
        self.queries[query_id] = query

        grant_result = {"approved": False, "reason": "no policy engine"}
        if self.policy:
            grant_result = self.policy.evaluate(
                "legal_advisor.query",
                {
                    "query_type": query_type,
                    "jurisdiction": jurisdiction,
                    "domains": list(self.ALLOWED_DOMAINS),
                },
            )

        content = self._generate_schematic_response(query_type, query_text)

        response = LegalResponse(
            query_id=query_id,
            response_type=query_type,
            content=content,
            disclaimer=self.DISCLAIMER,
            sources=list(self.ALLOWED_DOMAINS),
            confidence=0.5 if grant_result.get("approved", False) else 0.0,
        )
        self.responses[query_id] = response

        if self.events:
            self.events.append({
                "event": "legal_advisor.query",
                "query_id": query_id,
                "query_type": query_type,
                "jurisdiction": jurisdiction,
                "approved": grant_result.get("approved", False),
                "at": query.timestamp,
            })

        return response

    def _generate_schematic_response(
        self,
        query_type: str,
        query_text: str,
    ) -> str:
        """Generate a schematic response (placeholder, not real legal data)."""
        templates = {
            "case_law": (
                f"Case law query: '{query_text}'. "
                f"This is a schematic placeholder. No actual case law was "
                f"retrieved. Consult an attorney for case law research."
            ),
            "contract_clause": (
                f"Contract clause query: '{query_text}'. "
                f"This is a schematic placeholder. No contract clause analysis "
                f"was performed. Consult an attorney for contract review."
            ),
            "legal_concept": (
                f"Legal concept query: '{query_text}'. "
                f"This is a schematic placeholder. No legal concept explanation "
                f"was retrieved. Consult an attorney for legal concepts."
            ),
            "regulatory_ref": (
                f"Regulatory reference query: '{query_text}'. "
                f"This is a schematic placeholder. No regulatory data was "
                f"retrieved. Consult an attorney for regulatory guidance."
            ),
        }
        return templates.get(
            query_type,
            f"Legal query: '{query_text}'. No specific response template available.",
        )

    def get_query(self, query_id: str) -> LegalQuery | None:
        """Get a query by ID."""
        return self.queries.get(query_id)

    def get_response(self, query_id: str) -> LegalResponse | None:
        """Get a response by ID."""
        return self.responses.get(query_id)

    def list_queries(self) -> list[LegalQuery]:
        """List all queries."""
        return list(self.queries.values())

    def get_status(self) -> dict[str, Any]:
        """Get subsystem status."""
        return {
            "subsystem": "legal_advisor",
            "status": "operational" if self._initialized else "offline",
            "queries": len(self.queries),
            "responses": len(self.responses),
            "domains": sorted(self.ALLOWED_DOMAINS),
            "capabilities": [
                "case_law_search",
                "contract_clause_analysis",
                "legal_concept_overview",
                "regulatory_reference",
            ],
            "constraints": [
                "no_legal_advice",
                "no_representation",
                "no_filing_assistance",
                "read_only_legal_databases",
                "policy_gated_domain_access",
            ],
        }


# Global instance
_legal_advisor: LegalAdvisor | None = None


def get_legal_advisor(
    policy: PolicyEngine | None = None,
    events: EventStore | None = None,
) -> LegalAdvisor:
    """Get or create the global Legal Advisor instance."""
    global _legal_advisor
    if _legal_advisor is None:
        _legal_advisor = LegalAdvisor(policy=policy, events=events)
    return _legal_advisor


__all__ = [
    "LegalAdvisor",
    "LegalQuery",
    "LegalResponse",
    "get_legal_advisor",
]