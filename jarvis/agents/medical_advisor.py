"""
Medical Advisory Agent — JARVIS-OS Stark AI Extension.

Provides read-only medical reference information: drug interaction lookup,
symptom triage guidance, condition overviews, and medication information.

SECURITY CONSTRAINTS (hard-coded):
- NO diagnosis capability — only general information
- NO prescription capability — no medication recommendations
- NO treatment advice — only educational content
- Read-only medical databases via PolicyEngine-gated internet access
- All outputs carry disclaimer: not a substitute for professional care
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
class MedicalQuery:
    """A medical advisory query."""
    query_id: str
    query_type: str  # drug_interaction, symptom_info, condition_overview, medication_info
    query_text: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class MedicalResponse:
    """A medical advisory response."""
    query_id: str
    response_type: str
    content: str
    disclaimer: str
    sources: list[str] = field(default_factory=list)
    confidence: float = 0.0
    timestamp: float = field(default_factory=time.time)


class MedicalAdvisor:
    """
    Medical Advisory Agent — read-only medical reference.

    Provides general medical information for educational purposes only.
    Cannot diagnose, prescribe, or recommend treatment. All queries pass
    through PolicyEngine with allowlisted medical domains only.
    """

    ALLOWED_DOMAINS: frozenset[str] = frozenset({
        "medlineplus.gov",
        "cdc.gov",
        "nih.gov",
        "mayoclinic.org",
        "who.int",
        "drugs.com",
        "rxlist.com",
    })

    DISCLAIMER: str = (
        "IMPORTANT: This information is for educational purposes only and "
        "is not a substitute for professional medical advice, diagnosis, "
        "or treatment. Always consult a qualified healthcare provider for "
        "medical concerns."
    )

    def __init__(
        self,
        policy: PolicyEngine | None = None,
        events: EventStore | None = None,
    ) -> None:
        self.policy = policy
        self.events = events
        self.queries: dict[str, MedicalQuery] = {}
        self.responses: dict[str, MedicalResponse] = {}
        self._initialized = False

    def initialize(self) -> dict[str, Any]:
        """Initialize the medical advisor."""
        self._initialized = True
        return {
            "status": "operational",
            "subsystem": "medical_advisor",
            "domains": len(self.ALLOWED_DOMAINS),
            "policy_gated": True,
            "read_only": True,
            "disclaimer": self.DISCLAIMER,
        }

    def query(
        self,
        query_type: str,
        query_text: str,
    ) -> MedicalResponse:
        """Process a medical advisory query."""
        query_id = f"med-{int(time.time() * 1000)}"

        query = MedicalQuery(
            query_id=query_id,
            query_type=query_type,
            query_text=query_text,
        )
        self.queries[query_id] = query

        # Request PolicyEngine approval for domain access
        grant_result = {"approved": False, "reason": "no policy engine"}
        if self.policy:
            grant_result = self.policy.evaluate(
                "medical_advisor.query",
                {
                    "query_type": query_type,
                    "domains": list(self.ALLOWED_DOMAINS),
                },
            )

        # Generate schematic response (no actual medical data fetched without approval)
        content = self._generate_schematic_response(query_type, query_text)

        response = MedicalResponse(
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
                "event": "medical_advisor.query",
                "query_id": query_id,
                "query_type": query_type,
                "approved": grant_result.get("approved", False),
                "at": query.timestamp,
            })

        return response

    def _generate_schematic_response(
        self,
        query_type: str,
        query_text: str,
    ) -> str:
        """Generate a schematic response (placeholder, not real medical data)."""
        templates = {
            "drug_interaction": (
                f"Drug interaction query: '{query_text}'. "
                f"This is a schematic placeholder. No actual drug interaction "
                f"data was retrieved. Consult a pharmacist or physician for "
                f"drug interaction information."
            ),
            "symptom_info": (
                f"Symptom information query: '{query_text}'. "
                f"This is a schematic placeholder. No medical diagnosis is "
                f"provided. Seek professional medical evaluation for symptoms."
            ),
            "condition_overview": (
                f"Condition overview query: '{query_text}'. "
                f"This is a schematic placeholder. No medical condition data "
                f"was retrieved. Consult a healthcare provider for condition "
                f"information."
            ),
            "medication_info": (
                f"Medication information query: '{query_text}'. "
                f"This is a schematic placeholder. No medication data was "
                f"retrieved. Consult a pharmacist for medication information."
            ),
        }
        return templates.get(
            query_type,
            f"Medical query: '{query_text}'. No specific response template available.",
        )

    def get_query(self, query_id: str) -> MedicalQuery | None:
        """Get a query by ID."""
        return self.queries.get(query_id)

    def get_response(self, query_id: str) -> MedicalResponse | None:
        """Get a response by ID."""
        return self.responses.get(query_id)

    def list_queries(self) -> list[MedicalQuery]:
        """List all queries."""
        return list(self.queries.values())

    def get_status(self) -> dict[str, Any]:
        """Get subsystem status."""
        return {
            "subsystem": "medical_advisor",
            "status": "operational" if self._initialized else "offline",
            "queries": len(self.queries),
            "responses": len(self.responses),
            "domains": sorted(self.ALLOWED_DOMAINS),
            "capabilities": [
                "drug_interaction_lookup",
                "symptom_information",
                "condition_overview",
                "medication_information",
            ],
            "constraints": [
                "no_diagnosis",
                "no_prescription",
                "no_treatment_advice",
                "read_only_medical_databases",
                "policy_gated_domain_access",
            ],
        }


# Global instance
_medical_advisor: MedicalAdvisor | None = None


def get_medical_advisor(
    policy: PolicyEngine | None = None,
    events: EventStore | None = None,
) -> MedicalAdvisor:
    """Get or create the global Medical Advisor instance."""
    global _medical_advisor
    if _medical_advisor is None:
        _medical_advisor = MedicalAdvisor(policy=policy, events=events)
    return _medical_advisor


__all__ = [
    "MedicalAdvisor",
    "MedicalQuery",
    "MedicalResponse",
    "get_medical_advisor",
]