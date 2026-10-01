"""Research engine: planned search, credibility, cross-source compare, citations."""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, urlencode, urlparse

from ..browser.agent import BrowserAgent
from ..core.types import now


TRUSTED = {"python.org", "docs.python.org", "github.com", "arxiv.org",
           "wikipedia.org", "stackoverflow.com", "readthedocs.io",
           "developer.mozilla.org", "docs.rs", "go.dev"}
UNTRUSTED_SUFFIX = (".tk", ".ml", ".ga", ".cf", ".gq")


@dataclass
class Source:
    url: str
    title: str = ""
    text: str = ""
    credibility: float = 0.4
    fetched: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"url": self.url, "title": self.title,
                "text": self.text[:800], "credibility": self.credibility,
                "fetched": self.fetched, "notes": self.notes}


@dataclass
class ResearchReport:
    query: str
    summary: str = ""
    sources: list[Source] = field(default_factory=list)
    agreements: list[str] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    confidence: float = 0.0
    at: float = field(default_factory=now)

    def to_dict(self) -> dict[str, Any]:
        return {"query": self.query, "summary": self.summary,
                "sources": [s.to_dict() for s in self.sources],
                "agreements": self.agreements,
                "contradictions": self.contradictions,
                "citations": self.citations,
                "confidence": round(self.confidence, 3)}


class ResearchEngine:
    def __init__(self, browser: BrowserAgent | None = None,
                 max_sources: int = 4) -> None:
        self.browser = browser or BrowserAgent()
        self.max_sources = max_sources
        self.reports: list[ResearchReport] = []

    @staticmethod
    def plan(query: str) -> dict[str, Any]:
        low = query.lower()
        kind = "howto" if any(w in low for w in ("how", "fix", "error", "install")) else \
               "factual" if any(w in low for w in ("what", "when", "who", "define")) else \
               "comparison" if any(w in low for w in ("vs", "versus", "compare", "best")) else \
               "general"
        return {"query": query, "kind": kind,
                "queries": [query] if kind != "comparison"
                else [query, query + " review", query + " comparison"],
                "depth": 3 if kind == "general" else 4}

    @classmethod
    def credibility(cls, url: str, words: int = 0) -> tuple[float, list[str]]:
        host = urlparse(url).netloc.lower().lstrip("www.")
        notes: list[str] = []
        if not url.startswith("https://"):
            return 0.2, ["not https"]
        score = 0.4
        if host in TRUSTED or any(host.endswith("." + base) for base in TRUSTED):
            score += 0.35
            notes.append("trusted domain")
        elif host.endswith(UNTRUSTED_SUFFIX):
            score -= 0.2
            notes.append("low-trust TLD")
        if words > 300:
            score += 0.1
            notes.append("substantive length")
        elif words < 50:
            score -= 0.1
            notes.append("thin content")
        return round(max(0.05, min(0.95, score)), 3), notes

    @staticmethod
    def _query_backoffs(query: str) -> list[str]:
        """Full query, then progressively shorter fallbacks."""
        words = [w for w in query.split() if len(w) > 2]
        variants = [query]
        if len(words) > 4:
            variants.append(" ".join(words[:4]))
        if len(words) > 2:
            variants.append(" ".join(words[:2]))
        return variants

    def wiki_search(self, query: str, count: int = 3) -> list[dict[str, str]]:
        """Wikipedia API search: stable, keyless, script-friendly."""
        out = []
        for variant in self._query_backoffs(query):
            params = urlencode(
                {"action": "query", "list": "search", "srsearch": variant,
                 "format": "json", "srlimit": count})
            try:
                req = urllib.request.Request(
                    "https://en.wikipedia.org/w/api.php?" + params,
                    headers={"User-Agent": "jarvis-os/0.1 research agent"})
                with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
                    data = json.loads(resp.read().decode())
            except Exception:
                continue
            hits = data.get("query", {}).get("search", [])[:count]
            if hits:
                for hit in hits:
                    title = hit.get("title", "")
                    if title:
                        out.append({
                            "title": title,
                            "url": "https://en.wikipedia.org/wiki/"
                                   + quote(title.replace(" ", "_"))})
                break
        return out

    def research(self, query: str) -> ResearchReport:
        plan = self.plan(query)
        report = ResearchReport(query=query)
        seen: set[str] = set()
        candidates: list[dict[str, str]] = []
        for sub in plan["queries"][:2]:
            found = self.browser.search(sub, count=self.max_sources)
            if found.get("ok"):
                candidates.extend(found.get("results", []))
        # Wikipedia always runs: stable when web search is throttled.
        candidates.extend(self.wiki_search(query, count=2))
        for hit in candidates[: self.max_sources * 2]:
            url = hit.get("url", "")
            if not url or url in seen:
                continue
            seen.add(url)
            source = Source(url=url, title=hit.get("title", ""))
            fetched = self.browser.fetch(url)
            if fetched.get("ok"):
                page = fetched["page"]
                source.title = page.get("title", source.title)
                source.text = page.get("text", "")[:2000]
                source.fetched = True
                source.credibility, source.notes = self.credibility(
                    url, page.get("words", 0))
            else:
                source.notes = [f"fetch failed: {fetched.get('error', '')[:80]}"]
            report.sources.append(source)
            if len(report.sources) >= self.max_sources:
                break
        self._compare(report)
        self.reports.append(report)
        return report

    @staticmethod
    def _compare(report: ResearchReport) -> None:
        import re
        sentences: dict[str, list[str]] = {}
        for source in report.sources:
            if not source.fetched:
                continue
            for sent in re.split(r"(?<=[.!?])\s+", source.text):
                key = " ".join(sorted(set(re.findall(r"[a-z]{5,}", sent.lower())))[:6])
                if len(key) > 12:
                    sentences.setdefault(key, []).append(source.url)
        for key, urls in sentences.items():
            if len(urls) >= 2:
                report.agreements.append(f"{len(urls)} sources agree: {key[:100]}")
        urls = [s.url for s in report.sources if s.fetched]
        report.citations = urls
        if report.sources:
            fetched = [s for s in report.sources if s.fetched]
            report.confidence = round(
                sum(s.credibility for s in fetched) / len(fetched)
                * min(1.0, len(fetched) / 2.0), 3) if fetched else 0.0
            top = sorted(fetched, key=lambda s: -s.credibility)[:2]
            sentences: list[str] = []
            for source in top:
                for sent in source.text.split(". "):
                    cleaned = sent.strip()
                    # Skip nav/chrome cruft: demand a substantive sentence.
                    if len(cleaned) > 60 and "menu" not in cleaned[:30].lower():
                        sentences.append(cleaned + ".")
                        break
            report.summary = " ".join(sentences)[:600]

    def history(self) -> list[dict[str, Any]]:
        return [r.to_dict() for r in self.reports]
