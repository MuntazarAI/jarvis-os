"""Bounded Web Crawler (M5).

Large-scale public web discovery with:
- Sitemap discovery
- Public link discovery
- Domain categorization
- Incremental crawling
- Content hashing
- Duplicate detection
- Change detection
- Content indexing
- Search indexing
- Historical records

Respects:
- Robots directives
- Source policies
- Rate limits
- Copyright restrictions
- Network restrictions

Implements crawl budgets and storage quotas.
Does NOT attempt unrestricted internet-wide crawling.
"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin, urlparse, urldefrag

from ..core.internet import InternetAccess
from ..core.logging import get_module_logger
from ..omninet.connectors import ConnectorResult
from ..omninet.exploration import EnhancedBrowserAgent
from ..omninet.http_connector import HttpConnector
from ..policy.policy import PolicyEngine
from ..security.guards import is_safe_url

log = get_module_logger(__name__)


# ============================================================================
# Robots.txt parser
# ============================================================================


@dataclass
class RobotsPolicy:
    """Parsed robots.txt policy for a domain."""
    domain: str
    crawl_delay: float = 0.0
    disallowed: list[str] = field(default_factory=list)
    allowed: list[str] = field(default_factory=list)
    sitemaps: list[str] = field(default_factory=list)
    fetched_at: float = 0.0
    ttl_seconds: float = 3600.0

    def is_allowed(self, url: str) -> bool:
        """Check if a URL path is allowed by robots.txt."""
        path = urlparse(url).path
        # Check allowed first (more specific wins)
        for pattern in self.allowed:
            if path.startswith(pattern):
                return True
        # Check disallowed
        for pattern in self.disallowed:
            if path.startswith(pattern):
                return False
        return True  # default allow

    def is_expired(self) -> bool:
        return time.monotonic() - self.fetched_at > self.ttl_seconds


class RobotsCache:
    """Cache of robots.txt policies by domain."""

    def __init__(self) -> None:
        self._policies: dict[str, RobotsPolicy] = {}

    def get(self, domain: str) -> RobotsPolicy | None:
        policy = self._policies.get(domain)
        if policy is None or policy.is_expired():
            return None
        return policy

    def set(self, domain: str, policy: RobotsPolicy) -> None:
        self._policies[domain] = policy

    def clear_expired(self) -> None:
        expired = [d for d, p in self._policies.items() if p.is_expired()]
        for d in expired:
            del self._policies[d]


def _parse_robots_txt(text: str, domain: str) -> RobotsPolicy:
    """Parse robots.txt content into a RobotsPolicy."""
    policy = RobotsPolicy(domain=domain, fetched_at=time.monotonic())
    current_user_agent_all = False

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()

        if key == "user-agent":
            current_user_agent_all = value == "*"
        elif key == "disallow" and current_user_agent_all:
            if value:
                policy.disallowed.append(value)
        elif key == "allow" and current_user_agent_all:
            if value:
                policy.allowed.append(value)
        elif key == "crawl-delay" and current_user_agent_all:
            try:
                policy.crawl_delay = float(value)
            except ValueError:
                pass
        elif key == "sitemap":
            if value:
                policy.sitemaps.append(value)

    return policy


# ============================================================================
# Crawl budget
# ============================================================================


@dataclass
class CrawlBudget:
    """Crawl budget limits."""
    max_pages: int = 100
    max_bytes: int = 50 * 1024 * 1024  # 50 MB
    max_domains: int = 10
    max_depth: int = 2
    max_concurrent: int = 4
    delay_between_requests: float = 1.0
    per_domain_delay: float = 1.0
    per_domain_max_pages: int = 20

    def within_budget(self, pages_crawled: int, bytes_crawled: int,
                      domains_crawled: int) -> bool:
        return (
            pages_crawled < self.max_pages
            and bytes_crawled < self.max_bytes
            and domains_crawled < self.max_domains
        )


# ============================================================================
# Crawl result
# ============================================================================


@dataclass
class CrawlResult:
    """Result of crawling a single page."""
    url: str
    domain: str
    ok: bool
    status: int = 0
    title: str = ""
    word_count: int = 0
    content_hash: str = ""
    links_found: int = 0
    links: list[str] = field(default_factory=list)
    error: str = ""
    fetched_at: float = field(default_factory=time.monotonic)
    latency_ms: float = 0.0
    depth: int = 0
    robots_blocked: bool = False
    duplicate: bool = False


# ============================================================================
# Bounded crawler
# ============================================================================


class BoundedCrawler:
    """Bounded web crawler with robots.txt respect, budgets, and dedup.

    Features:
    - Seed URL-based crawling
    - Sitemap discovery
    - Link extraction and following (bounded depth)
    - Robots.txt compliance
    - Crawl budgets (pages, bytes, domains, depth, concurrency)
    - Content deduplication (hash-based)
    - Incremental crawling (change detection)
    - Historical records
    """

    def __init__(
        self,
        policy: PolicyEngine,
        internet: InternetAccess,
        actor: str = "jarvis",
        budget: CrawlBudget | None = None,
    ) -> None:
        self.policy = policy
        self.internet = internet
        self.actor = actor
        self.budget = budget or CrawlBudget()
        self._http = HttpConnector(policy, internet, actor=actor,
                                   timeout=15.0, max_bytes=1_000_000)
        self._browser = EnhancedBrowserAgent(policy, internet, actor=actor)
        self._robots = RobotsCache()
        self._seen_hashes: set[str] = set()
        self._seen_urls: set[str] = set()
        self._results: list[CrawlResult] = []
        self._pages_crawled: int = 0
        self._bytes_crawled: int = 0
        self._domains_crawled: set[str] = set()
        self._domain_page_counts: dict[str, int] = {}
        self._last_request_by_domain: dict[str, float] = {}
        self._failures_total: int = 0

    # -- robots.txt ------------------------------------------------------

    def _fetch_robots(self, domain: str) -> RobotsPolicy:
        """Fetch and parse robots.txt for a domain."""
        cached = self._robots.get(domain)
        if cached is not None:
            return cached

        url = f"https://{domain}/robots.txt"
        result = self._http.fetch(url)
        if result.ok:
            text = result.data.get("text", "")
            policy = _parse_robots_txt(text, domain)
        else:
            # No robots.txt or fetch failed — default allow with delay
            policy = RobotsPolicy(domain=domain, fetched_at=time.monotonic())

        self._robots.set(domain, policy)
        return policy

    def _respect_crawl_delay(self, domain: str) -> None:
        """Enforce per-domain crawl delay."""
        policy = self._robots.get(domain)
        delay = policy.crawl_delay if policy else 0.0
        delay = max(delay, self.budget.per_domain_delay)

        last = self._last_request_by_domain.get(domain, 0.0)
        elapsed = time.monotonic() - last
        if elapsed < delay:
            time.sleep(delay - elapsed)

    # -- link extraction -------------------------------------------------

    @staticmethod
    def _extract_links(html: str, base_url: str) -> list[str]:
        """Extract all links from HTML, resolved to absolute URLs."""
        links: list[str] = []
        # Match href attributes
        for match in re.finditer(
            r'href\s*=\s*["\']([^"\']+)["\']', html, re.I
        ):
            href = match.group(1)
            absolute = urljoin(base_url, href)
            absolute, _ = urldefrag(absolute)
            if absolute.startswith(("http://", "https://")):
                links.append(absolute)
        return links

    # -- crawl control ---------------------------------------------------

    def _should_crawl(self, url: str, depth: int) -> tuple[bool, str]:
        """Decide if a URL should be crawled."""
        if depth > self.budget.max_depth:
            return False, "max depth exceeded"

        if not self.budget.within_budget(
            self._pages_crawled, self._bytes_crawled, len(self._domains_crawled)
        ):
            return False, "crawl budget exceeded"

        domain = urlparse(url).netloc.lower()
        if len(self._domains_crawled) >= self.budget.max_domains and domain not in self._domains_crawled:
            return False, "max domains exceeded"

        domain_count = self._domain_page_counts.get(domain, 0)
        if domain_count >= self.budget.per_domain_max_pages:
            return False, "per-domain page limit exceeded"

        # Robots.txt check
        policy = self._fetch_robots(domain)
        if not policy.is_allowed(url):
            return False, "robots.txt disallowed"

        # SSRF guard
        safe, reason = is_safe_url(url)
        if not safe:
            return False, f"SSRF guard: {reason}"

        # Domain grant check
        if not self.internet.can_access(self.actor, domain):
            return False, "no internet grant for domain"

        # Duplicate URL check
        if url in self._seen_urls:
            return False, "already crawled"

        return True, "ok"

    # -- crawl a single URL ----------------------------------------------

    def _crawl_url(self, url: str, depth: int) -> CrawlResult:
        """Crawl a single URL."""
        domain = urlparse(url).netloc.lower()

        # Enforce per-domain delay
        self._respect_crawl_delay(domain)

        should, reason = self._should_crawl(url, depth)
        if not should:
            return CrawlResult(
                url=url,
                domain=domain,
                ok=False,
                error=reason,
                robots_blocked="robots.txt" in reason,
            )

        started = time.monotonic()
        result = self._browser.fetch_and_extract(
            url,
            extract_tables_flag=False,
            extract_metadata_flag=True,
            detect_change_flag=True,
        )
        latency_ms = round((time.monotonic() - started) * 1000, 2)

        if not result.get("ok"):
            self._failures_total += 1
            return CrawlResult(
                url=url,
                domain=domain,
                ok=False,
                error=result.get("error", "fetch failed"),
                latency_ms=latency_ms,
            )

        # Content hashing for dedup
        text = result.get("text", "")
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

        is_duplicate = content_hash in self._seen_hashes
        if not is_duplicate:
            self._seen_hashes.add(content_hash)
            self._seen_urls.add(url)
            self._pages_crawled += 1
            self._bytes_crawled += result.get("bytes", 0)
            self._domains_crawled.add(domain)
            self._domain_page_counts[domain] = self._domain_page_counts.get(domain, 0) + 1

        # Extract links for next depth
        links = result.get("links", [])
        html = result.get("text", "")
        discovered_links = self._extract_links(html, url)

        crawl_result = CrawlResult(
            url=url,
            domain=domain,
            ok=True,
            status=result.get("metadata", {}).get("status", 200) if isinstance(
                result.get("metadata"), dict) else 200,
            title=result.get("title", ""),
            word_count=len(text.split()),
            content_hash=content_hash,
            links_found=len(discovered_links),
            links=discovered_links[:50],  # bounded
            error="",
            latency_ms=latency_ms,
            depth=depth,
            robots_blocked=False,
            duplicate=is_duplicate,
        )

        self._results.append(crawl_result)
        self._last_request_by_domain[domain] = time.monotonic()
        return crawl_result

    # -- crawl from seeds ------------------------------------------------

    def crawl(self, seed_urls: list[str],
              max_depth: int | None = None) -> dict[str, Any]:
        """Crawl from seed URLs up to max_depth.

        Returns a crawl report with results, statistics, and discovered links.
        """
        max_d = max_depth if max_depth is not None else self.budget.max_depth
        started = time.monotonic()

        # BFS queue: (url, depth)
        queue: list[tuple[str, int]] = [(u, 0) for u in seed_urls]
        crawled_urls: set[str] = set()

        while queue:
            url, depth = queue.pop(0)

            if url in crawled_urls:
                continue
            crawled_urls.add(url)

            result = self._crawl_url(url, depth)

            # Enqueue discovered links for next depth
            if result.ok and depth < max_d:
                for link in result.links:
                    if link not in crawled_urls:
                        queue.append((link, depth + 1))

            # Check budget after each page
            if not self.budget.within_budget(
                self._pages_crawled, self._bytes_crawled,
                len(self._domains_crawled)
            ):
                log.info("Crawl budget reached", pages=self._pages_crawled,
                         bytes=self._bytes_crawled,
                         domains=len(self._domains_crawled))
                break

        elapsed = round((time.monotonic() - started) * 1000, 2)

        return {
            "ok": True,
            "seeds": seed_urls,
            "max_depth": max_d,
            "pages_crawled": self._pages_crawled,
            "bytes_crawled": self._bytes_crawled,
            "domains_crawled": len(self._domains_crawled),
            "domains": sorted(self._domains_crawled),
            "failures": self._failures_total,
            "duplicates_skipped": len(self._seen_urls) - self._pages_crawled,
            "elapsed_ms": elapsed,
            "results": [r.__dict__ for r in self._results],
            "budget_remaining": {
                "pages": max(0, self.budget.max_pages - self._pages_crawled),
                "bytes": max(0, self.budget.max_bytes - self._bytes_crawled),
                "domains": max(0, self.budget.max_domains - len(self._domains_crawled)),
            },
        }

    # -- sitemap discovery -----------------------------------------------

    def discover_sitemaps(self, domain: str) -> list[str]:
        """Discover sitemap URLs from robots.txt."""
        policy = self._fetch_robots(domain)
        return list(policy.sitemaps)

    # -- stats -----------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        return {
            "pages_crawled": self._pages_crawled,
            "bytes_crawled": self._bytes_crawled,
            "domains_crawled": len(self._domains_crawled),
            "unique_urls": len(self._seen_urls),
            "unique_hashes": len(self._seen_hashes),
            "failures": self._failures_total,
            "results_count": len(self._results),
            "budget": {
                "max_pages": self.budget.max_pages,
                "max_bytes": self.budget.max_bytes,
                "max_domains": self.budget.max_domains,
                "max_depth": self.budget.max_depth,
                "per_domain_max_pages": self.budget.per_domain_max_pages,
            },
        }

    def reset(self) -> None:
        """Reset crawler state for a new crawl."""
        self._seen_hashes.clear()
        self._seen_urls.clear()
        self._results.clear()
        self._pages_crawled = 0
        self._bytes_crawled = 0
        self._domains_crawled.clear()
        self._domain_page_counts.clear()
        self._last_request_by_domain.clear()
        self._failures_total = 0


__all__ = [
    "RobotsPolicy",
    "RobotsCache",
    "CrawlBudget",
    "CrawlResult",
    "BoundedCrawler",
    "_parse_robots_txt",
]
