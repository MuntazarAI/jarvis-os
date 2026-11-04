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
import re
import shutil
import socket
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# Explicit LAN ranges are allowed (audits of the operator's own network).
# Everything else must be globally routable. Loopback, unspecified,
# link-local, multicast, and reserved ranges are refused by category.
_PRIVATE_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("fc00::/7"),
)
_LOOPBACK_NAMES = frozenset({
    "localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback",
})
_LABEL_RE = re.compile(
    r"^[A-Za-z0-9_](?:[A-Za-z0-9_-]{0,61}[A-Za-z0-9_])?$")
_MAX_HOST_LEN = 253
_MAX_WORDLIST_BYTES = 100 * 1024 * 1024
_MAX_HASHFILE_BYTES = 10 * 1024 * 1024
# hash_audit stdout/stderr can contain recovered plaintext in several
# tool-specific formats. Do not pass it through any agent/log/trace path.
_SENSITIVE_OUTPUT_NOTE = (
    "[withheld: hash_audit output can contain recovered credentials]")


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


def _existing_file(value: str, label: str, *,
                   max_bytes: int | None = None
                   ) -> tuple[Path | None, str]:
    """Resolve an operator-supplied file to an absolute path.

    Absolute paths cannot be mistaken for john/hashcat/gobuster options.
    Size caps bound how much input the external tool can consume.
    """
    if not isinstance(value, str) or not value.strip():
        return None, f"{label} file required and must exist"
    try:
        path = Path(value).expanduser().resolve()
        if not path.is_file():
            return None, f"{label} file required and must exist"
        if max_bytes is not None and path.stat().st_size > max_bytes:
            return None, f"{label} file too large (max {max_bytes} bytes)"
    except (OSError, RuntimeError) as exc:
        return None, f"{label} file error: {type(exc).__name__}"
    return path, ""


def _bounded_int(value: Any, default: int, low: int, high: int) -> int | None:
    try:
        number = int(value if value is not None else default)
    except (TypeError, ValueError):
        return None
    return max(low, min(number, high))


def _clean_host(host: str) -> str:
    text = str(host or "").strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    return text.rstrip(".").lower()


def _parse_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Parse an IP literal, including legacy IPv4 spellings.

    ``socket.inet_aton`` accepts forms such as ``127.1``, ``2130706433``,
    ``0x7f000001`` and ``0177.0.0.1`` that external tools may also accept.
    Treating them as hostnames would bypass the address policy.
    """
    text = _clean_host(host).replace("%25", "%")
    if not text:
        return None
    try:
        return ipaddress.ip_address(text)
    except ValueError:
        pass
    try:
        return ipaddress.IPv4Address(socket.inet_aton(text))
    except (OSError, ValueError):
        return None


def _is_explicit_private(
        addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return any(
        addr.version == net.version and addr in net
        for net in _PRIVATE_NETWORKS)


def _address_verdict(
        addr: ipaddress.IPv4Address | ipaddress.IPv6Address
) -> tuple[bool, str]:
    """Allow public and explicit RFC1918/ULA LAN addresses; refuse the rest."""
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    if addr.is_loopback:
        return False, "loopback destination refused"
    if addr.is_unspecified:
        return False, "unspecified destination refused"
    if addr.is_link_local:
        return False, "link-local destination refused"
    if addr.is_multicast:
        return False, "multicast destination refused"
    if addr.is_reserved:
        return False, "reserved destination refused"
    if addr.is_global or _is_explicit_private(addr):
        return True, "ok"
    return False, "non-routable destination refused"


def _is_loopback_name(host: str) -> bool:
    text = _clean_host(host)
    return text in _LOOPBACK_NAMES or text.endswith(".localhost")


def _valid_hostname(host: str) -> bool:
    text = _clean_host(host)
    if not text or len(text) > _MAX_HOST_LEN:
        return False
    labels = text.split(".")
    return bool(labels) and all(_LABEL_RE.fullmatch(label) for label in labels)


def _resolve_host_addresses(
        host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Resolve a hostname for a best-effort destination check.

    Returns an empty list when resolution fails. Callers must treat that
    as fail-closed. This is not a rebinding-proof control: the HTTP client
    resolves again and may follow redirects.
    """
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError):
        return []
    out = []
    for info in infos:
        try:
            text = info[4][0]
        except (IndexError, TypeError):
            continue
        addr = _parse_ip(str(text))
        if addr is not None:
            out.append(addr)
    return out


