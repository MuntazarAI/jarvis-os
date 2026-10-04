"""Static self-review (heuristic SAST-lite, no dependencies).

Walks a target directory and flags: probable hardcoded secrets
(high), dangerous call patterns (medium), and prompt-injection
markers via the existing guards (medium). Binary, hidden, oversized,
and over-count files are skipped and counted, never read blindly.

This is a tripwire, not a pentest: a clean result is `unknown`-leaning
(`no heuristic hits`), never a clean bill of health. Dynamic proof
belongs to `security scan` (Strix bridge).
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
    ("eval-exec", re.compile(r"\b(eval|exec)\s*\(")),
    ("shell-true", re.compile(r"shell\s*=\s*True")),
    ("pickle-loads", re.compile(r"pickle\.loads?\s*\(")),
    ("curl-pipe-shell", re.compile(r"curl[^\n|]*\|\s*(ba)?sh")),
    ("os-system", re.compile(r"os\.system\s*\(")),
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
                "detail": "probable hardcoded credential — move to "
                          "vault/env (match redacted)"})
    for name, pattern in _DANGEROUS_PATTERNS:
        match = pattern.search(text)
        if match:
            lineno = text.count("\n", 0, match.start()) + 1
            report["findings"].append({
                "file": path[-200:], "line": lineno,
                "severity": "medium", "kind": f"danger:{name}",
                "detail": "dangerous pattern — needs human review"})
    injection = scan_injection(text)
    if not injection["clean"]:
        report["findings"].append({
            "file": path[-200:], "line": 0, "severity": "medium",
            "kind": "injection-markers",
            "detail": str(injection["verdict"])[:200]})


__all__ = ["review_path", "MAX_FILES", "MAX_FILE_BYTES"]
