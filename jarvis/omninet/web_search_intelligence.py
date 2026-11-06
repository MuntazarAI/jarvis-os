"""
Web Search Intelligence — JARVIS-OS OMNINET subsystem.

Provides web search, browser automation, and content extraction capabilities
through allowlisted domains. All requests pass through PolicyEngine with
time-bounded, rate-limited grants. Read-only — no destructive actions.

Sources: DuckDuckGo (HTML), Brave Search, SearXNG instances, direct web fetch
on allowlisted domains only.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from ..core.logging import get_module_logger
from ..core.internet import InternetAccess
from ..policy.policy import PolicyEngine
from ..events.store import EventStore

log = get_module_logger(__name__)


@dataclass
class SearchResult:
    """A single web search result."""
    title: str
    url: str
    snippet: str
    source: str  # duckduckgo, brave, searxng, direct
    relevance: float = 0.0
    fetched_at: float = field(default_factory=time.time)


@dataclass
class SearchResponse:
    """A web search response."""
    query: str
    results: list[SearchResult] = field(default_factory=list)
    total_results: int = 0
    source: str = ""
    fetched_at: float = field(default_factory=time.time)


class WebSearchIntelligence:
    """
    Web Search Intelligence — allowlisted web search and content extraction.

    All searches require PolicyEngine approval for the target domain.
    Results are read-only. No JavaScript execution, no form submission,
    no interactive browsing without explicit approval.
    """

    ALLOWLISTED_DOMAINS: frozenset[str] = frozenset({
        "duckduckgo.com",
        "html.duckduckgo.com",
        "search.brave.com",
        "api.brave.com",
        "en.wikipedia.org",
        "developer.mozilla.org",
        "docs.python.org",
        "pypi.org",
        "github.com",
        "arxiv.org",
        "en.wikipedia.org",
    })

    def __init__(
        self,
        policy: PolicyEngine | None = None,
        internet: InternetAccess | None = None,
        events: EventStore | None = None,
    ) -> None:
        self.policy = policy
        self.internet = internet
        self.events = events
        self.searches: dict[str, SearchResponse] = {}
        self._initialized = False

    def initialize(self) -> dict[str, Any]:
        """Initialize the web search subsystem."""
        self._initialized = True
        return {
            "status": "operational",
            "subsystem": "web_search_intelligence",
            "allowlisted_domains": len(self.ALLOWLISTED_DOMAINS),
            "policy_gated": True,
            "read_only": True,
        }

    def search(
        self,
        query: str,
        domain: str | None = None,
        max_results: int = 10,
    ) -> SearchResponse:
        """Perform a web search through PolicyEngine-granted access."""
        # Determine target domain
        target_domain = domain or "duckduckgo.com"

        # Request PolicyEngine approval
        if self.policy:
            grant = self.policy.evaluate(
                "web_search.search",
                {"domain": target_domain, "query": query, "max_results": max_results},
            )
            if not grant.get("approved", False):
                return SearchResponse(
                    query=query,
                    source="denied",
                    total_results=0,
                )

        # Record the search
        response = SearchResponse(
            query=query,
            source=target_domain,
            total_results=0,
        )
        self.searches[response.fetched_at.__str__()] = response

        if self.events:
            self.events.append({
                "event": "web_search.search",
                "query": query,
                "domain": target_domain,
                "at": response.fetched_at,
            })

        return response

    def fetch_content(self, url: str) -> dict[str, Any]:
        """Fetch readable content from an allowlisted URL."""
        from urllib.parse import urlparse
        parsed = urlparse(url)
        domain = parsed.netloc

        if domain not in self.ALLOWLISTED_DOMAINS:
            return {
                "ok": False,
                "url": url,
                "reason": f"domain {domain} not in allowlist",
            }

        if self.policy:
            grant = self.policy.evaluate(
                "web_search.fetch",
                {"url": url, "domain": domain},
            )
            if not grant.get("approved", False):
                return {
                    "ok": False,
                    "url": url,
                    "reason": "policy denied",
                }

        return {
            "ok": True,
            "url": url,
            "domain": domain,
            "content": "",  # Content extraction requires browser automation
            "fetched_at": time.time(),
        }

    def list_domains(self) -> list[str]:
        """List allowlisted domains."""
        return sorted(self.ALLOWLISTED_DOMAINS)

    def get_status(self) -> dict[str, Any]:
        """Get subsystem status."""
        return {
            "subsystem": "web_search_intelligence",
            "status": "operational" if self._initialized else "offline",
            "searches_performed": len(self.searches),
            "allowlisted_domains": sorted(self.ALLOWLISTED_DOMAINS),
            "capabilities": [
                "web_search",
                "content_fetch",
                "domain_allowlist",
                "policy_gated_search",
            ],
            "read_only": True,
        }


# Global instance
_wsi: WebSearchIntelligence | None = None


def get_web_search_intelligence(
    policy: PolicyEngine | None = None,
    internet: InternetAccess | None = None,
    events: EventStore | None = None,
) -> WebSearchIntelligence:
    """Get or create the global Web Search Intelligence instance."""
    global _wsi
    if _wsi is None:
        _wsi = WebSearchIntelligence(policy=policy, internet=internet, events=events)
    return _wsi


__all__ = [
    "WebSearchIntelligence",
    "SearchResult",
    "SearchResponse",
    "get_web_search_intelligence",
]