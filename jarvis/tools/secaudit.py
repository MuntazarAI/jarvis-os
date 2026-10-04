"""Defensive security-audit tools (read-only posture, explicit scope).

Each wrapper runs ONE fixed-safe invocation (argv list, no shell),
validates the target up front, caps time and output, and reports
honestly when a binary or resource (e.g. wordlist) is missing.

Deliberately absent: brute-force execution, exploitation/dump modes,
wireless attacks, or any autonomous attack. Those stay manual
tools in the operator's hands and are never exposed here.

Authorization: every tool declares HIGH risk + a dedicated permission
so PolicyEngine + approvals gate each use. Scope comes from the
operator's explicit arguments, never inferred.
"""

from __future__ import annotations

import ipaddress
import shutil
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


def _binary(name: str) -> str | None:
    return shutil.which(name)


def _fail(tool: str, error: str) -> dict[str, Any]:
    return {"ok": False, "tool": tool, "error": error[:300]}


def _run(tool: str, argv: list[str], timeout_s: float,
         cap: int = 20000) -> dict[str, Any]:
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=min(timeout_s, 300.0))
    except subprocess.TimeoutExpired:
        return _fail(tool, f"timed out after {timeout_s}s")
    except (OSError, subprocess.SubprocessError) as exc:
        return _fail(tool, f"{type(exc).__name__}: {exc}")
    out = (proc.stdout or "")[-cap:]
    err = (proc.stderr or "")[-2000:]
    return {"ok": proc.returncode == 0, "tool": tool,
            "returncode": proc.returncode, "output": out,
            "stderr": err}


def validate_target(target: str) -> tuple[bool, str]:
    """Explicit-scope validation. Refuses empty, overbroad, and
    non-target inputs. LAN ranges are allowed ONLY as explicit /24 or
    smaller — never wider, never the whole internet."""
    target = (target or "").strip()
    if not target:
        return False, "target required: name an explicit host or network"
    lowered = target.lower()
    if lowered in ("0.0.0.0/0", "::/0", "internet", "everyone",
                   "all", "*"):
        return False, "overbroad target refused"
    if "/" in target:
        try:
            net = ipaddress.ip_network(target, strict=False)
        except ValueError:
            return False, "bad network notation"
        if net.num_addresses > 256:
            return False, "network too wide (max /24)"
        if net.is_multicast or net.is_reserved or \
                net.is_unspecified:
            return False, "non-routable target refused"
        return True, "ok"
    try:
        addr = ipaddress.ip_address(target)
    except ValueError:
        return True, "ok"  # hostname: operator-named
    if addr.is_multicast or addr.is_reserved or \
            addr.is_unspecified or addr.is_loopback:
        return False, "non-routable target refused"
    return True, "ok"  # single global or LAN host: operator-named


def validate_url(url: str) -> tuple[bool, str]:
    try:
        parts = urlparse(url)
    except ValueError:
        return False, "bad URL"
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return False, "only http(s) URLs with a host"
    host = parts.hostname
    if host in ("localhost", "localhost.localdomain"):
        return False, "loopback refused (use explicit LAN address)"
    return True, "ok"


def net_inventory(target: str, timeout_s: float = 120.0
                  ) -> dict[str, Any]:
    """Ping-scan one host or /24: who is up, nothing more. No port
    scan, no OS detection, no scripts in v1."""
    binary = _binary("nmap")
    if binary is None:
        return _fail("net_inventory", "nmap not installed")
    ok, reason = validate_target(target)
    if not ok:
        return _fail("net_inventory", reason)
    return _run("net_inventory",
                [binary, "-sn", "-T4", "--max-retries", "1", target],
                timeout_s)


def web_audit(url: str, timeout_s: float = 240.0) -> dict[str, Any]:
    """Nikto scan of one URL you named. Findings reported, nothing
    exploited."""
    binary = _binary("nikto")
    if binary is None:
        return _fail("web_audit", "nikto not installed")
    ok, reason = validate_url(url)
    if not ok:
        return _fail("web_audit", reason)
    return _run("web_audit",
                [binary, "-h", url, "-Tuning", "x", "-timeout", "10"],
                timeout_s)


def dir_enum(url: str, wordlist: str, timeout_s: float = 180.0
             ) -> dict[str, Any]:
    """Gobuster directory enum with YOUR wordlist file. No bundled
    wordlist is assumed; missing file fails honestly."""
    binary = _binary("gobuster")
    if binary is None:
        return _fail("dir_enum", "gobuster not installed")
    ok, reason = validate_url(url)
    if not ok:
        return _fail("dir_enum", reason)
    path = Path(wordlist or "").expanduser()
    if not path.is_file():
        return _fail("dir_enum",
                     "wordlist file required and must exist")
    return _run("dir_enum",
                [binary, "dir", "-u", url, "-w", str(path),
                 "-q", "-t", "10", "-timeout", "10s"],
                timeout_s)


def hash_audit(hashfile: str, wordlist: str,
               tool: str = "john", timeout_s: float = 300.0
               ) -> dict[str, Any]:
    """Strength-audit YOUR OWN hash file with YOUR wordlist. Reads
    hashes you provide; never sources them."""
    if tool not in ("john", "hashcat"):
        return _fail("hash_audit", "tool must be john or hashcat")
    binary = _binary(tool)
    if binary is None:
        return _fail("hash_audit", f"{tool} not installed")
    hashes = Path(hashfile or "").expanduser()
    words = Path(wordlist or "").expanduser()
    if not hashes.is_file():
        return _fail("hash_audit", "hash file required and must exist")
    if not words.is_file():
        return _fail("hash_audit", "wordlist file required")
    if tool == "john":
        argv = [binary, f"--wordlist={words}", str(hashes)]
    else:
        argv = [binary, "-m", "0", "-a", "0", str(hashes), str(words)]
    return _run("hash_audit", argv, timeout_s)


def sqli_scan(url: str, timeout_s: float = 240.0) -> dict[str, Any]:
    """sqlmap detection-only scan (--batch, level 1, risk 1).
    Dump/exploit/shell modes are not expressible here by design."""
    binary = _binary("sqlmap")
    if binary is None:
        return _fail("sqli_scan", "sqlmap not installed")
    ok, reason = validate_url(url)
    if not ok:
        return _fail("sqli_scan", reason)
    return _run("sqli_scan",
                [binary, "-u", url, "--batch", "--level", "1",
                 "--risk", "1", "--threads", "2",
                 "--disable-coloring"],
                timeout_s)


def capture_read(pcap: str, max_packets: int = 200) -> dict[str, Any]:
    """Read-only analysis of a capture FILE you hand over. Never
    sniffs an interface."""
    binary = _binary("tshark") or _binary("wireshark")
    if binary is None:
        return _fail("capture_read", "tshark/wireshark not installed")
    path = Path(pcap or "").expanduser()
    if not path.is_file():
        return _fail("capture_read", "capture file required")
    count = max(1, min(int(max_packets or 200), 1000))
    return _run("capture_read",
                [binary, "-r", str(path), "-T",
                 "fields", "-e", "frame.number", "-e", "ip.src",
                 "-e", "ip.dst", "-e", "dns.qry.name", "-c",
                 str(count)],
                120.0)


__all__ = ["validate_target", "validate_url", "net_inventory",
           "web_audit", "dir_enum", "hash_audit", "sqli_scan",
           "capture_read"]
