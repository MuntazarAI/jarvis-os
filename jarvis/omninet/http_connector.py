"""HTTP / HTTPS REST connector (M1).

Every fetch is:
- SSRF-guarded (is_safe_url blocks private IPs, non-http(s), redirects)
- PolicyEngine-gated (requires net.fetch permission per domain)
- Size-capped and timeout-bounded
- Injection-scanned on response
"""

from __future__ import annotations

import time
import urllib.request
from typing import Any
from urllib.parse import urlparse

from ..core.internet import InternetAccess
from ..core.types import RiskLevel
from ..policy.policy import PolicyEngine
from .connectors import Connector, ConnectorResult, ConnectorSpec


class HttpConnector(Connector):
    """HTTP/HTTPS REST connector with PolicyEngine gating."""

    def __init__(
        self,
        policy: PolicyEngine,
        internet: InternetAccess,
        actor: str = "jarvis",
        timeout: float = 15.0,
        max_bytes: int = 1_000_000,
    ) -> None:
        spec = ConnectorSpec(
            name="http",
            kind="http",
            description="HTTP/HTTPS REST connector with PolicyEngine gating",
            timeout_s=timeout,
            max_bytes=max_bytes,
            trust_note="stdlib urllib, SSRF-guarded, policy-gated",
            trust_basis="configured",
        )
        super().__init__(spec, policy, internet, actor=actor)
        self.timeout = timeout
        self.max_bytes = max_bytes

    def fetch(self, url: str, **kwargs: Any) -> ConnectorResult:
        started = time.monotonic()
        method = kwargs.get("method", "GET").upper()
        headers = kwargs.get("headers", {}) or {}
        required_permissions = kwargs.get(
            "required_permissions", ["net.fetch"]
        )

        # 1. PolicyEngine gate
        decision = self._evaluate(
            action=f"http.{method.lower()}.{url}",
            args={"url": url, "method": method, "headers": headers},
            required_permissions=required_permissions,
        )
        if not decision.allow:
            return ConnectorResult(
                connector=self.spec.name,
                kind=self.spec.kind,
                ok=False,
                error=f"policy denied: {'; '.join(decision.reasons)}",
                latency_ms=round((time.monotonic() - started) * 1000, 2),
            )

        # 2. Domain grant check via InternetAccess
        domain = urlparse(url).netloc.lower()
        if not self.internet.can_access(self.actor, domain):
            return ConnectorResult(
                connector=self.spec.name,
                kind=self.spec.kind,
                ok=False,
                error=f"no internet grant for domain: {domain}",
                latency_ms=round((time.monotonic() - started) * 1000, 2),
            )

        # 3. SSRF guard
        safe, reason = self._guard_url(url)
        if not safe:
            self._failures_total += 1
            return ConnectorResult(
                connector=self.spec.name,
                kind=self.spec.kind,
                ok=False,
                error=f"SSRF guard: {reason}",
                latency_ms=round((time.monotonic() - started) * 1000, 2),
            )

        # 4. Quota check
        if not self.within_quota():
            self._failures_total += 1
            return ConnectorResult(
                connector=self.spec.name,
                kind=self.spec.kind,
                ok=False,
                error="connector quota exceeded",
                latency_ms=round((time.monotonic() - started) * 1000, 2),
            )

        # 5. Execute fetch
        self._active += 1
        self._requests_total += 1
        try:
            req_headers = {"User-Agent": "jarvis-os/0.1 OMNINET research agent"}
            req_headers.update(headers)
            req = urllib.request.Request(url, headers=req_headers, method=method)
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
                raw = resp.read(self.max_bytes + 1)
                truncated = len(raw) > self.max_bytes
                html = raw[: self.max_bytes].decode("utf-8", errors="replace")
                status = resp.getcode()
                final_url = resp.geturl()
        except Exception as exc:
            self._failures_total += 1
            return ConnectorResult(
                connector=self.spec.name,
                kind=self.spec.kind,
                ok=False,
                error=f"{type(exc).__name__}: {exc}",
                latency_ms=round((time.monotonic() - started) * 1000, 2),
            )
        finally:
            self._active -= 1

        # 6. Injection scan on response
        from ..security.guards import scan_injection
        scan = scan_injection(html)
        injection_flags = [str(h)[:80] for h in (scan.get("hits", []) or [])][:5]

        self._bytes_total += len(raw)
        latency_ms = round((time.monotonic() - started) * 1000, 2)

        # Record request for internet rate limiting
        self.internet.record_request(self.actor, domain)

        return ConnectorResult(
            connector=self.spec.name,
            kind=self.spec.kind,
            ok=True,
            data={
                "url": final_url,
                "status": status,
                "text": html,
                "truncated": truncated,
                "bytes": len(raw),
                "headers": dict(resp.headers),
            },
            error="",
            latency_ms=latency_ms,
            bytes_read=len(raw),
            injection_flags=injection_flags,
        )


__all__ = ["HttpConnector"]
