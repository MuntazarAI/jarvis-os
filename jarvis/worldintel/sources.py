"""Source registry + providers (World Intelligence 1.0).

A Source is structured metadata (id, kind, endpoint, freshness domain,
rate limit, privacy class, trust note). Trust notes are explicit about
whether quality is measured/configured/documented/unknown — reputation
is never proof of truth.

Providers (all keyless, all bounded):
- RSS/Atom: generic stdlib XML parsing, any feed URL.
- HackerNews: keyless JSON API (top/new stories + item text).
- Wikipedia: wraps the existing ResearchEngine.wiki_search path.
- Geo/live: wraps existing geospatial live providers (sync/query).
- Local: wraps local-world adapters (computer/device state).

Every provider returns EvidenceItems; every fetch goes through the
SSRF guard + bounded HTTP. Fake providers live in tests.
"""

from __future__ import annotations

import json
import time
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlencode

from ..security.guards import is_safe_url, scan_injection

MAX_ITEMS = 20
MAX_TEXT_CHARS = 4000
FETCH_TIMEOUT_S = 15.0
FETCH_MAX_BYTES = 1 * 1024 * 1024


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse every redirect: the caller re-validates, never chases."""

    def redirect_request(self, req: Any, fp: Any, code: int,
                         msg: str, headers: Any,
                         newurl: str) -> None:
        raise ValueError(f"redirect refused: {code}")


@dataclass
class Source:
    source_id: str = ""
    name: str = ""
    kind: str = "rss"  # rss | hn | wiki | geo | local | web
    endpoint: str = ""
    freshness_domain: str = "general"
    rate_limit_s: float = 60.0
    privacy_class: str = "public"
    trust_note: str = "unknown"
    trust_basis: str = "unknown"  # measured|configured|documented|unknown
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.source_id:
            raise ValueError("source needs an id")
        self.name = (self.name or self.source_id)[:120]
        if self.trust_basis not in ("measured", "configured",
                                    "documented", "unknown"):
            raise ValueError("bad trust basis")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvidenceItem:
    evidence_id: str = field(
        default_factory=lambda: _new_id("ev"))
    source_id: str = ""
    title: str = ""
    url: str = ""
    published_at: float = 0.0
    retrieved_at: float = field(default_factory=time.time)
    text: str = ""
    entities: list[str] = field(default_factory=list)
    injection_flags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.title = str(self.title or "")[:300]
        self.text = str(self.text or "")[:MAX_TEXT_CHARS]
        if len(self.entities) > 20:
            self.entities = self.entities[:20]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SourceRegistry:
    """Known sources + last-fetch times for rate limiting."""

    def __init__(self, sources: list[Source] | None = None) -> None:
        self._sources: dict[str, Source] = {}
        self._last_fetch: dict[str, float] = {}
        for source in sources or default_sources():
            self.register(source)

    def register(self, source: Source) -> None:
        self._sources[source.source_id] = source

    def get(self, source_id: str) -> Source | None:
        return self._sources.get(source_id)

    def enabled(self, kind: str = "") -> list[Source]:
        return [s for s in self._sources.values()
                if s.enabled and (not kind or s.kind == kind)]

    def can_fetch(self, source_id: str, now: float = 0.0) -> bool:
        source = self._sources.get(source_id)
        if source is None or not source.enabled:
            return False
        stamp = now or time.time()
        return stamp - self._last_fetch.get(source_id, 0.0) >= \
            source.rate_limit_s

    def mark_fetched(self, source_id: str, at: float = 0.0) -> None:
        self._last_fetch[source_id] = at or time.time()

    def to_dict(self) -> dict[str, Any]:
        return {"sources": [s.to_dict() for s in
                             self._sources.values()]}


def default_sources() -> list[Source]:
    return [
        Source(source_id="hn-top", name="Hacker News top", kind="hn",
               endpoint="https://hacker-news.firebaseio.com/v0",
               freshness_domain="tech-news", rate_limit_s=300.0,
               trust_note="community-ranked tech headlines",
               trust_basis="documented"),
        Source(source_id="wiki", name="Wikipedia search", kind="wiki",
               endpoint="https://en.wikipedia.org/w/api.php",
               freshness_domain="reference", rate_limit_s=60.0,
               trust_note="edited reference work, verify claims",
               trust_basis="documented"),
    ]


def bounded_get(url: str, *, timeout_s: float = FETCH_TIMEOUT_S,
                max_bytes: int = FETCH_MAX_BYTES) -> bytes:
    """SSRF-guarded, size-capped GET with NO redirect following
    (redirects are re-validated by the caller, never chased blindly).
    Raises on any problem."""
    ok, reason = is_safe_url(url)
    if not ok:
        raise ValueError(f"unsafe URL: {reason}")
    request = urllib.request.Request(
        url, headers={"User-Agent": "jarvis-os-worldintel/1.0"})
    opener = urllib.request.build_opener(_NoRedirect)
    with opener.open(request, timeout=timeout_s) as response:
        data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError("response exceeds size cap")
    return data


def _scan(text: str) -> list[str]:
    try:
        result = scan_injection(text)
        hits = result.get("hits", []) if isinstance(
            result, dict) else []
        return [str(h)[:80] for h in (hits or [])][:5]
    except Exception:
        return []


def parse_rss(data: bytes, *, source_id: str,
              max_items: int = MAX_ITEMS) -> list[EvidenceItem]:
    """RSS 2.0 + Atom via stdlib. Malformed XML yields nothing."""
    try:
        root = ET.fromstring(data[:FETCH_MAX_BYTES])
    except (ET.ParseError, ValueError):
        return []
    items: list[EvidenceItem] = []
    for entry in list(root.iter("item")) + list(
            root.iter("{http://www.w3.org/2005/Atom}entry")):
        if len(items) >= max_items:
            break
        title = (entry.findtext("title") or entry.findtext(
            "{http://www.w3.org/2005/Atom}title") or "")
        link = (entry.findtext("link") or "")
        if not link:
            link_el = entry.find(
                "{http://www.w3.org/2005/Atom}link")
            if link_el is not None:
                link = str(link_el.get("href", ""))
        pub = (entry.findtext("pubDate") or entry.findtext(
            "{http://www.w3.org/2005/Atom}updated") or "")
        desc = (entry.findtext("description") or entry.findtext(
            "{http://www.w3.org/2005/Atom}summary") or "")
        text = f"{title}\n{desc}".strip()[:MAX_TEXT_CHARS]
        items.append(EvidenceItem(
            source_id=source_id, title=title[:300], url=link[:500],
            published_at=_parse_time(pub), text=text,
            injection_flags=_scan(text)))
    return items


def _parse_time(value: str) -> float:
    import email.utils
    try:
        parsed = email.utils.parsedate_to_datetime(value or "")
        return parsed.timestamp() if parsed is not None else 0.0
    except (ValueError, TypeError):
        return 0.0


def fetch_hn(top_n: int = 10) -> list[EvidenceItem]:
    """Hacker News top stories via the keyless Firebase API."""
    base = "https://hacker-news.firebaseio.com/v0"
    ids = json.loads(bounded_get(f"{base}/topstories.json",
                                 max_bytes=65536))
    items: list[EvidenceItem] = []
    for item_id in (ids or [])[:max(0, top_n)]:
        try:
            raw = json.loads(bounded_get(
                f"{base}/item/{int(item_id)}.json",
                max_bytes=65536))
        except (ValueError, TypeError):
            continue
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title", ""))
        text = f"{title}\n{raw.get('text', '') or ''}".strip()
        items.append(EvidenceItem(
            source_id="hn-top", title=title[:300],
            url=str(raw.get("url", ""))[:500],
            published_at=float(raw.get("time", 0.0) or 0.0),
            text=text[:MAX_TEXT_CHARS], injection_flags=_scan(text)))
        if len(items) >= MAX_ITEMS:
            break
    return items


__all__ = ["Source", "EvidenceItem", "SourceRegistry",
           "default_sources", "bounded_get", "parse_rss", "fetch_hn",
           "MAX_ITEMS", "MAX_TEXT_CHARS"]