def validate_target(target: str, *, resolve_dns: bool = False
                    ) -> tuple[bool, str]:
    """Explicit-scope validation. Refuses empty, overbroad, option-like,
    and non-routable targets. LAN ranges are allowed ONLY as explicit nets
    of 256 addresses or fewer (e.g. /24 IPv4, /120 IPv6) — never wider,
    never the whole internet.

    Hostnames are always syntax-checked. With ``resolve_dns=True`` every
    address the name currently resolves to must also pass the destination
    policy, and resolution failure fails closed. This is best-effort, not
    rebinding-proof: the external tool resolves the name again. Callers
    that need a tight binding should use explicit addresses.

    Hostnames are never reinterpreted as options because a leading ``-``
    and all shell/option punctuation are rejected before argv construction.
    """
    if not isinstance(target, str):
        return False, "target must be a string"
    text = target.strip()
    if not text:
        return False, "target required: name an explicit host or network"
    if len(text) > _MAX_HOST_LEN:
        return False, "target too long"
    if text.startswith("-"):
        return False, "option-like target refused"
    if any(ord(ch) < 0x20 for ch in text):
        return False, "control character in target"
    if any(ch in "\\'\"`$;&|<>(){}[]," for ch in text):
        return False, "invalid character in target"
    lowered = text.lower()
    if lowered in ("0.0.0.0/0", "::/0", "internet", "everyone",
                   "all", "*"):
        return False, "overbroad target refused"
    if "/" in text:
        try:
            net = ipaddress.ip_network(text, strict=False)
        except ValueError:
            return False, "bad network notation"
        if net.num_addresses > 256:
            return False, "network too wide (max 256 addresses)"
        if net.is_multicast or net.is_reserved or net.is_loopback \
                or net.is_link_local:
            return False, "non-routable target refused"
        if net.network_address.is_unspecified:
            return False, "non-routable target refused"
        if not (net.is_global or any(
                net.version == private.version and net.subnet_of(private)
                for private in _PRIVATE_NETWORKS)):
            return False, "non-routable target refused"
        return True, "ok"
    addr = _parse_ip(text)
    if addr is not None:
        return _address_verdict(addr)
    if not _valid_hostname(text):
        return False, "bad hostname"
    if _is_loopback_name(text):
        return False, "loopback hostname refused"
    if resolve_dns:
        addresses = _resolve_host_addresses(text)
        if not addresses:
            return False, "hostname does not resolve (fail closed)"
        for resolved in addresses:
            ok, reason = _address_verdict(resolved)
            if not ok:
                return False, f"{reason}: {resolved}"
    return True, "ok"


def validate_url(url: str, *, resolve_dns: bool = True) -> tuple[bool, str]:
    """Validate one explicit http(s) destination.

    Policy: public addresses and explicit RFC1918/ULA LAN addresses are
    allowed; loopback, unspecified, link-local (including cloud metadata),
    multicast, reserved, and non-routable destinations are refused.

    Hostnames are resolved best-effort and every resolved address must
    pass. This is not a rebinding-proof or redirect-proof control: the
    external tool resolves again and may follow redirects. Use network
    egress controls when that distinction matters.
    """
    if not isinstance(url, str):
        return False, "URL must be a string"
    text = url.strip()
    if not text:
        return False, "URL required"
    if any(ord(ch) < 0x20 for ch in text):
        return False, "control character in URL"
    if "\\" in text:
        return False, "backslash in URL refused"
    try:
        parts = urlparse(text)
        _ = parts.port  # raises ValueError for a malformed port
    except ValueError:
        return False, "bad URL"
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return False, "only http(s) URLs with a host"
    host = parts.hostname
    addr = _parse_ip(host)
    if addr is not None:
        return _address_verdict(addr)
    if _is_loopback_name(host):
        return False, "loopback hostname refused"
    if not _valid_hostname(host):
        return False, "bad hostname"
    if not resolve_dns:
        return True, "ok (hostname not resolved)"
    addresses = _resolve_host_addresses(host)
    if not addresses:
        return False, "hostname does not resolve (fail closed)"
    for resolved in addresses:
        ok, reason = _address_verdict(resolved)
        if not ok:
            return False, f"{reason}: {resolved}"
    return True, "ok"


