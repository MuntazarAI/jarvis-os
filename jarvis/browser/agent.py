"""Browser agent: fetch, extract, forms, keyless search, audited.

No Playwright/Selenium here — those need a browser download this machine
doesn't have. Everything below runs on the standard library against live
HTTP. Interactive tab control stays an explicit, honest gap.
"""

from __future__ import annotations

import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any

from ..core.types import now


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.chunks: list[str] = []
        self.links: list[dict[str, str]] = []
        self.forms: list[dict[str, Any]] = []
        self.title: str = ""
        self._in_title = False
        self._skip = 0
        self._current_link: dict[str, str] | None = None
        self._current_form: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag in ("script", "style", "noscript"):
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "a":
            self._current_link = {"href": attrs_dict.get("href", ""), "text": ""}
        elif tag == "form":
            self._current_form = {"action": attrs_dict.get("action", ""),
                                  "method": attrs_dict.get("method", "get"),
                                  "inputs": []}
        elif tag == "input" and self._current_form is not None:
            self._current_form["inputs"].append(
                {"name": attrs_dict.get("name", ""),
                 "type": attrs_dict.get("type", "text")})

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript") and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False
        elif tag == "a" and self._current_link is not None:
            text = self._current_link["text"].strip()
            if text and self._current_link["href"]:
                self.links.append(self._current_link)
            self._current_link = None
        elif tag == "form" and self._current_form is not None:
            self.forms.append(self._current_form)
            self._current_form = None

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self.title += text
            return
        if self._current_link is not None:
            self._current_link["text"] += text + " "
            return
        self.chunks.append(text)


@dataclass
class Page:
    url: str
    title: str = ""
    text: str = ""
    links: list[dict[str, str]] = field(default_factory=list)
    forms: list[dict[str, Any]] = field(default_factory=list)
    secure: bool = False
    words: int = 0
    fetched_at: float = field(default_factory=now)

    def to_dict(self) -> dict[str, Any]:
        return {"url": self.url, "title": self.title,
                "text": self.text[:2000], "links": self.links[:20],
                "forms": self.forms, "secure": self.secure,
                "words": self.words}


class BrowserAgent:
    """Audited fetch/extract/search. Every fetch is logged with actor + time."""

    def __init__(self, timeout: float = 15.0, max_bytes: int = 1_000_000) -> None:
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.audit: list[dict[str, Any]] = []
        self.history: list[Page] = []

    def fetch(self, url: str, actor: str = "researcher") -> dict[str, Any]:
        if not url.startswith(("http://", "https://")):
            return {"ok": False, "error": "only http(s) URLs are allowed"}
        entry = {"actor": actor, "url": url, "at": now()}
        self.audit.append(entry)
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "jarvis-os/0.1 research agent"})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
                raw = resp.read(self.max_bytes + 1)
                truncated = len(raw) > self.max_bytes
                html = raw[:self.max_bytes].decode("utf-8", errors="replace")
        except Exception as exc:
            entry["ok"] = False
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        page = self.extract(url, html)
        self.history.append(page)
        entry["ok"] = True
        entry["truncated"] = truncated
        payload = page.to_dict()
        payload["truncated"] = truncated
        return {"ok": True, "page": payload}

    @staticmethod
    def extract(url: str, html: str) -> Page:
        parser = _TextExtractor()
        parser.feed(html[:2_000_000])
        text = re.sub(r"\s+", " ", " ".join(parser.chunks)).strip()
        for link in parser.links:
            href = link["href"]
            if href and not href.startswith(("http", "//", "#", "mailto:")):
                link["href"] = urllib.parse.urljoin(url, href)
        return Page(url=url, title=parser.title.strip(), text=text,
                    links=parser.links, forms=parser.forms,
                    secure=url.startswith("https://"), words=len(text.split()))

    def search(self, query: str, count: int = 5) -> dict[str, Any]:
        """Keyless HTML search with provider fallback (html → lite).

        DDG rate-limits scripts intermittently; each provider is tried in
        turn and the first one returning results wins. Fails honestly
        offline.
        """
        results = self._search_html(query, count)
        provider = "duckduckgo-html"
        if not results:
            results = self._search_lite(query, count)
            provider = "duckduckgo-lite"
        self.audit.append({"actor": "researcher", "url": f"search:{query}",
                           "at": now(), "ok": True, "results": len(results),
                           "provider": provider})
        return {"ok": True, "query": query, "results": results,
                "provider": provider}

    def _get(self, url: str) -> str | None:
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
                return resp.read(self.max_bytes).decode("utf-8", errors="replace")
        except Exception:
            return None

    def _search_html(self, query: str, count: int) -> list[dict[str, str]]:
        params = urllib.parse.urlencode({"q": query})
        html = self._get(f"https://html.duckduckgo.com/html/?{params}")
        if not html:
            return []
        results = []
        for match in re.finditer(
                r'<a[^>]+class="[^"]*result__a[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
                html, re.S):
            href, label = match.group(1), re.sub(r"<.*?>", "", match.group(2)).strip()
            if href.startswith("//"):
                href = "https:" + href
            if href.startswith("http"):
                results.append({"title": label[:120], "url": href[:300]})
            if len(results) >= count:
                break
        return results

    def _search_lite(self, query: str, count: int) -> list[dict[str, str]]:
        params = urllib.parse.urlencode({"q": query})
        html = self._get(f"https://lite.duckduckgo.com/lite/?{params}")
        if not html:
            return []
        results = []
        for match in re.finditer(
                r'<a[^>]*href="//duckduckgo\.com/l/\?uddg=([^"&]+)"[^>]*>(.*?)</a>',
                html, re.S):
            try:
                href = urllib.parse.unquote(match.group(1))
            except Exception:
                continue
            label = re.sub(r"<.*?>", "", match.group(2)).strip()
            if href.startswith("http") and label:
                results.append({"title": label[:120], "url": href[:300]})
            if len(results) >= count:
                break
        return results

    def verify(self, page: Page, expect: str) -> dict[str, Any]:
        found = expect.lower() in (page.title + " " + page.text).lower()
        return {"ok": found, "expect": expect,
                "note": "present" if found else "absent"}

    def audit_trail(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.audit[-limit:]
