"""Security guards: SSRF blocking, prompt-injection scan, safe fetch."""

from __future__ import annotations

import ipaddress
import re
import socket
from typing import Any
from urllib.parse import urlparse


def is_safe_url(url: str) -> tuple[bool, str]:
    """Block non-http(s) and private/internal targets (SSRF guard)."""
    try:
        parts = urlparse(url)
    except ValueError as exc:
        return False, f"bad URL: {exc}"
    if parts.scheme not in ("http", "https"):
        return False, "only http(s) URLs are allowed"
    host = parts.hostname or ""
    if not host:
        return False, "no host"
    if host in ("localhost", "localhost.localdomain"):
        return False, "loopback hosts are blocked"
    try:
        addr = ipaddress.ip_address(host)
        if not addr.is_global:
            return False, f"non-public IP blocked: {addr}"
        return True, "literal public IP"
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, parts.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return False, f"cannot resolve: {host}"
    for info in infos:
        try:
            if not ipaddress.ip_address(info[4][0]).is_global:
                return False, f"host resolves to non-public IP: {info[4][0]}"
        except ValueError:
            return False, f"unparseable resolved IP: {info[4][0]}"
    return True, "ok"


INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.I),
    re.compile(r"ignore\s+your\s+(system\s+)?prompt", re.I),
    re.compile(r"disregard\s+(all\s+)?(prior|previous|above)", re.I),
    re.compile(r"^system\s*:", re.I | re.M),
    re.compile(r"you\s+are\s+now\s+(a|an)\s+\w+", re.I),
    re.compile(r"reveal\s+(your\s+)?(system|secret|private|hidden)", re.I),
    re.compile(r"execute\s+the\s+following\s+(as|with)", re.I),
    re.compile(r"!\s*\[.*\]\(.*\)\s*$", re.M),  # trailing markdown exfil images
]


def scan_injection(text: str) -> dict[str, Any]:
    """Detect prompt-injection attempts in untrusted content."""
    hits = sorted({pattern.pattern for pattern in INJECTION_PATTERNS
                   if pattern.search(text)})
    return {"clean": not hits, "hits": hits,
            "verdict": "clean" if not hits
            else f"injection markers: {', '.join(hits)}"}


def sanitize_for_context(text: str, limit: int = 2000) -> str:
    """Quote untrusted content so the model treats it as data, not orders."""
    clipped = text[:limit]
    return "<untrusted-content>\n" + clipped + "\n</untrusted-content>"