def net_inventory(target: str, timeout_s: float = 120.0,
                  profile: str = "ping") -> dict[str, Any]:
    """Host discovery and inventory. Profiles (intrusiveness rises):
    ping (who is up, default), fast (top-100 ports), service (version
    detection on open ports). No OS detection, no scripts, no UDP in v1.
    Returns parsed host/port findings plus raw output.

    Hostnames are resolved once and every answer must pass the destination
    policy before nmap starts. nmap resolves the name again, so a DNS
    change between check and use remains possible; prefer explicit
    addresses when that distinction matters.
    """
    binary = _binary("nmap")
    if binary is None:
        return _fail("net_inventory", "nmap not installed")
    ok, reason = validate_target(target, resolve_dns=True)
    if not ok:
        return _fail("net_inventory", reason)
    if profile == "ping":
        argv = [binary, "-sn", "-T4", "--max-retries", "1", target]
    elif profile == "fast":
        argv = [binary, "-F", "-T4", "--max-retries", "1", target]
    elif profile == "service":
        argv = [binary, "-sV", "-T4", "--max-retries", "1",
                "--version-intensity", "0", target]
    else:
        return _fail("net_inventory",
                     "profile must be ping, fast, or service")
    out = _run("net_inventory", argv, timeout_s)
    if out["ok"]:
        out["findings"] = _parse_nmap(out["output"])
    return out


def _parse_nmap(output: str) -> list[dict[str, Any]]:
    """Parse nmap human output into host/port records. Best-effort;
    raw output always retained alongside."""
    import re as _re
    findings = []
    host = ""
    for line in (output or "").splitlines():
        scan = _re.match(r"Nmap scan report for (\S+)", line)
        if scan:
            host = scan.group(1)
            findings.append({"host": host, "ports": []})
            continue
        port = _re.match(
            r"(\d+)/(tcp|udp)\s+(\S+)\s+(\S+)(?:\s+(.*))?", line)
        if port and findings:
            findings[-1]["ports"].append({
                "port": int(port.group(1)), "proto": port.group(2),
                "state": port.group(3), "service": port.group(4),
                "version": (port.group(5) or "").strip()[:120]})
    return findings


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


def dir_enum(url: str, wordlist: str, timeout_s: float = 180.0,
             extensions: str = "", threads: int = 10
             ) -> dict[str, Any]:
    """Gobuster directory enum with YOUR wordlist file. Optional
    comma-separated extensions (php,html) and 1-20 threads."""
    binary = _binary("gobuster")
    if binary is None:
        return _fail("dir_enum", "gobuster not installed")
    ok, reason = validate_url(url)
    if not ok:
        return _fail("dir_enum", reason)
    path, reason = _existing_file(wordlist, "wordlist",
                                  max_bytes=_MAX_WORDLIST_BYTES)
    if path is None:
        return _fail("dir_enum", reason)
    count = _bounded_int(threads, 10, 1, 20)
    if count is None:
        return _fail("dir_enum", "threads must be an integer")
    exts = "".join(
        ch for ch in str(extensions or "")
        if ch.isalnum() or ch in ",-")[:40]
    argv = [binary, "dir", "-u", url, "-w", str(path),
            "-q", "-t", str(count), "-timeout", "10s"]
    if exts:
        argv += ["-x", exts]
    out = _run("dir_enum", argv, timeout_s)
    if out["ok"]:
        out["findings"] = _parse_gobuster(out["output"])
    return out


def _parse_gobuster(output: str) -> list[dict[str, Any]]:
    import re as _re
    findings = []
    for line in (output or "").splitlines():
        match = _re.match(r"(\S+)\s+\(Status:\s*(\d+)\)", line)
        if match:
            findings.append({"path": match.group(1)[:200],
                             "status": int(match.group(2))})
    return findings


