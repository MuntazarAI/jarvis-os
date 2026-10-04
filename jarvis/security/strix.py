"""Strix dynamic-scan bridge (optional dependency, policy-gated).

Delegates proof-of-exploit work to the Strix CLI when installed, and
maps its result into our evidence shapes. This module owns no
scanning logic of its own — it is a bounded subprocess runner plus a
translator, wrapped in authorization gates:

- no binary → honest `unavailable` (never a silent skip)
- no `--yes` (authorization) → refused, always
- non-local target without `--allow-nonlocal` → refused, always
- emergency stop → refused, always
- bounded timeout, capped output, list-args only (no shell)

A Strix verdict is recorded as `partial`, never `verified`: a tool
claim is evidence, not proof. Absence of findings is recorded as
`no findings reported`, never `secure`.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

DEFAULT_TIMEOUT_S = 600.0
MAX_OUTPUT_CHARS = 20_000
SCAN_MODES = ("quick", "standard", "deep")


def strix_binary() -> str:
    """Path to the Strix CLI, or empty when not installed."""
    return shutil.which("strix") or ""


def classify_target(target: str) -> dict[str, Any]:
    """Sort a scan target into path / loopback-url / public-url."""
    text = (target or "").strip()
    if not text or len(text) > 2000:
        return {"kind": "unsupported", "reason": "empty/oversize target"}
    candidate = Path(text)
    if candidate.exists():
        return {"kind": "path",
                "path": str(candidate.resolve())[:500]}
    lowered = text.lower()
    if lowered.startswith(("http://", "https://")):
        from urllib.parse import urlparse
        import ipaddress
        host = (urlparse(text).hostname or "")
        if host in ("localhost", "localhost.localdomain"):
            return {"kind": "loopback-url", "url": text[:500]}
        try:
            addr = ipaddress.ip_address(host)
            if addr.is_loopback:
                return {"kind": "loopback-url", "url": text[:500]}
            if not addr.is_global:
                return {"kind": "private-url", "url": text[:500]}
            return {"kind": "public-url", "url": text[:500]}
        except ValueError:
            pass  # hostname: fall through to the SSRF guard (may DNS)
        from .guards import is_safe_url
        safe, reason = is_safe_url(text)
        if safe:
            return {"kind": "public-url", "url": text[:500]}
        return {"kind": "unsupported", "reason": reason}
    if lowered.startswith(("localhost", "127.", "0.0.0.0",
                            "[::1]")):
        return {"kind": "loopback-url", "url": text[:500]}
    return {"kind": "unsupported",
            "reason": "not a local path or http(s) URL"}


def run_scan(target: str, *, mode: str = "quick",
             timeout_s: float = DEFAULT_TIMEOUT_S,
             allow_nonlocal: bool = False,
             authorized: bool = False,
             max_turns: int = 100,
             policy: Any = None) -> dict[str, Any]:
    """Run one bounded non-interactive scan. Never raises."""
    started = time.time()
    result: dict[str, Any] = {"tool": "strix", "target": target[:300],
                              "mode": mode, "status": "unknown",
                              "verification": "unknown", "findings": [],
                              "summary": "", "duration_s": 0.0}
    try:
        if not authorized:
            return _refuse(result, started, "authorization required: "
                           "re-run with --yes to confirm you own this "
                           "target or have explicit written permission")
        if policy is not None:
            check = getattr(policy, "_emergency_stop", None)
            if callable(check):
                try:
                    if check():
                        return _refuse(result, started,
                                       "emergency stop engaged")
                except Exception:
                    pass
        binary = strix_binary()
        if mode not in SCAN_MODES:
            return _refuse(result, started,
                           f"unknown mode (quick|standard|deep)")
        info = classify_target(target)
        kind = info["kind"]
        if kind == "unsupported":
            return _refuse(result, started,
                           f"unsupported target: {info['reason']}")
        if kind == "public-url" and not allow_nonlocal:
            return _refuse(result, started, "non-local target needs "
                           "--allow-nonlocal plus --yes")
        if kind == "private-url" and not allow_nonlocal:
            return _refuse(result, started, "off-machine (LAN) target "
                           "needs --allow-nonlocal plus --yes")
        from .guards import scan_injection
        if not scan_injection(target)["clean"]:
            return _refuse(result, started,
                           "target contains injection markers")
        # Policy gates above run before environment checks: a refusal
        # must never depend on whether the tool happens to be installed.
        if not binary:
            result.update(status="unavailable", summary=(
                "strix CLI not installed: "
                "see https://github.com/usestrix/strix for install "
                "instructions (inspect before piping to shell), "
                "then set an LLM key"))
            result["duration_s"] = round(time.time() - started, 2)
            return result
        timeout = max(30.0, min(3600.0, float(timeout_s or 0.0)
                                or DEFAULT_TIMEOUT_S))
        turns = max(1, min(500, int(max_turns or 0) or 100))
        try:
            proc = subprocess.run(
                [binary, "-n", "-t", target, "--scan-mode", mode,
                 "--max-turns", str(turns)],
                capture_output=True, text=True, timeout=timeout,
                shell=False)
        except subprocess.TimeoutExpired:
            result.update(status="timeout", summary=(
                f"scan exceeded {timeout:.0f}s — killed, no verdict"))
            result["duration_s"] = round(time.time() - started, 2)
            return result
        except OSError as exc:
            result.update(status="error", summary=(
                f"scan launch failed: {type(exc).__name__}"))
            result["duration_s"] = round(time.time() - started, 2)
            return result
        output = (proc.stdout or "") + (proc.stderr or "")
        result["log_tail"] = output[-MAX_OUTPUT_CHARS:]
        result["returncode"] = proc.returncode
        counts = _severity_counts(output)
        result["findings"] = counts
        total = sum(counts.values())
        # Tool claims are evidence (partial), never proof (verified).
        # Silence is absence-of-findings, never a clean bill of health.
        if proc.returncode != 0 or total > 0:
            result.update(
                status="findings" if total else "tool-failed",
                verification="partial",
                summary=f"strix exit={proc.returncode}: {total} "
                        f"finding(s) {counts} — triage required")
        else:
            result.update(status="no-findings", verification="partial",
                          summary="strix reported no findings — "
                          "absence of tool findings, not proof of safety")
        result["duration_s"] = round(time.time() - started, 2)
        return result
    except Exception as exc:
        return _refuse(result, started,
                       f"bridge crashed: {type(exc).__name__}")


def to_evidence(result: dict[str, Any],
                subject: str = "") -> dict[str, Any]:
    """Map a scan result into a verification-shaped evidence entry."""
    return {"subject": (subject or result.get("target", ""))[:200],
            "verdict": ("reported" if result.get("status")
                        in ("findings", "no-findings", "tool-failed")
                        else "unavailable"),
            "tool": "strix", "mode": result.get("mode", ""),
            "verification": result.get("verification", "unknown"),
            "summary": str(result.get("summary", ""))[:500],
            "duration_s": result.get("duration_s", 0.0)}


def _refuse(result: dict, started: float,
            reason: str) -> dict[str, Any]:
    result.update(status="refused", verification="unknown",
                  summary=reason[:300],
                  duration_s=round(time.time() - started, 2))
    return result


def _severity_counts(output: str) -> dict[str, int]:
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for match in re.finditer(
            r"\b(critical|high|medium|low)\b", output, re.IGNORECASE):
        counts[match.group(1).lower()] += 1
    # Cap: counts describe tool chatter volume, not distinct vulns.
    return {key: min(value, 999)
            for key, value in counts.items()}


__all__ = ["run_scan", "classify_target", "strix_binary",
           "to_evidence", "SCAN_MODES"]
