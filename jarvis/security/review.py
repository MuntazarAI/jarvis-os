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
    ("cors-wildcard", re.compile(
        r"(?i)(allow_origins\s*=\s*\[\s*['\"]\*|"
        r"access-control-allow-origin['\"]?\s*[:=]\s*['\"]\*)"),
     "medium", "A05",
     "restrict CORS origins to an explicit allowlist"),
    ("bind-all", re.compile(
        r"(?i)\b(host|bind)\s*[:=]\s*['\"]0\.0\.0\.0"),
     "low", "A05",
     "bind loopback by default; expose only behind an allowlist"),
    ("tls-verify-off", re.compile(
        r"(?i)\bverify\s*=\s*False\b"),
     "high", "A02",
     "never disable TLS certificate verification"),
    ("insecure-cookie", re.compile(
        r"(?i)set_cookie\s*\([^)]*secure\s*=\s*False"),
     "medium", "A05",
     "set Secure and HttpOnly on session cookies"),
)

# Dependency manifests are checked line-by-line with hygiene rules. This
# is deliberately not a CVE database: it reports supply-chain posture
# (unpinned, wildcard, cleartext index, cleartext VCS) with file:line
# evidence, never an exploitability claim.
_MANIFEST_NAMES = {"requirements.txt", "requirements-dev.txt",
                   "requirements-test.txt", "pipfile", "package.json",
                   "pyproject.toml"}
_INDEX_HTTP_RE = re.compile(
    r"(?i)^--?(?:extra-)?index-url\s+http://|^--trusted-host\b")
_VCS_HTTP_RE = re.compile(r"(?i)git\+http://")
_PINNED_RE = re.compile(r"(==|===|>=|<=|~=|!=|@\s*https?://)")
_WILDCARD_RE = re.compile(r"(?i)(^|[=@\s])\*$|\blatest\b")

_SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv",
              "dist", "build"}
# State files that can contain live credentials or approval material
# are never scanned: a self-review must not read the vault it protects.
SENSITIVE_STATE_NAMES = {
    "secrets.json", ".vault.key", "policy-approvals.json",
    "device-approvals.json", "credentials.json", "id_rsa"}
_SKIP_NAMES = SENSITIVE_STATE_NAMES


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
                              "skipped": 0, "truncated": False,
                              "status": "unknown",
                              "verdict": "no heuristic hits"}
    try:
        if not root.exists():
            report["status"] = "error"
            report["verdict"] = "target does not exist"
            return report
        is_dir = root.is_dir()
        files = [root] if root.is_file() else sorted(
            p for p in root.rglob("*") if p.is_file())
        for path in files:
            if len(report["findings"]) >= MAX_FINDINGS:
                report["truncated"] = True
                report["skipped"] += 1
                continue
            if report["scanned"] >= MAX_FILES:
                report["truncated"] = True
                report["skipped"] += 1
                continue
            if path.is_symlink():
                report["skipped"] += 1  # never follow out-of-tree links
                continue
            try:
                relative = (path.relative_to(root) if is_dir
                            else Path(path.name))
            except ValueError:
                report["skipped"] += 1
                continue
            parts = relative.parts or (path.name,)
            if any(part in _SKIP_DIRS or part.startswith(".")
                   for part in parts):
                report["skipped"] += 1  # excluded by policy, counted
                continue
            if path.name in _SKIP_NAMES:
                report["skipped"] += 1  # never read live secret state
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
            _scan_text(relative.as_posix(), text, report)
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
                "file": path, "line": lineno,
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
                "file": path, "line": lineno,
                "severity": severity, "kind": f"pattern:{name}",
                "owasp": owasp, "evidence": line, "detail": hint})
    injection = scan_injection(text)
    if not injection["clean"]:
        report["findings"].append({
            "file": path, "line": 0, "severity": "medium",
            "kind": "injection-markers", "owasp": "A03",
            "evidence": "marker set present (content not echoed)",
            "detail": str(injection["verdict"])[:200]})
    name = Path(path).name.lower()
    if name in _MANIFEST_NAMES:
        _scan_manifest(path, name, text, report)


def _manifest_hit(path: str, lineno: int, severity: str, kind: str,
                  owasp: str, detail: str) -> dict[str, Any]:
    return {"file": path, "line": lineno, "severity": severity,
            "kind": f"dependency:{kind}", "owasp": owasp,
            "evidence": f"line {lineno}: manifest directive",
            "detail": detail}