def hash_audit(hashfile: str, wordlist: str,
               tool: str = "john", timeout_s: float = 300.0,
               mode: str = "") -> dict[str, Any]:
    """Strength-audit YOUR OWN hash file with YOUR wordlist.

    Intent boundary: this runs a dictionary attack against hashes the
    operator explicitly supplies, with a wordlist the operator explicitly
    supplies. It never extracts hashes from the system, never targets a
    remote service, and never runs an unbounded/mask/brute-force mode.

    Optional mode: john --format name, or hashcat numeric -m mode.
    Unknown/invalid modes are refused rather than silently defaulted.
    """
    if tool not in ("john", "hashcat"):
        return _fail("hash_audit", "tool must be john or hashcat")
    binary = _binary(tool)
    if binary is None:
        return _fail("hash_audit", f"{tool} not installed")
    hashes, reason = _existing_file(hashfile, "hash",
                                    max_bytes=_MAX_HASHFILE_BYTES)
    if hashes is None:
        return _fail("hash_audit", reason)
    words, reason = _existing_file(wordlist, "wordlist",
                                   max_bytes=_MAX_WORDLIST_BYTES)
    if words is None:
        return _fail("hash_audit", reason)
    raw_mode = str(mode or "").strip()
    if tool == "john":
        clean_mode = "".join(
            ch for ch in raw_mode if ch.isalnum() or ch in "-_")[:32]
        if raw_mode and clean_mode != raw_mode:
            return _fail("hash_audit", "invalid john format name")
        argv = [binary, f"--wordlist={words}", str(hashes)]
        if clean_mode:
            argv.append(f"--format={clean_mode}")
    else:
        # hashcat modes are numeric; anything else must not be guessed.
        if not raw_mode.isdigit():
            return _fail("hash_audit",
                         "hashcat mode must be a numeric -m value")
        argv = [binary, "-m", raw_mode, "-a", "0", str(hashes), str(words)]
    out = _run("hash_audit", argv, timeout_s)
    findings = _parse_cracked(out.get("output", "")) \
        if out.get("ok") else []
    out["findings"] = _redact_findings(findings)
    out["cracked_count"] = len(findings)
    out["sensitive"] = True
    out["redacted"] = True
    # Raw stdout/stderr is never safe to return: john and hashcat use
    # different formats, and some include the recovered plaintext. Keep
    # hash prefixes and counts; the authorized operator can inspect the
    # tool's own output directly.
    for key in ("output", "stderr"):
        if key in out:
            out[key] = _SENSITIVE_OUTPUT_NOTE
    out["note"] = ("recovered plaintext is withheld; run the hash tool "
                   "directly if authorized")
    return out


def _redact_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Publish hash prefixes + a strong marker, never cracked plaintext."""
    out = []
    for finding in findings:
        digest = str(finding.get("hash") or "")
        if len(digest) > 16:
            digest = digest[:16] + "…"
        out.append({"hash": digest, "cracked": "[redacted]",
                    "recovered": True})
    return out


def _parse_cracked(output: str) -> list[dict[str, Any]]:
    import re as _re
    findings = []
    for line in (output or "").splitlines():
        match = _re.match(r"(.+?):(.+)", line.strip())
        if match and len(match.group(2).strip()) >= 1 and \
                "session" not in line.lower()[:20]:
            findings.append({"hash": match.group(1)[:80],
                             "cracked": match.group(2)[:80]})
            if len(findings) >= 100:
                break
    return findings


def sqli_scan(url: str, timeout_s: float = 240.0,
              level: int = 1) -> dict[str, Any]:
    """sqlmap detection-only scan (--batch, level 1-2, risk 1).
    Dump/exploit/shell modes are not expressible here by design."""
    binary = _binary("sqlmap")
    if binary is None:
        return _fail("sqli_scan", "sqlmap not installed")
    ok, reason = validate_url(url)
    if not ok:
        return _fail("sqli_scan", reason)
    level_value = _bounded_int(level, 1, 1, 2)
    if level_value is None:
        return _fail("sqli_scan", "level must be an integer")
    out = _run("sqli_scan",
               [binary, "-u", url, "--batch", "--level", str(level_value),
                "--risk", "1", "--threads", "2",
                "--disable-coloring"],
               timeout_s)
    if out["ok"]:
        out["findings"] = _parse_sqli(out["output"])
    return out


def _parse_sqli(output: str) -> list[dict[str, Any]]:
    import re as _re
    findings = []
    for line in (output or "").splitlines():
        lowered = line.lower()
        if "injectable" in lowered or "vulnerable" in lowered:
            findings.append({"finding": line.strip()[:200]})
            if len(findings) >= 50:
                break
    return findings


def capture_read(pcap: str, max_packets: int = 200,
                 display_filter: str = "") -> dict[str, Any]:
    """Read-only analysis of a capture FILE you hand over. Optional
    tshark display filter (length-capped, passed as one argv element).
    Never sniffs an interface."""
    binary = _binary("tshark") or _binary("wireshark")
    if binary is None:
        return _fail("capture_read", "tshark/wireshark not installed")
    path, reason = _existing_file(pcap, "capture")
    if path is None:
        return _fail("capture_read", reason)
    count = _bounded_int(max_packets, 200, 1, 1000)
    if count is None:
        return _fail("capture_read", "max_packets must be an integer")
    argv = [binary, "-r", str(path), "-T",
            "fields", "-e", "frame.number", "-e", "ip.src",
            "-e", "ip.dst", "-e", "dns.qry.name", "-c",
            str(count)]
    filt = str(display_filter or "")[:200]
    if filt:
        argv += ["-Y", filt]
    return _run("capture_read", argv, 120.0)


__all__ = ["validate_target", "validate_url", "net_inventory",
           "web_audit", "dir_enum", "hash_audit", "sqli_scan",
           "capture_read"]
