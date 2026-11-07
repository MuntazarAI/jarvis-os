"""
Financial Advisory Agent — JARVIS-OS Stark AI Extension.

Provides read-only financial reference information: market data lookup,
portfolio analysis concepts, investment terminology, and economic indicators.

SECURITY CONSTRAINTS (hard-coded):
- NO trading capability — no buy/sell orders
- NO fund transfer capability — no money movement
- NO investment advice — no personalized recommendations
- Read-only financial data via PolicyEngine-gated internet access
- All outputs carry disclaimer: not a substitute for financial advice
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
class FinancialQuery:
    """A financial advisory query."""
    query_id: str
    query_type: str  # market_data, portfolio_concept, investment_terminology, economic_indicator
    query_text: str
    asset_class: str = "general"
    timestamp: float = field(default_factory=time.time)


@dataclass
class FinancialResponse:
    """A financial advisory response."""
    query_id: str
    response_type: str
    content: str
    disclaimer: str
    sources: list[str] = field(default_factory=list)
    confidence: float = 0.0
    timestamp: float = field(default_factory=time.time)


class FinancialAdvisor:
    """
    Financial Advisory Agent — read-only financial reference.

    Provides general financial information for educational purposes only.
    Cannot execute trades, transfer funds, or provide investment advice.
    All queries pass through PolicyEngine with allowlisted financial domains only.
    """

    ALLOWED_DOMAINS: frozenset[str] = frozenset({
        "sec.gov",
        "investor.gov",
        "federalreserve.gov",
        "treasury.gov",
        "yahoo.com",
        "bloomberg.com",
        "reuters.com",
    })

    DISCLAIMER: str = (
        "IMPORTANT: This information is for educational purposes only and "
        "is not a substitute for professional financial advice, investment "
        "recommendations, or financial planning. Always consult a qualified "
        "financial advisor for investment decisions."
    )

    def __init__(
        self,
        policy: PolicyEngine | None = None,
        events: EventStore | None = None,
    ) -> None:
        self.policy = policy
        self.events = events
        self.queries: dict[str, FinancialQuery] = {}
        self.responses: dict[str, FinancialResponse] = {}
        self._initialized = False

    def initialize(self) -> dict[str, Any]:
        """Initialize the financial advisor."""
        self._initialized = True
        return {
            "status": "operational",
            "subsystem": "financial_advisor",
            "domains": len(self.ALLOWED_DOMAINS),
            "policy_gated": True,
            "read_only": True,
            "disclaimer": self.DISCLAIMER,
        }

    def query(
        self,
        query_type: str,
        query_text: str,
        asset_class: str = "general",
    ) -> FinancialResponse:
        """Process a financial advisory query."""
        query_id = f"fin-{int(time.time() * 1000)}"

        query = FinancialQuery(
            query_id=query_id,
            query_type=query_type,
            query_text=query_text,
            asset_class=asset_class,
        )
        self.queries[query_id] = query

        grant_result = {"approved": False, "reason": "no policy engine"}
        if self.policy:
            grant_result = self.policy.evaluate(
                "financial_advisor.query",
                {
                    "query_type": query_type,
                    "asset_class": asset_class,
                    "domains": list(self.ALLOWED_DOMAINS),
                },
            )

        content = self._generate_schematic_response(query_type, query_text)

        response = FinancialResponse(
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
                "event": "financial_advisor.query",
                "query_id": query_id,
                "query_type": query_type,
                "asset_class": asset_class,
                "approved": grant_result.get("approved", False),
                "at": query.timestamp,
            })

        return response

    def _generate_schematic_response(
        self,
        query_type: str,
        query_text: str,
    ) -> str:
        """Generate a schematic response (placeholder, not real financial data)."""
        templates = {
            "market_data": (
                f"Market data query: '{query_text}'. "
                f"This is a schematic placeholder. No actual market data was "
                f"retrieved. Consult a financial advisor for market information."
            ),
            "portfolio_concept": (
                f"Portfolio concept query: '{query_text}'. "
                f"This is a schematic placeholder. No portfolio analysis was "
                f"performed. Consult a financial advisor for portfolio guidance."
            ),
            "investment_terminology": (
                f"Investment terminology query: '{query_text}'. "
                f"This is a schematic placeholder. No investment terminology "
                f"explanation was retrieved. Consult a financial advisor."
            ),
            "economic_indicator": (
                f"Economic indicator query: '{query_text}'. "
                f"This is a schematic placeholder. No economic data was "
                f"retrieved. Consult a financial advisor for economic analysis."
            ),
        }
        return templates.get(
            query_type,
            f"Financial query: '{query_text}'. No specific response template available.",
        )

    def get_query(self, query_id: str) -> FinancialQuery | None:
        """Get a query by ID."""
        return self.queries.get(query_id)

    def get_response(self, query_id: str) -> FinancialResponse | None:
        """Get a response by ID."""
        return self.responses.get(query_id)

    def list_queries(self) -> list[FinancialQuery]:
        """List all queries."""
        return list(self.queries.values())

    def get_status(self) -> dict[str, Any]:
        """Get subsystem status."""
        return {
            "subsystem": "financial_advisor",
            "status": "operational" if self._initialized else "offline",
            "queries": len(self.queries),
            "responses": len(self.responses),
            "domains": sorted(self.ALLOWED_DOMAINS),
            "capabilities": [
                "market_data_lookup",
                "portfolio_concept_overview",
                "investment_terminology",
                "economic_indicator_reference",
            ],
            "constraints": [
                "no_trading",
                "no_fund_transfer",
                "no_investment_advice",
                "read_only_financial_data",
                "policy_gated_domain_access",
            ],
        }


# Global instance
_financial_advisor: FinancialAdvisor | None = None


def get_financial_advisor(
    policy: PolicyEngine | None = None,
    events: EventStore | None = None,
) -> FinancialAdvisor:
    """Get or create the global Financial Advisor instance."""
    global _financial_advisor
    if _financial_advisor is None:
        _financial_advisor = FinancialAdvisor(policy=policy, events=events)
    return _financial_advisor


__all__ = [
    "FinancialAdvisor",
    "FinancialQuery",
    "FinancialResponse",
    "get_financial_advisor",
]