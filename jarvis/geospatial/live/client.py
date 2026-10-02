"""Bounded HTTP client for live providers.

Keyless GET + JSON only. Redirects are refused (SSRF guard), payloads are
size-capped, timeouts are bounded, and every URL passes
``security.guards.is_safe_url`` before any socket opens. A fake transport
can be injected for deterministic tests — no network in the test suite.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable


class LiveHttpError(RuntimeError):
    """Raised when a live fetch fails safely (no partial trust)."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str,
                         headers: Any, newurl: str) -> Any:
        raise LiveHttpError(f"redirect refused: {code} -> {newurl}")


def default_fetch(url: str, timeout_s: float, max_bytes: int) -> tuple[int, bytes, str]:
    """Real network fetch. Returns (status, body, content_type)."""
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(
        url, method="GET", headers={"User-Agent": "jarvis-os-live/3.7"})
    try:
        with opener.open(request, timeout=timeout_s) as response:
            status = int(getattr(response, "status", 200))
            content_type = str(response.headers.get("Content-Type", ""))
            body = response.read(max_bytes + 1)
    except LiveHttpError:
        raise
    except urllib.error.HTTPError as exc:
        raise LiveHttpError(f"http {exc.code} for {url}") from None
    except Exception as exc:
        raise LiveHttpError(f"fetch failed for {url}: {exc}") from None
    return status, body, content_type


class BoundedHttpClient:
    """Size/time/redirect-bounded JSON fetcher with SSRF gating."""

    def __init__(self, timeout_s: float = 20.0, max_bytes: int = 2 * 1024 * 1024,
                 fetch: Callable[..., tuple[int, bytes, str]] | None = None) -> None:
        self.timeout_s = timeout_s
        self.max_bytes = max_bytes
        self._fetch = fetch or default_fetch

    def fetch_json(self, url: str) -> Any:
        from ...security.guards import is_safe_url
        ok, reason = is_safe_url(url)
        if not ok:
            raise LiveHttpError(f"unsafe URL refused: {reason}")
        status, body, _content_type = self._fetch(url, self.timeout_s, self.max_bytes)
        if status < 200 or status >= 300:
            raise LiveHttpError(f"http {status} for {url}")
        if len(body) > self.max_bytes:
            raise LiveHttpError(f"payload over cap ({len(body)} > {self.max_bytes})")
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise LiveHttpError(f"invalid JSON from {url}: {exc}") from None
