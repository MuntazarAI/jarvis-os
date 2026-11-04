"""Global Web Discovery (M2).

Multi-provider search engine with fallback chain:
- DuckDuckGo (existing via jarvis/browser/agent.py) — keyless, always available
- SearXNG — self-hosted instance (when configured)
- Brave Search — requires API key (optional)
- Tavily — requires API key (optional)
- Exa — requires API key (optional)

Providers are tried in order; the first one returning results wins.
Fails honestly when offline or no provider is configured.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from ..browser.agent import BrowserAgent
from ..core.internet import InternetAccess
from ..core.logging import get_module_logger
from ..core.types import ActionPlan, RiskLevel
from ..policy.policy import PolicyEngine
from ..security.guards import is_safe_url

log = get_module_logger(__name__)


@dataclass
class SearchResult:
    """Normalized search result from any provider."""
    title: str
    url: str
    snippet: str = ""
    provider: str = ""
    rank: int = 0
    fetched_at: float = field(default_factory=time.monotonic)


@dataclass
class SearchProviderSpec:
    """Specification for a search provider."""
    name: str
    kind: str  # duckduckgo | searxng | brave | tavily | exa
    enabled: bool = True
    requires_key: bool = False
    api_key: str | None = None
    base_url: str = ""
    timeout_s: float = 15.0
    max_results: int = 10
    trust_note: str = "unknown"
    trust_basis: str = "unknown"


class SearchProvider:
    """Base class for search providers."""

    def __init__(
        self,
        spec: SearchProviderSpec,
        policy: PolicyEngine,
        internet: InternetAccess,
        actor: str = "jarvis",
    ) -> None:
        self.spec = spec
        self.policy = policy
        self.internet = internet
        self.actor = actor
        self._requests_total: int = 0
        self._failures_total: int = 0

    def is_available(self) -> bool:
        """Return True if this provider can be used (enabled + configured)."""
        if not self.spec.enabled:
            return False
        if self.spec.requires_key and not self.spec.api_key:
            return False
        return True

    def search(self, query: str, count: int = 5) -> list[SearchResult]:
        """Search and return normalized results. Must be implemented by subclasses."""
        raise NotImplementedError

    def _evaluate(self, action: str, args: dict[str, Any]) -> Any:
        plan = ActionPlan(
            action=action,
            args=args,
            required_permissions=["net.fetch"],
            risk=RiskLevel.LOW,
        )
        return self.policy.evaluate(self.actor, plan)


class DuckDuckGoProvider(SearchProvider):
    """DuckDuckGo keyless search via the existing BrowserAgent."""

    def __init__(
        self,
        policy: PolicyEngine,
        internet: InternetAccess,
        actor: str = "jarvis",
    ) -> None:
        spec = SearchProviderSpec(
            name="duckduckgo",
            kind="duckduckgo",
            enabled=True,
            requires_key=False,
            base_url="https://duckduckgo.com",
            trust_note="keyless HTML search via existing BrowserAgent",
            trust_basis="configured",
        )
        super().__init__(spec, policy, internet, actor=actor)
        self._browser = BrowserAgent()

    def search(self, query: str, count: int = 5) -> list[SearchResult]:
        started = time.monotonic()
        decision = self._evaluate(
            action=f"search.duckduckgo.{query[:80]}",
            args={"query": query, "count": count},
        )
        if not decision.allow:
            log.warning("DuckDuckGo search denied by policy",
                        reasons=decision.reasons)
            return []

        # Domain grant check
        if not self.internet.can_access(self.actor, "duckduckgo.com"):
            log.warning("No internet grant for duckduckgo.com")
            return []

        safe, reason = is_safe_url("https://duckduckgo.com")
        if not safe:
            log.warning("DuckDuckGo SSRF guard failed", reason=reason)
            return []

        try:
            result = self._browser.search(query, count=count)
            self._requests_total += 1
            if not result.get("ok"):
                self._failures_total += 1
                return []
            raw_results = result.get("results", [])
            results = []
            for i, hit in enumerate(raw_results[:count]):
                results.append(SearchResult(
                    title=hit.get("title", ""),
                    url=hit.get("url", ""),
                    snippet=hit.get("snippet", "")[:300],
                    provider="duckduckgo",
                    rank=i + 1,
                ))
            log.info("DuckDuckGo search completed",
                     query=query[:60], results=len(results),
                     provider=result.get("provider", "unknown"),
                     latency_ms=round((time.monotonic() - started) * 1000, 2))
            return results
        except Exception as exc:
            self._failures_total += 1
            log.warning("DuckDuckGo search failed", error=str(exc)[:120])
            return []


class SearXNGProvider(SearchProvider):
    """SearXNG metasearch provider (self-hosted instance, optional)."""

    def __init__(
        self,
        policy: PolicyEngine,
        internet: InternetAccess,
        instance_url: str,
        actor: str = "jarvis",
    ) -> None:
        spec = SearchProviderSpec(
            name="searxng",
            kind="searxng",
            enabled=True,
            requires_key=False,
            base_url=instance_url,
            trust_note="self-hosted SearXNG metasearch instance",
            trust_basis="configured",
        )
        super().__init__(spec, policy, internet, actor=actor)
        self.instance_url = instance_url.rstrip("/")

    def is_available(self) -> bool:
        # SearXNG needs a valid instance URL + internet grant for that domain
        if not super().is_available():
            return False
        from urllib.parse import urlparse
        domain = urlparse(self.instance_url).netloc.lower()
        return self.internet.can_access(self.actor, domain)

    def search(self, query: str, count: int = 5) -> list[SearchResult]:
        started = time.monotonic()
        decision = self._evaluate(
            action=f"search.searxng.{query[:80]}",
            args={"query": query, "count": count, "instance": self.instance_url},
        )
        if not decision.allow:
            log.warning("SearXNG search denied by policy", reasons=decision.reasons)
            return []

        safe, reason = is_safe_url(self.instance_url)
        if not safe:
            log.warning("SearXNG SSRF guard failed", reason=reason)
            return []

        try:
            import urllib.parse
            import urllib.request
            params = urllib.parse.urlencode({"q": query, "format": "json"})
            url = f"{self.instance_url}/search?{params}"
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "jarvis-os/0.1 OMNINET research agent"},
            )
            with urllib.request.urlopen(req, timeout=self.spec.timeout_s) as resp:  # noqa: S310
                import json
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
            self._requests_total += 1
            results = []
            for i, item in enumerate(data.get("results", [])[:count]):
                results.append(SearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    snippet=item.get("content", "")[:300],
                    provider="searxng",
                    rank=i + 1,
                ))
            log.info("SearXNG search completed",
                     query=query[:60], results=len(results),
                     latency_ms=round((time.monotonic() - started) * 1000, 2))
            return results
        except Exception as exc:
            self._failures_total += 1
            log.warning("SearXNG search failed", error=str(exc)[:120])
            return []


class BraveSearchProvider(SearchProvider):
    """Brave Search provider — requires API key."""

    def __init__(
        self,
        policy: PolicyEngine,
        internet: InternetAccess,
        api_key: str,
        actor: str = "jarvis",
    ) -> None:
        spec = SearchProviderSpec(
            name="brave",
            kind="brave",
            enabled=True,
            requires_key=True,
            api_key=api_key,
            base_url="https://api.search.brave.com/res/v1/web/search",
            trust_note="Brave Search API (key-configured)",
            trust_basis="configured",
        )
        super().__init__(spec, policy, internet, actor=actor)

    def search(self, query: str, count: int = 5) -> list[SearchResult]:
        started = time.monotonic()
        decision = self._evaluate(
            action=f"search.brave.{query[:80]}",
            args={"query": query, "count": count},
        )
        if not decision.allow:
            log.warning("Brave search denied by policy", reasons=decision.reasons)
            return []

        safe, reason = is_safe_url(self.spec.base_url)
        if not safe:
            log.warning("Brave SSRF guard failed", reason=reason)
            return []

        try:
            import urllib.parse
            import urllib.request
            import json
            params = urllib.parse.urlencode({"q": query, "count": count})
            url = f"{self.spec.base_url}?{params}"
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "jarvis-os/0.1 OMNINET research agent",
                    "X-Subscription-Token": self.spec.api_key or "",
                    "Accept": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=self.spec.timeout_s) as resp:  # noqa: S310
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
            self._requests_total += 1
            results = []
            for i, item in enumerate(data.get("web", {}).get("results", [])[:count]):
                results.append(SearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    snippet=item.get("description", "")[:300],
                    provider="brave",
                    rank=i + 1,
                ))
            log.info("Brave search completed",
                     query=query[:60], results=len(results),
                     latency_ms=round((time.monotonic() - started) * 1000, 2))
            return results
        except Exception as exc:
            self._failures_total += 1
            log.warning("Brave search failed", error=str(exc)[:120])
            return []


class SearchEngine:
    """Multi-provider discovery engine with fallback chain.

    Providers are tried in priority order. The first provider returning
    results wins. Falls back gracefully when providers are offline or
    not configured.
    """

    def __init__(
        self,
        policy: PolicyEngine,
        internet: InternetAccess,
        actor: str = "jarvis",
    ) -> None:
        self.policy = policy
        self.internet = internet
        self.actor = actor
        self._providers: list[SearchProvider] = []

        # Always register DuckDuckGo (keyless, fallback)
        self._providers.append(DuckDuckGoProvider(policy, internet, actor))

    def register(self, provider: SearchProvider) -> None:
        """Register a search provider. Order matters — earlier = higher priority."""
        self._providers.append(provider)
        log.info("Search provider registered",
                 name=provider.spec.name, kind=provider.spec.kind)

    def add_searxng(self, instance_url: str) -> None:
        """Add a SearXNG instance provider."""
        self.register(SearXNGProvider(self.policy, self.internet, instance_url, self.actor))

    def add_brave(self, api_key: str) -> None:
        """Add Brave Search provider (requires API key)."""
        self.register(BraveSearchProvider(self.policy, self.internet, api_key, self.actor))

    def available_providers(self) -> list[str]:
        """Return names of providers that are currently available."""
        return [p.spec.name for p in self._providers if p.is_available()]

    def search(self, query: str, count: int = 5) -> dict[str, Any]:
        """Search across providers with fallback.

        Returns the first provider's results that succeed.
        Falls through all providers if none return results.
        """
        started = time.monotonic()
        available = [p for p in self._providers if p.is_available()]

        if not available:
            return {
                "ok": False,
                "query": query,
                "results": [],
                "provider": None,
                "error": "no search providers available",
                "providers_checked": [],
                "latency_ms": round((time.monotonic() - started) * 1000, 2),
            }

        providers_checked = []
        last_error = ""

        for provider in available:
            providers_checked.append(provider.spec.name)
            try:
                results = provider.search(query, count=count)
                if results:
                    return {
                        "ok": True,
                        "query": query,
                        "results": [r.__dict__ for r in results],
                        "provider": provider.spec.name,
                        "error": "",
                        "providers_checked": providers_checked,
                        "latency_ms": round((time.monotonic() - started) * 1000, 2),
                    }
            except Exception as exc:
                last_error = str(exc)[:120]
                log.warning("Search provider failed",
                            provider=provider.spec.name, error=last_error)

        # All providers tried, none returned results
        return {
            "ok": False,
            "query": query,
            "results": [],
            "provider": None,
            "error": last_error or "no results from any provider",
            "providers_checked": providers_checked,
            "latency_ms": round((time.monotonic() - started) * 1000, 2),
        }

    def health(self) -> dict[str, Any]:
        """Return health status of all search providers."""
        return {
            "providers": [
                {
                    "name": p.spec.name,
                    "kind": p.spec.kind,
                    "available": p.is_available(),
                    "requests_total": p._requests_total,
                    "failures_total": p._failures_total,
                }
                for p in self._providers
            ],
            "available_count": sum(1 for p in self._providers if p.is_available()),
        }


__all__ = [
    "SearchResult",
    "SearchProviderSpec",
    "SearchProvider",
    "DuckDuckGoProvider",
    "SearXNGProvider",
    "BraveSearchProvider",
    "SearchEngine",
]
