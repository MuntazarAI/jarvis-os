"""Live Internet Observatory (M7).

Continuous monitoring for selected public information sources:
- AI developments, scientific publications, software releases
- Linux development, public infrastructure announcements
- Public news, security advisories, technology developments
- Public datasets, selected research topics

Supports scheduled retrieval, event detection, change detection,
importance classification, notifications, daily/weekly reports,
and historical comparison. All configurable schedules and resource limits.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any

from ..core.internet import InternetAccess
from ..core.logging import get_module_logger
from ..core.types import now
from ..omninet.crawler import BoundedCrawler, CrawlBudget
from ..omninet.discovery import SearchEngine
from ..omninet.public_data import default_public_data_registry
from ..omninet.exploration import EnhancedBrowserAgent
from ..policy.policy import PolicyEngine
from ..security.guards import is_safe_url

log = get_module_logger(__name__)


@dataclass
class MonitorSource:
    """A source to monitor continuously."""
    source_id: str
    name: str
    url: str
    kind: str  # news | rss | api | website | dataset | security
    check_interval_s: float = 3600.0  # 1 hour default
    enabled: bool = True
    last_checked: float = 0.0
    last_hash: str | None = None
    change_count: int = 0
    importance_threshold: float = 0.5  # 0.0-1.0
    tags: list[str] = field(default_factory=list)


@dataclass
class MonitorEvent:
    """A detected change or event from a monitored source."""
    event_id: str
    source_id: str
    source_name: str
    event_type: str  # change | new_content | importance_high | anomaly
    title: str
    description: str
    importance: float  # 0.0-1.0
    url: str
    detected_at: float = field(default_factory=time.monotonic)
    previous_hash: str | None = None
    current_hash: str | None = None
    tags: list[str] = field(default_factory=list)


@dataclass
class ObservatoryReport:
    """Daily or weekly observatory report."""
    report_id: str
    period: str  # daily | weekly
    generated_at: float = field(default_factory=time.monotonic)
    sources_monitored: int = 0
    events_detected: int = 0
    events: list[MonitorEvent] = field(default_factory=list)
    summary: str = ""
    top_events: list[dict[str, Any]] = field(default_factory=list)


class LiveObservatory:
    """Continuous monitoring of public information sources.

    Features:
    - Scheduled retrieval of configured sources
    - Change detection via content hashing
    - Importance classification
    - Event deduplication
    - Daily/weekly report generation
    - Resource-bounded (crawl budgets respected)
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
        self._sources: dict[str, MonitorSource] = {}
        self._events: list[MonitorEvent] = []
        self._crawler = BoundedCrawler(policy, internet, actor=actor,
                                       budget=CrawlBudget(max_pages=50,
                                                          max_domains=10,
                                                          max_depth=1))
        self._search = SearchEngine(policy, internet, actor=actor)
        self._browser = EnhancedBrowserAgent(policy, internet, actor=actor)
        self._event_counter: int = 0

    # -- source management ----------------------------------------------

    def add_source(self, source: MonitorSource) -> None:
        """Add a source to monitor."""
        self._sources[source.source_id] = source
        log.info("Monitor source added", source_id=source.source_id,
                 name=source.name, kind=source.kind)

    def remove_source(self, source_id: str) -> bool:
        """Remove a monitored source."""
        if source_id in self._sources:
            del self._sources[source_id]
            return True
        return False

    def list_sources(self) -> list[dict[str, Any]]:
        """List all monitored sources."""
        return [{
            "source_id": s.source_id,
            "name": s.name,
            "kind": s.kind,
            "check_interval_s": s.check_interval_s,
            "enabled": s.enabled,
            "last_checked": s.last_checked,
            "change_count": s.change_count,
            "tags": s.tags,
        } for s in self._sources.values()]

    def enable_source(self, source_id: str) -> bool:
        if source_id in self._sources:
            self._sources[source_id].enabled = True
            return True
        return False

    def disable_source(self, source_id: str) -> bool:
        if source_id in self._sources:
            self._sources[source_id].enabled = False
            return True
        return False

    # -- monitoring -----------------------------------------------------

    def check_source(self, source: MonitorSource) -> list[MonitorEvent]:
        """Check a single source for changes. Returns new events."""
        if not source.enabled:
            return []

        # Rate limiting: respect check interval
        now_ts = time.monotonic()
        if source.last_checked > 0 and \
                (now_ts - source.last_checked) < source.check_interval_s:
            return []

        source.last_checked = now_ts

        # Check domain grant
        from urllib.parse import urlparse
        domain = urlparse(source.url).netloc.lower()
        if not self.internet.can_access(self.actor, domain):
            log.warning("No internet grant for monitored source",
                        source=source.name, domain=domain)
            return []

        # SSRF guard
        safe, reason = is_safe_url(source.url)
        if not safe:
            log.warning("SSRF guard blocked source",
                        source=source.name, reason=reason)
            return []

        # Fetch current content
        result = self._browser.fetch_and_extract(
            source.url,
            extract_tables_flag=False,
            extract_metadata_flag=True,
            detect_change_flag=False,
        )

        if not result.get("ok"):
            log.warning("Failed to fetch monitored source",
                        source=source.name, error=result.get("error"))
            return []

        current_text = result.get("text", "")
        current_hash = hashlib.sha256(current_text.encode("utf-8")).hexdigest()[:16]

        events: list[MonitorEvent] = []

        if source.last_hash is None:
            # First time seeing this source
            source.last_hash = current_hash
            source.change_count = 0
            return events

        if current_hash != source.last_hash:
            # Content changed
            source.change_count += 1
            importance = self._assess_importance(
                source, result, current_hash)

            event = MonitorEvent(
                event_id=f"evt-{self._event_counter}",
                source_id=source.source_id,
                source_name=source.name,
                event_type="change",
                title=result.get("title", source.name)[:200],
                description=f"Content changed on {source.name}",
                importance=importance,
                url=source.url,
                previous_hash=source.last_hash,
                current_hash=current_hash,
                tags=list(source.tags),
            )
            self._event_counter += 1
            events.append(event)
            self._events.append(event)
            source.last_hash = current_hash

        return events

    def check_all_sources(self) -> list[MonitorEvent]:
        """Check all enabled sources for changes."""
        all_events: list[MonitorEvent] = []
        for source in self._sources.values():
            try:
                events = self.check_source(source)
                all_events.extend(events)
            except Exception as exc:
                log.warning("Error checking source",
                            source=source.name, error=str(exc)[:120])
        return all_events

    def _assess_importance(
        self,
        source: MonitorSource,
        result: dict[str, Any],
        current_hash: str,
    ) -> float:
        """Assess importance of a change (0.0-1.0)."""
        importance = 0.5  # baseline

        # Higher importance for security/tech sources
        if source.kind in ("security", "software"):
            importance += 0.2
        if any(t in ("security", "cve", "vulnerability") for t in source.tags):
            importance += 0.15

        # Higher importance for larger changes
        word_count = len(result.get("text", "").split())
        if word_count > 1000:
            importance += 0.1
        elif word_count > 500:
            importance += 0.05

        # Metadata signals
        metadata = result.get("metadata", {})
        if metadata.get("og_title"):
            importance += 0.05

        return min(1.0, importance)

    # -- reporting ------------------------------------------------------

    def get_events(
        self,
        since: float | None = None,
        min_importance: float = 0.0,
        limit: int = 100,
    ) -> list[MonitorEvent]:
        """Get events, optionally filtered by time and importance."""
        events = self._events
        if since is not None:
            events = [e for e in events if e.detected_at >= since]
        if min_importance > 0:
            events = [e for e in events if e.importance >= min_importance]
        events.sort(key=lambda e: -e.detected_at)
        return events[:limit]

    def generate_report(self, period: str = "daily") -> ObservatoryReport:
        """Generate a daily or weekly report."""
        now_ts = time.monotonic()

        if period == "daily":
            since = now_ts - 86400.0  # 24 hours
        elif period == "weekly":
            since = now_ts - 604800.0  # 7 days
        else:
            since = 0.0

        events = self.get_events(since=since)

        # Top events by importance
        top = sorted(events, key=lambda e: -e.importance)[:10]

        # Summary
        high_importance = [e for e in events if e.importance >= 0.7]
        summary = (
            f"Monitored {len(self._sources)} sources. "
            f"Detected {len(events)} events in the past {period}. "
            f"{len(high_importance)} high-importance events."
        )

        report = ObservatoryReport(
            report_id=f"report-{period}-{int(now_ts)}",
            period=period,
            sources_monitored=len(self._sources),
            events_detected=len(events),
            events=events,
            summary=summary,
            top_events=[{
                "event_id": e.event_id,
                "source": e.source_name,
                "title": e.title,
                "importance": e.importance,
                "detected_at": e.detected_at,
                "url": e.url,
            } for e in top],
        )
        return report

    # -- quick setup ----------------------------------------------------

    def add_default_sources(self) -> None:
        """Add a default set of public monitoring sources."""
        defaults = [
            MonitorSource(
                source_id="hn-tech",
                name="Hacker News",
                url="https://news.ycombinator.com",
                kind="news",
                check_interval_s=1800.0,
                tags=["tech", "startups"],
            ),
            MonitorSource(
                source_id="arxiv-ai",
                name="arXiv AI",
                url="https://arxiv.org/list/cs.AI/recent",
                kind="academic",
                check_interval_s=7200.0,
                tags=["ai", "research", "papers"],
            ),
            MonitorSource(
                source_id="github-security",
                name="GitHub Security Advisories",
                url="https://github.com/advisories",
                kind="security",
                check_interval_s=3600.0,
                tags=["security", "vulnerabilities"],
            ),
            MonitorSource(
                source_id="python-releases",
                name="Python Releases",
                url="https://www.python.org/downloads/",
                kind="software",
                check_interval_s=86400.0,
                tags=["python", "releases"],
            ),
        ]
        for src in defaults:
            # Only add if domain has internet grant
            from urllib.parse import urlparse
            domain = urlparse(src.url).netloc.lower()
            if self.internet.can_access(self.actor, domain):
                self.add_source(src)

    # -- status ---------------------------------------------------------

    def status(self) -> dict[str, Any]:
        return {
            "sources_monitored": len(self._sources),
            "sources_enabled": sum(1 for s in self._sources.values()
                                   if s.enabled),
            "events_total": len(self._events),
            "events_last_24h": len(self.get_events(
                since=time.monotonic() - 86400.0)),
            "crawler_stats": self._crawler.stats(),
        }


__all__ = [
    "MonitorSource",
    "MonitorEvent",
    "ObservatoryReport",
    "LiveObservatory",
]
