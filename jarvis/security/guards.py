"""Security guards: SSRF blocking, prompt-injection scan, safe fetch."""

from __future__ import annotations

import ipaddress
import re
import socket
import ssl
from typing import Any
from urllib.parse import urlparse

# Private/internal IP ranges that must never be reached
_PRIVATE_IP_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local
    ipaddress.ip_network("::1/128"),          # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),         # IPv6 ULA
    ipaddress.ip_network("fe80::/10"),        # IPv6 link-local
]

# Hostnames that resolve to internal addresses
_BLOCKED_HOSTNAMES = frozenset({
    "localhost", "localhost.localdomain", "localhost6", "localhost6.localdomain6",
    "metadata.google.internal", "169.254.169.254",  # GCP metadata
    "metadata", "metadata.novalocal",             # AWS/OpenStack metadata
    "metadata.azure.com",                         # Azure metadata
    "169.254.169.253",                            # Azure IMDS
    "local", "localdomain",                       # mDNS
})


INJECTION_PATTERNS = [
    # Direct instruction override
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.I),
    re.compile(r"ignore\s+your\s+(system\s+)?prompt", re.I),
    re.compile(r"disregard\s+(all\s+)?(prior|previous|above)", re.I),
    re.compile(r"^system\s*:", re.I | re.M),
    re.compile(r"you\s+are\s+now\s+(a|an)\s+\w+", re.I),
    # Credential extraction
    re.compile(r"reveal\s+(your\s+)?(system|secret|private|hidden)", re.I),
    re.compile(r"what\s+is\s+your\s+(system\s+)?prompt", re.I),
    re.compile(r"show\s+me\s+(your\s+)?(prompt|instructions)", re.I),
    # Tool/Action hijacking
    re.compile(r"execute\s+the\s+following\s+(as|with)", re.I),
    re.compile(r"run\s+(this|the following)\s+(code|command)", re.I),
    re.compile(r"!\s*\[.*\]\(.*\)\s*$", re.M),  # trailing markdown exfil images
    # Role confusion
    re.compile(r"act\s+as\s+(if\s+you\s+are\s+)?(a|an)\s+\w+", re.I),
    re.compile(r"pretend\s+(to\s+be|you\s+are)\s+(a|an)\s+\w+", re.I),
    # Jailbreak patterns
    re.compile(r"dan\s+mode", re.I),
    re.compile(r"developer\s+mode", re.I),
    re.compile(r"unrestricted\s+mode", re.I),
    # Chain of thought extraction
    re.compile(r"think\s+step\s+by\s+step\s+and\s+show\s+your\s+(work|reasoning)", re.I),
    re.compile(r"output\s+your\s+(reasoning|chain\s+of\s+thought)", re.I),
]


def is_safe_url(url: str) -> tuple[bool, str]:
    """Block non-http(s), private/internal targets, and metadata endpoints (SSRF guard)."""
    try:
        parts = urlparse(url)
    except ValueError as exc:
        return False, f"bad URL: {exc}"
    if parts.scheme not in ("http", "https"):
        return False, "only http(s) URLs are allowed"
    host = parts.hostname or ""
    if not host:
        return False, "no host"
    # Normalize host
    host = host.lower().strip(".")
    if host in _BLOCKED_HOSTNAMES:
        return False, f"blocked hostname: {host}"
    # Resolve and check all IPs
    try:
        infos = socket.getaddrinfo(host, parts.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return False, f"cannot resolve: {host}"
    for info in infos:
        try:
            ip_str = info[4][0]
            addr = ipaddress.ip_address(ip_str)
            if not addr.is_global:
                return False, f"non-public IP blocked: {addr}"
            # Extra check against private ranges
            for net in _PRIVATE_IP_RANGES:
                if addr in net:
                    return False, f"private IP range blocked: {addr} in {net}"
        except ValueError:
            return False, f"unparseable resolved IP: {info[4][0]}"
    return True, "ok"


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


def safe_getaddrinfo(host: str, port: int = 443) -> list[tuple[str, int]]:
    """Resolve hostname to public IPs only, for allow-listed connections."""
    safe, reason = is_safe_url(f"https://{host}:{port}")
    if not safe:
        return []
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return []
    out = []
    for info in infos:
        try:
            ip_str = info[4][0]
            addr = ipaddress.ip_address(ip_str)
            if addr.is_global:
                out.append((ip_str, port))
        except ValueError:
            continue
    return out


def verify_tls_hostname(conn: ssl.SSLSocket, hostname: str) -> bool:
    """Verify the peer certificate matches the expected hostname."""
    try:
        ssl.match_hostname(conn.getpeercert(), hostname)
        return True
    except Exception:
        return False


__all__ = [
    "is_safe_url",
    "scan_injection",
    "sanitize_for_context",
    "safe_getaddrinfo",
    "verify_tls_hostname",
    "INJECTION_PATTERNS",
]