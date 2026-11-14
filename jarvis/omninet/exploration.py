"""Advanced Browser Intelligence (M3).

Builds on existing jarvis/browser/agent.py (BrowserAgent) with:
- Table extraction from HTML
- Metadata extraction (OpenGraph, JSON-LD, meta tags)
- Page change detection (hash-based, historical comparison)
- OpenClaw browser integration wrapper (when available)
- Structured content extraction

Everything is PolicyEngine-gated via the existing InternetAccess.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

from ..browser.agent import BrowserAgent, Page
from ..core.internet import InternetAccess
from ..core.logging import get_module_logger
from ..core.types import ActionPlan, RiskLevel
from ..omninet.connectors import Connector, ConnectorResult, ConnectorSpec
from ..omninet.http_connector import HttpConnector
from ..policy.policy import PolicyEngine
from ..security.guards import is_safe_url, scan_injection

log = get_module_logger(__name__)


# ============================================================================
# Table extraction
# ============================================================================


class _TableExtractor(HTMLParser):
    """Extract HTML tables into structured data."""

    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._current_table: list[list[str]] | None = None
        self._current_row: list[str] | None = None
        self._current_cell: list[str] = []
        self._in_cell = False
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "noscript"):
            self._skip += 1
        if self._skip:
            return
        if tag == "table":
            self._current_table = []
        elif tag in ("tr",) and self._current_table is not None:
            self._current_row = []
        elif tag in ("td", "th") and self._current_row is not None:
            self._in_cell = True
            self._current_cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript") and self._skip:
            self._skip -= 1
        if self._skip:
            return
        if tag in ("td", "th") and self._in_cell:
            self._in_cell = False
            cell_text = " ".join(self._current_cell).strip()
            if self._current_row is not None:
                self._current_row.append(cell_text)
        elif tag == "tr" and self._current_row is not None:
            if self._current_table is not None:
                self._current_table.append(self._current_row)
            self._current_row = None
        elif tag == "table" and self._current_table is not None:
            self.tables.append(self._current_table)
            self._current_table = None

    def handle_data(self, data: str) -> None:
        if self._skip or not self._in_cell:
            return
        self._current_cell.append(data.strip())


def extract_tables(html: str) -> list[list[list[str]]]:
    """Extract all HTML tables as nested lists of strings."""
    parser = _TableExtractor()
    parser.feed(html[:2_000_000])
    return parser.tables


# ============================================================================
# Metadata extraction
# ============================================================================


@dataclass
class PageMetadata:
    """Structured metadata extracted from a page."""
    title: str = ""
    description: str = ""
    language: str = ""
    charset: str = ""
    author: str = ""
    published_time: str = ""
    modified_time: str = ""
    og_title: str = ""
    og_description: str = ""
    og_image: str = ""
    og_type: str = ""
    og_url: str = ""
    json_ld: list[dict[str, Any]] = field(default_factory=list)
    canonical_url: str = ""
    robots: str = ""
    viewport: str = ""
    generator: str = ""
    extraction_method: str = "html_parser"


def extract_metadata(html: str, url: str) -> PageMetadata:
    """Extract page metadata: title, description, OpenGraph, JSON-LD, meta tags."""
    metadata = PageMetadata()

    # Title
    title_match = re.search(
        r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if title_match:
        metadata.title = re.sub(r"\s+", " ", title_match.group(1)).strip()

    # Meta tags
    meta_pattern = re.compile(
        r'<meta[^>]+>',
        re.I,
    )
    for m in meta_pattern.finditer(html[:2_000_000]):
        tag = m.group(0)
        attrs = dict(
            re.findall(
                r'(\w+)=["\']([^"\']*)["\']', tag, re.I
            )
        )
        name = attrs.get("name", "").lower()
        property_ = attrs.get("property", "").lower()
        content = attrs.get("content", "")

        if name == "description":
            metadata.description = content
        elif name == "author":
            metadata.author = content
        elif name == "robots":
            metadata.robots = content
        elif name == "viewport":
            metadata.viewport = content
        elif name == "generator":
            metadata.generator = content
        elif name == "charset":
            metadata.charset = content
        elif name == "article:published_time":
            metadata.published_time = content
        elif name == "article:modified_time":
            metadata.modified_time = content
        elif property_ == "og:title":
            metadata.og_title = content
        elif property_ == "og:description":
            metadata.og_description = content
        elif property_ == "og:image":
            metadata.og_image = content
        elif property_ == "og:type":
            metadata.og_type = content
        elif property_ == "og:url":
            metadata.og_url = content

    # Canonical URL
    canon_match = re.search(
        r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)["\']',
        html, re.I)
    if canon_match:
        metadata.canonical_url = urljoin(url, canon_match.group(1))

    # JSON-LD
    jsonld_pattern = re.compile(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        re.I | re.S,
    )
    for m in jsonld_pattern.finditer(html[:2_000_000]):
        try:
            data = json.loads(m.group(1))
            metadata.json_ld.append(data)
        except (json.JSONDecodeError, ValueError):
            continue

    # Language
    lang_match = re.search(
        r'<html[^>]+lang=["\']([^"\']+)["\']', html, re.I)
    if lang_match:
        metadata.language = lang_match.group(1)

    return metadata


# ============================================================================
# Page change detection
# ============================================================================


@dataclass
class PageChange:
    """A detected change between two page snapshots."""
    url: str
    changed: bool
    old_hash: str = ""
    new_hash: str = ""
    old_word_count: int = 0
    new_word_count: int = 0
    detected_at: float = field(default_factory=time.monotonic)
    diff_summary: str = ""


class ChangeDetector:
    """Hash-based page change detection with historical comparison."""

    def __init__(self) -> None:
        self._snapshots: dict[str, dict[str, Any]] = {}  # url -> {hash, text, word_count, first_seen}

    def snapshot(self, url: str, text: str) -> dict[str, Any]:
        """Record a page snapshot. Returns the snapshot record."""
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        word_count = len(text.split())
        now_ts = time.monotonic()
        record = {
            "url": url,
            "hash": content_hash,
            "word_count": word_count,
            "first_seen": self._snapshots.get(url, {}).get("first_seen", now_ts),
            "last_seen": now_ts,
            "text": text[:5000],  # bounded storage
        }
        self._snapshots[url] = record
        return record

    def detect_change(self, url: str, text: str) -> PageChange:
        """Compare current text against the last snapshot."""
        new_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        new_word_count = len(text.split())
        old = self._snapshots.get(url)

        if old is None:
            # First time seeing this URL
            self.snapshot(url, text)
            return PageChange(
                url=url,
                changed=False,
                new_hash=new_hash,
                new_word_count=new_word_count,
                diff_summary="first snapshot recorded",
            )

        changed = old["hash"] != new_hash
        diff_summary = ""
        if changed:
            diff_summary = (
                f"content changed: {old['word_count']} -> {new_word_count} words, "
                f"hash {old['hash']} -> {new_hash}"
            )

        # Update snapshot
        self.snapshot(url, text)

        return PageChange(
            url=url,
            changed=changed,
            old_hash=old["hash"],
            new_hash=new_hash,
            old_word_count=old["word_count"],
            new_word_count=new_word_count,
            diff_summary=diff_summary,
        )

    def history(self, url: str) -> dict[str, Any] | None:
        """Return the snapshot history for a URL."""
        return self._snapshots.get(url)


# ============================================================================
# Enhanced browser agent (M3)
# ============================================================================


class EnhancedBrowserAgent:
    """Browser agent with table extraction, metadata, and change detection.

    Wraps the existing BrowserAgent and adds:
    - Structured table extraction
    - Metadata extraction (OpenGraph, JSON-LD, meta tags)
    - Page change detection
    - All fetches are PolicyEngine-gated via HttpConnector
    """

    def __init__(
        self,
        policy: PolicyEngine,
        internet: InternetAccess,
        actor: str = "jarvis",
        timeout: float = 15.0,
        max_bytes: int = 1_000_000,
    ) -> None:
        self.policy = policy
        self.internet = internet
        self.actor = actor
        self._base = BrowserAgent(timeout=timeout, max_bytes=max_bytes)
        self._http = HttpConnector(policy, internet, actor=actor,
                                   timeout=timeout, max_bytes=max_bytes)
        self._change_detector = ChangeDetector()
        self._extraction_history: list[dict[str, Any]] = []

    # -- fetch with full extraction --------------------------------------

    def fetch_and_extract(
        self,
        url: str,
        extract_tables_flag: bool = True,
        extract_metadata_flag: bool = True,
        detect_change_flag: bool = True,
        check_injection: bool = True,
    ) -> dict[str, Any]:
        """Fetch a URL and extract tables, metadata, and detect changes.

        Every fetch goes through HttpConnector (PolicyEngine-gated,
        SSRF-guarded, injection-scanned).
        """
        started = time.monotonic()

        # 1. SSRF guard before any request
        safe, reason = is_safe_url(url)
        if not safe:
            return {
                "ok": False,
                "error": f"SSRF guard: {reason}",
                "url": url,
            }

        # 2. Domain grant check
        domain = urlparse(url).netloc.lower()
        if not self.internet.can_access(self.actor, domain):
            return {
                "ok": False,
                "error": f"no internet grant for domain: {domain}",
                "url": url,
            }

        # 3. Fetch via HttpConnector (PolicyEngine-gated)
        result = self._http.fetch(url)
        if not result.ok:
            return {
                "ok": False,
                "error": result.error,
                "url": url,
                "latency_ms": result.latency_ms,
            }

        page_data = result.data
        html = page_data.get("text", "")

        # 4. Injection scan on response
        injection_flags = result.injection_flags
        if check_injection and injection_flags:
            log.warning("Injection markers detected in fetched page",
                        url=url, flags=injection_flags[:3])

        # 5. Base extraction (title, text, links, forms) via BrowserAgent
        base_page = self._base.extract(url, html)

        # 6. Table extraction
        tables = []
        if extract_tables_flag:
            try:
                tables = extract_tables(html)
            except Exception as exc:
                log.warning("Table extraction failed", url=url,
                            error=str(exc)[:120])

        # 7. Metadata extraction
        metadata = None
        if extract_metadata_flag:
            try:
                metadata = extract_metadata(html, url)
            except Exception as exc:
                log.warning("Metadata extraction failed", url=url,
                            error=str(exc)[:120])

        # 8. Change detection
        change = None
        if detect_change_flag:
            try:
                change = self._change_detector.detect_change(url, html)
            except Exception as exc:
                log.warning("Change detection failed", url=url,
                            error=str(exc)[:120])

        # 9. Record extraction
        latency_ms = round((time.monotonic() - started) * 1000, 2)
        extraction_record = {
            "url": url,
            "domain": domain,
            "fetched_at": time.monotonic(),
            "latency_ms": latency_ms,
            "bytes": page_data.get("bytes", 0),
            "tables_count": len(tables),
            "has_metadata": metadata is not None,
            "change_detected": change.changed if change else False,
            "injection_flags": injection_flags,
        }
        self._extraction_history.append(extraction_record)

        # Keep history bounded
        if len(self._extraction_history) > 500:
            self._extraction_history = self._extraction_history[-500:]

        return {
            "ok": True,
            "url": url,
            "domain": domain,
            "title": base_page.title,
            "text": base_page.text,
            "links": base_page.links,
            "forms": base_page.forms,
            "tables": tables,
            "metadata": {
                "title": metadata.title if metadata else "",
                "description": metadata.description if metadata else "",
                "og_title": metadata.og_title if metadata else "",
                "og_description": metadata.og_description if metadata else "",
                "og_image": metadata.og_image if metadata else "",
                "canonical_url": metadata.canonical_url if metadata else "",
                "language": metadata.language if metadata else "",
                "author": metadata.author if metadata else "",
                "published_time": metadata.published_time if metadata else "",
                "robots": metadata.robots if metadata else "",
                "json_ld_count": len(metadata.json_ld) if metadata else 0,
            } if metadata else {},
            "change": {
                "changed": change.changed if change else False,
                "old_hash": change.old_hash if change else "",
                "new_hash": change.new_hash if change else "",
                "old_word_count": change.old_word_count if change else 0,
                "new_word_count": change.new_word_count if change else 0,
                "diff_summary": change.diff_summary if change else "",
            } if change else {},
            "injection_flags": injection_flags,
            "latency_ms": latency_ms,
            "bytes": page_data.get("bytes", 0),
        }

    # -- search ----------------------------------------------------------

    def search(self, query: str, count: int = 5) -> dict[str, Any]:
        """Search using the base BrowserAgent (DuckDuckGo keyless)."""
        return self._base.search(query, count=count)

    # -- change detection history ----------------------------------------

    def change_history(self, url: str) -> dict[str, Any] | None:
        """Return change detection history for a URL."""
        return self._change_detector.history(url)

    def extraction_history(self) -> list[dict[str, Any]]:
        """Return all extraction records (bounded to 500)."""
        return list(self._extraction_history)

    def health(self) -> dict[str, Any]:
        """Return browser agent health status."""
        return {
            "extractions_total": len(self._extraction_history),
            "change_tracked_urls": len(self._change_detector._snapshots),
            "http_connector": self._http.health_check(),
        }


__all__ = [
    "PageMetadata",
    "PageChange",
    "extract_tables",
    "extract_metadata",
    "ChangeDetector",
    "EnhancedBrowserAgent",
]
