"""Static self-review: deterministic vulnerability scanner (no LLM).

Fully offline heuristic SAST. No models, no network, no execution —
it reads text and matches patterns, which bounds both its power and
its honesty: findings are LEADS with file:line evidence, never proof
of exploitability. Severity + OWASP mapping triage the queue; a clean
result means `no heuristic hits`, never `secure`.

Vuln classes: hardcoded secrets, SQL concatenation, reflected XSS
sinks, SSRF-prone fetches, weak crypto, path traversal, dangerous
execution, deserialization, debug exposure, prompt-injection markers
(via existing guards).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .guards import scan_injection

MAX_FILES = 200
MAX_FILE_BYTES = 200_000
MAX_FINDINGS = 100

_SECRET_PATTERNS = (
    ("aws-access-key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("private-key-block", re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("bearer-token", re.compile(
        r"[Bb]earer [A-Za-z0-9\-._~+/]{20,}")),
    ("api-key-assign", re.compile(
        r"(?i)(api[_-]?key|api[_-]?secret)\s*[:=]\s*['\"][^'\"]{8,}")),
    ("password-assign", re.compile(
        r"(?i)password\s*[:=]\s*['\"][^'\"]{4,}")),
)

_DANGEROUS_PATTERNS = (
    # (name, regex, severity, owasp, remediation hint)
    ("eval-exec", re.compile(r"\b(eval|exec)\s*\("),
     "medium", "A03",
     "avoid eval/exec; parse or dispatch explicitly"),
    ("shell-true", re.compile(r"shell\s*=\s*True"),
     "medium", "A03",
     "use list-args and never enable a shell"),
    ("pickle-loads", re.compile(r"pickle\.loads?\s*\("),
     "medium", "A08",
     "unpickle trusted data only; prefer JSON"),
    ("yaml-load", re.compile(r"yaml\.load\s*\("),
     "medium", "A08",
     "use yaml.safe_load"),
    ("curl-pipe-shell", re.compile(r"curl[^\n|]*\|\s*(ba)?sh"),
     "medium", "A08",
     "inspect installers before piping to shell"),
    ("os-system", re.compile(r"os\.system\s*\("),
     "medium", "A03",
     "use subprocess list-args"),
    ("sql-concat", re.compile(
        r"(execute|executemany|query)\s*\(\s*(f['\"]|['\"].*?\+|%\s)"),
     "high", "A03",
     "use parameterized queries, never string building"),
    ("xss-sink", re.compile(
        r"(innerHTML\s*=|document\.write\s*\(|outerHTML\s*=)"),
     "medium", "A03",
     "sink untrusted data via textContent or an escaper"),
    ("ssrf-fetch", re.compile(
        r"(requests\.(get|post)|urllib.*\.urlopen|fetch\s*\(|"
        r"axios\.(get|post))\s*\(\s*[a-zA-Z_\"']"),
     "medium", "A10",
     "validate target against an allowlist; reuse the SSRF guard"),
    ("weak-crypto", re.compile(
        r"\b(md5|sha1|DES|RC4)\s*\(|hashlib\.(md5|sha1)\s*\("),
     "medium", "A02",
     "use SHA-256+ / bcrypt / argon2 as appropriate"),
    ("path-traversal", re.compile(
        r"open\s*\(\s*[^)]*(\+|%|format\s*\(|f['\"])"),
     "medium", "A01",
     "resolve + jail paths under an allowed root"),
    ("debug-enabled", re.compile(
        r"(?i)\bDEBUG\s*=\s*True|app\.run\s*\([^)]*debug\s*=\s*True"),
     "low", "A05",
     "never ship debug mode enabled"),
)

_SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv",
              "dist", "build"}


def _is_text(path: Path) -> bool:
    try:
        with open(path, "rb") as handle:
            chunk = handle.read(4096)
        return b"\x00" not in chunk
    except OSError:
        return False


def review_path(target: str | Path) -> dict[str, Any]:
    """Review one file or directory. Never raises."""
    root = Path(target)
    report: dict[str, Any] = {"target": str(root)[:300],
                              "findings": [], "scanned": 0,
                              "skipped": 0, "status": "unknown",
                              "verdict": "no heuristic hits"}
    try:
        if not root.exists():
            report["status"] = "error"
            report["verdict"] = "target does not exist"
            return report
        files = [root] if root.is_file() else sorted(
            p for p in root.rglob("*") if p.is_file())
        for path in files:
            if len(report["findings"]) >= MAX_FINDINGS:
                report["skipped"] += 1
                continue
            if report["scanned"] >= MAX_FILES:
                report["skipped"] += 1
                continue
            if any(part in _SKIP_DIRS or part.startswith(".")
                   for part in path.parts):
                report["skipped"] += 1  # excluded by policy, counted
                continue
            try:
                size = path.stat().st_size
            except OSError:
                report["skipped"] += 1
                continue
            if size > MAX_FILE_BYTES or not _is_text(path):
                report["skipped"] += 1
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                report["skipped"] += 1
                continue
            report["scanned"] += 1
            _scan_text(str(path), text, report)
        highs = sum(1 for f in report["findings"]
                    if f["severity"] == "high")
        by_severity = {}
        for finding in report["findings"]:
            by_severity[finding["severity"]] = \
                by_severity.get(finding["severity"], 0) + 1
        report["by_severity"] = by_severity
        report["status"] = "fail" if highs else "pass"
        if report["findings"]:
            report["verdict"] = (
                f"{len(report['findings'])} heuristic hit(s), "
                f"{highs} high — triage required, not proof of "
                f"exploitability")
        return report
    except Exception as exc:
        report["status"] = "error"
        report["verdict"] = f"review crashed: {type(exc).__name__}"
        return report


def _scan_text(path: str, text: str, report: dict) -> None:
    for name, pattern in _SECRET_PATTERNS:
        match = pattern.search(text)
        if match:
            lineno = text.count("\n", 0, match.start()) + 1
            report["findings"].append({
                "file": path[-200:], "line": lineno,
                "severity": "high", "kind": f"secret:{name}",
                "owasp": "A07",
                "evidence": f"line {lineno}: <credential redacted>",
                "detail": "probable hardcoded credential — move to "
                          "vault/env (match redacted)"})
    for name, pattern, severity, owasp, hint in _DANGEROUS_PATTERNS:
        match = pattern.search(text)
        if match:
            lineno = text.count("\n", 0, match.start()) + 1
            line = text.splitlines()[lineno - 1].strip()[:120]
            report["findings"].append({
                "file": path[-200:], "line": lineno,
                "severity": severity, "kind": f"pattern:{name}",
                "owasp": owasp, "evidence": line, "detail": hint})
    injection = scan_injection(text)
    if not injection["clean"]:
        report["findings"].append({
            "file": path[-200:], "line": 0, "severity": "medium",
            "kind": "injection-markers", "owasp": "A03",
            "evidence": "marker set present (content not echoed)",
            "detail": str(injection["verdict"])[:200]})


__all__ = ["review_path", "MAX_FILES", "MAX_FILE_BYTES"]
