"""
Scientific Advisory Agent — JARVIS-OS Stark AI Extension.

Provides read-only scientific reference information: literature search,
citation analysis, research methodology overviews, and experiment design
frameworks.

SECURITY CONSTRAINTS (hard_coded):
- NO laboratory control — no equipment access
- NO experiment execution — no lab automation
- NO clinical data — no patient data handling
- Read-only scientific literature via PolicyEngine-gated internet access
- All outputs carry disclaimer: not a substitute for peer-reviewed research
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
class ScientificQuery:
    """A scientific advisory query."""
    query_id: str
    query_type: str  # literature_search, citation_analysis, research_methodology, experiment_design
    query_text: str
    field_of_study: str = "general"
    timestamp: float = field(default_factory=time.time)


@dataclass
class ScientificResponse:
    """A scientific advisory response."""
    query_id: str
    response_type: str
    content: str
    disclaimer: str
    sources: list[str] = field(default_factory=list)
    confidence: float = 0.0
    timestamp: float = field(default_factory=time.time)


class ScientificAdvisor:
    """
    Scientific Advisory Agent — read-only scientific reference.

    Provides general scientific information for educational purposes only.
    Cannot control laboratory equipment, execute experiments, or handle
    clinical data. All queries pass through PolicyEngine with allowlisted
    scientific domains only.
    """

    ALLOWED_DOMAINS: frozenset[str] = frozenset({
        "pubmed.ncbi.nlm.nih.gov",
        "arxiv.org",
        "scholar.google.com",
        "science.org",
        "nature.com",
        "cell.com",
        "plos.org",
    })

    DISCLAIMER: str = (
        "IMPORTANT: This information is for educational purposes only and "
        "is not a substitute for peer-reviewed scientific research, "
        "laboratory validation, or professional scientific consultation."
    )

    def __init__(
        self,
        policy: PolicyEngine | None = None,
        events: EventStore | None = None,
    ) -> None:
        self.policy = policy
        self.events = events
        self.queries: dict[str, ScientificQuery] = {}
        self.responses: dict[str, ScientificResponse] = {}
        self._initialized = False

    def initialize(self) -> dict[str, Any]:
        """Initialize the scientific advisor."""
        self._initialized = True
        return {
            "status": "operational",
            "subsystem": "scientific_advisor",
            "domains": len(self.ALLOWED_DOMAINS),
            "policy_gated": True,
            "read_only": True,
            "disclaimer": self.DISCLAIMER,
        }

    def query(
        self,
        query_type: str,
        query_text: str,
        field_of_study: str = "general",
    ) -> ScientificResponse:
        """Process a scientific advisory query."""
        query_id = f"sci-{int(time.time() * 1000)}"

        query = ScientificQuery(
            query_id=query_id,
            query_type=query_type,
            query_text=query_text,
            field_of_study=field_of_study,
        )
        self.queries[query_id] = query

        grant_result = {"approved": False, "reason": "no policy engine"}
        if self.policy:
            grant_result = self.policy.evaluate(
                "scientific_advisor.query",
                {
                    "query_type": query_type,
                    "field_of_study": field_of_study,
                    "domains": list(self.ALLOWED_DOMAINS),
                },
            )

        content = self._generate_schematic_response(query_type, query_text)

        response = ScientificResponse(
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
                "event": "scientific_advisor.query",
                "query_id": query_id,
                "query_type": query_type,
                "field_of_study": field_of_study,
                "approved": grant_result.get("approved", False),
                "at": query.timestamp,
            })

        return response

    def _generate_schematic_response(
        self,
        query_type: str,
        query_text: str,
    ) -> str:
        """Generate a schematic response (placeholder, not real scientific data)."""
        templates = {
            "literature_search": (
                f"Literature search query: '{query_text}'. "
                f"This is a schematic placeholder. No actual literature was "
                f"retrieved. Consult a research librarian for literature search."
            ),
            "citation_analysis": (
                f"Citation analysis query: '{query_text}'. "
                f"This is a schematic placeholder. No citation analysis was "
                f"performed. Consult a research advisor for citation metrics."
            ),
            "research_methodology": (
                f"Research methodology query: '{query_text}'. "
                f"This is a schematic placeholder. No methodology guidance was "
                f"retrieved. Consult a principal investigator for methodology."
            ),
            "experiment_design": (
                f"Experiment design query: '{query_text}'. "
                f"This is a schematic placeholder. No experiment design was "
                f"created. Consult a research advisor for experimental design."
            ),
        }
        return templates.get(
            query_type,
            f"Scientific query: '{query_text}'. No specific response template available.",
        )

    def get_query(self, query_id: str) -> ScientificQuery | None:
        """Get a query by ID."""
        return self.queries.get(query_id)

    def get_response(self, query_id: str) -> ScientificResponse | None:
        """Get a response by ID."""
        return self.responses.get(query_id)

    def list_queries(self) -> list[ScientificQuery]:
        """List all queries."""
        return list(self.queries.values())

    def get_status(self) -> dict[str, Any]:
        """Get subsystem status."""
        return {
            "subsystem": "scientific_advisor",
            "status": "operational" if self._initialized else "offline",
            "queries": len(self.queries),
            "responses": len(self.responses),
            "domains": sorted(self.ALLOWED_DOMAINS),
            "capabilities": [
                "literature_search",
                "citation_analysis",
                "research_methodology_overview",
                "experiment_design_framework",
            ],
            "constraints": [
                "no_laboratory_control",
                "no_experiment_execution",
                "no_clinical_data",
                "read_only_scientific_literature",
                "policy_gated_domain_access",
            ],
        }


# Global instance
_scientific_advisor: ScientificAdvisor | None = None


def get_scientific_advisor(
    policy: PolicyEngine | None = None,
    events: EventStore | None = None,
) -> ScientificAdvisor:
    """Get or create the global Scientific Advisor instance."""
    global _scientific_advisor
    if _scientific_advisor is None:
        _scientific_advisor = ScientificAdvisor(policy=policy, events=events)
    return _scientific_advisor


__all__ = [
    "ScientificAdvisor",
    "ScientificQuery",
    "ScientificResponse",
    "get_scientific_advisor",
]