def _scan_manifest(path: str, name: str, text: str,
                   report: dict) -> None:
    """Hygiene checks for dependency manifests. Deterministic, no CVE DB."""
    for lineno, raw in enumerate(text.splitlines()[:5000], start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if name.endswith(".json"):
            lowered = line.lower()
            if '"latest"' in lowered or '": "*"' in lowered:
                report["findings"].append(_manifest_hit(
                    path, lineno, "medium", "wildcard", "A06",
                    "wildcard dependency version — pin an exact release"))
            if "http://" in line and "resolved" not in line:
                report["findings"].append(_manifest_hit(
                    path, lineno, "high", "insecure-index", "A08",
                    "cleartext registry/source URL in manifest"))
            continue
        if name == "pyproject.toml":
            if _VCS_HTTP_RE.search(line):
                report["findings"].append(_manifest_hit(
                    path, lineno, "high", "vcs-http", "A08",
                    "dependency fetched over cleartext git+http"))
            if _WILDCARD_RE.search(line):
                report["findings"].append(_manifest_hit(
                    path, lineno, "medium", "wildcard", "A06",
                    "wildcard dependency version — pin an exact release"))
            continue
        if _INDEX_HTTP_RE.search(line):
            report["findings"].append(_manifest_hit(
                path, lineno, "high", "insecure-index", "A08",
                "cleartext package index or trusted-host override"))
            continue
        if line.startswith(("-r ", "--requirement", "-c ", "--constraint")):
            continue
        if _VCS_HTTP_RE.search(line):
            report["findings"].append(_manifest_hit(
                path, lineno, "high", "vcs-http", "A08",
                "dependency fetched over cleartext git+http"))
            continue
        if _WILDCARD_RE.search(line.split("#", 1)[0]):
            report["findings"].append(_manifest_hit(
                path, lineno, "medium", "wildcard", "A06",
                "wildcard dependency version — pin an exact release"))
            continue
        target = line.split("#", 1)[0].strip()
        if target.startswith("-e "):
            target = target[3:].strip()
        if target and not _PINNED_RE.search(target):
            report["findings"].append(_manifest_hit(
                path, lineno, "low", "unpinned", "A06",
                "dependency is not pinned to a reviewed version"))


def scan_file(target: str | Path) -> dict[str, Any]:
    """Scan exactly one file. Returns findings or an explicit unknown."""
    path = Path(target)
    if path.name in _SKIP_NAMES:
        return {"status": "skipped", "findings": [],
                "detail": "sensitive state file is never scanned"}
    if not path.exists():
        return {"status": "missing", "findings": [],
                "detail": "file does not exist"}
    if not path.is_file():
        return {"status": "error", "findings": [],
                "detail": "not a regular file"}
    try:
        if path.stat().st_size > MAX_FILE_BYTES or not _is_text(path):
            return {"status": "skipped", "findings": [],
                    "detail": "file is binary or over the size bound"}
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"status": "error", "findings": [],
                "detail": f"{type(exc).__name__}"}
    report: dict[str, Any] = {"findings": []}
    _scan_text(str(path), text, report)
    return {"status": "ok", "findings": report["findings"]}


def recheck_finding(file_path: str | Path, kind: str,
                    line: int = 0) -> dict[str, Any]:
    """Deterministically re-check one recorded hit in one file.

    Returns ``still_present`` with the current line, ``resolved`` when
    the rule no longer matches, or ``unknown`` when the file cannot be
    read. Absence at a *different* line is still presence: a rule that
    moved is not a rule that was fixed.
    """
    result = scan_file(file_path)
    if result["status"] == "missing":
        return {"state": "unknown", "line": 0,
                "detail": ("file no longer exists; deletion/move cannot "
                           "be verified as a fix")}
    if result["status"] != "ok":
        return {"state": "unknown", "line": 0,
                "detail": str(result.get("detail", "unreadable"))[:120]}
    hits = [f for f in result["findings"] if f["kind"] == kind]
    if not hits:
        return {"state": "resolved", "line": 0,
                "detail": "rule no longer matches in this file"}
    exact = next((f for f in hits if line and f["line"] == line), None)
    hit = exact or hits[0]
    return {"state": "still_present", "line": int(hit.get("line", 0)),
            "detail": "rule still matches"}


__all__ = ["review_path", "scan_file", "recheck_finding",
           "MAX_FILES", "MAX_FILE_BYTES", "MAX_FINDINGS"]
