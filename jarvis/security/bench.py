"""Safe local security benchmark (no real targets, no network).

Runs the deterministic scanner and the durable security manager over a
small corpus of intentionally vulnerable toy fixtures with a ground-truth
manifest. Measures precision/recall, false positives, validation rate,
remediation verification rate, latency, CPU/RAM, and determinism.

Only files under the corpus directory are copied to a temporary work
tree; the fixtures themselves are never modified. Remediation uses the
real policy/approval path with a local benchmark actor, not a bypass.
"""

from __future__ import annotations

import json
import re
import resource
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from .intel import MANAGER_ACTOR, SecurityManager
from .review import review_path

MAX_CASES = 32
MAX_CASE_FILES = 500
MAX_CASE_BYTES = 5_000_000
MAX_EXPECTED = 100
DEFAULT_CORPUS = (Path(__file__).resolve().parents[2] /
                  "tests" / "fixtures" / "security_bench")


class BenchError(ValueError):
    """Malformed corpus or unsafe benchmark input."""


def _load_manifest(corpus: Path) -> list[dict[str, Any]]:
    manifest = corpus / "manifest.json"
    try:
        raw = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BenchError(f"cannot read manifest: {type(exc).__name__}")
    if not isinstance(raw, dict) or int(raw.get("version", 0) or 0) != 1:
        raise BenchError("unsupported benchmark manifest")
    cases = raw.get("cases")
    if not isinstance(cases, list) or not cases:
        raise BenchError("manifest has no cases")
    if len(cases) > MAX_CASES:
        raise BenchError(f"manifest exceeds {MAX_CASES} cases")
    out: list[dict[str, Any]] = []
    root = corpus.resolve()
    for item in cases:
        if not isinstance(item, dict):
            raise BenchError("case must be an object")
        name = re.sub(r"[^A-Za-z0-9._-]+", "_",
                      str(item.get("name", "")))[:60]
        rel = str(item.get("path", ""))
        if not name or not rel:
            raise BenchError("case needs name and path")
        target = (corpus / rel).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            raise BenchError(f"case escapes corpus: {name}")
        if not target.is_dir():
            raise BenchError(f"case directory missing: {name}")
        expected = []
        raw_findings = list(item.get("findings") or [])
        if len(raw_findings) > MAX_EXPECTED:
            raise BenchError(f"case exceeds {MAX_EXPECTED} findings: {name}")
        for finding in raw_findings:
            if not isinstance(finding, dict):
                continue
            kind = str(finding.get("kind", ""))[:80]
            file = str(finding.get("file", ""))[:200]
            if not kind or not file:
                continue
            expected.append({"kind": kind, "file": file,
                             "line": int(finding.get("line", 0) or 0),
                             "severity": str(
                                 finding.get("severity", ""))[:20]})
        remediations = []
        raw_fixes = list(item.get("remediations") or [])
        if len(raw_fixes) > 20:
            raise BenchError(f"too many remediations in {name}")
        for fix in raw_fixes:
            if not isinstance(fix, dict):
                continue
            kind = str(fix.get("kind", ""))[:80]
            file = str(fix.get("file", ""))[:200]
            replacement = str(fix.get("replacement", ""))
            if kind and file and replacement:
                remediations.append({"kind": kind, "file": file,
                                     "replacement": replacement[:400]})
        out.append({"name": name, "path": target, "findings": expected,
                    "remediations": remediations})
    return out


def _copy_case(source: Path, dest: Path) -> None:
    files = 0
    total = 0
    for path in source.rglob("*"):
        if path.is_symlink():
            raise BenchError("case contains a symlink; refusing to copy")
        if not path.is_file():
            continue
        files += 1
        total += path.stat().st_size
        if files > MAX_CASE_FILES or total > MAX_CASE_BYTES:
            raise BenchError("case exceeds benchmark size bounds")
    shutil.copytree(source, dest, symlinks=True)


def _flat(findings: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Deduplicate (kind, file) pairs; severity is measured separately."""
    keys: list[tuple[str, str]] = []
    for finding in findings:
        key = (str(finding.get("kind", "")),
               Path(str(finding.get("asset", ""))).as_posix())
        if key not in keys:
            keys.append(key)
    return keys


def _same_scan(first: dict[str, Any], second: dict[str, Any]) -> bool:
    def shape(report: dict[str, Any]) -> str:
        rows = [(f.get("kind"),
                 Path(str(f.get("file", ""))).as_posix(),
                 f.get("line")) for f in report.get("findings", [])]
        return json.dumps(sorted(rows, key=str), sort_keys=True)
    return shape(first) == shape(second)


def _usage() -> tuple[float, float]:
    try:
        usage = resource.getrusage(resource.RUSAGE_SELF)
        return (float(usage.ru_utime + usage.ru_stime),
                float(usage.ru_maxrss))
    except Exception:
        return 0.0, 0.0


def run_benchmark(corpus: str | Path = DEFAULT_CORPUS, *,
                  home: str = "") -> dict[str, Any]:
    """Run the corpus. Returns metrics; never raises on a bad fixture."""
    corpus_path = Path(corpus).expanduser()
    if not corpus_path.is_dir():
        raise BenchError(f"corpus not found: {str(corpus_path)[:200]}")
    cases = _load_manifest(corpus_path)

    from ..core.config import JarvisConfig
    from ..policy.policy import PolicyEngine

    work = Path(tempfile.mkdtemp(prefix="jarvis-secbench-",
                                 dir=home or None))
    state = work / "state"
    state.mkdir(parents=True, exist_ok=True)
    config = JarvisConfig()
    config.paths.home = str(state)
    policy = PolicyEngine(config)
    # The benchmark operator explicitly grants the write capability the
    # remediation actor needs; every change still requires a fresh
    # policy decision plus a single-use approval.
    policy.grant(MANAGER_ACTOR, "fs.write")

    manager = SecurityManager(state, policy=policy)
    cpu_start, _ = _usage()
    wall_start = time.perf_counter()
    totals = {"tp": 0, "fp": 0, "fn": 0, "predicted": 0,
              "validated": 0, "attempted": 0, "reverified": 0,
              "line_expected": 0, "line_matches": 0}
    deterministic = True
    rows: list[dict[str, Any]] = []
    try:
        for index, case in enumerate(cases):
            dest = work / f"case-{index}-{case['name']}"
            _copy_case(case["path"], dest)
            first = review_path(dest)
            second = review_path(dest)
            case_deterministic = _same_scan(first, second)
            deterministic = deterministic and case_deterministic
            result = manager.intel(dest, source="benchmark")
            predictions = result.get("findings", [])
            expected = case["findings"]
            expected_keys = {(row["kind"], Path(row["file"]).as_posix())
                             for row in expected}
            predicted_keys = set(_flat(predictions))
            tp = len(expected_keys & predicted_keys)
            fp = len(predicted_keys - expected_keys)
            fn = len(expected_keys - predicted_keys)
            for row in expected:
                if not row.get("line"):
                    continue
                totals["line_expected"] += 1
                if any(p.get("kind") == row["kind"]
                       and Path(str(p.get("asset", ""))).as_posix() ==
                       Path(row["file"]).as_posix()
                       and int(p.get("line", 0) or 0) == row["line"]
                       for p in predictions):
                    totals["line_matches"] += 1
            stored = [f for f in manager.findings.list()
                      if f.task_id == result.get("task_id")]
            validated = sum(
                1 for f in stored
                if f.state.value in ("validated", "remediated", "reverified"))
            attempted = 0
            reverified = 0
            for fix in case["remediations"]:
                target = next(
                    (f for f in stored
                     if f.kind == fix["kind"]
                     and Path(f.asset).as_posix() ==
                     Path(fix["file"]).as_posix()), None)
                if target is None:
                    attempted += 1
                    continue
                attempted += 1
                outcome = manager.auto_remediate(
                    target.finding_id, replacement=fix["replacement"])
                if outcome.get("status") == "reverified":
                    reverified += 1
            totals["tp"] += tp
            totals["fp"] += fp
            totals["fn"] += fn
            totals["predicted"] += len(predicted_keys)
            totals["validated"] += validated
            totals["attempted"] += attempted
            totals["reverified"] += reverified
            rows.append({
                "name": case["name"],
                "expected": len(expected_keys),
                "predicted": len(predicted_keys),
                "true_positive": tp,
                "false_positive": fp,
                "false_negative": fn,
                "validated": validated,
                "remediations_attempted": attempted,
                "remediated_verified": reverified,
                "deterministic": case_deterministic,
                "task_state": result.get("state", "unknown"),
            })
    finally:
        wall_ms = (time.perf_counter() - wall_start) * 1000.0
        cpu_end, rss = _usage()
        shutil.rmtree(work, ignore_errors=True)
    precision = (totals["tp"] / (totals["tp"] + totals["fp"])
                 if totals["tp"] + totals["fp"] else 1.0)
    recall = (totals["tp"] / (totals["tp"] + totals["fn"])
              if totals["tp"] + totals["fn"] else 1.0)
    validation_rate = (totals["validated"] / totals["predicted"]
                       if totals["predicted"] else 1.0)
    remediation_rate = (totals["reverified"] / totals["attempted"]
                        if totals["attempted"] else 1.0)
    line_rate = (totals["line_matches"] / totals["line_expected"]
                 if totals["line_expected"] else 1.0)
    metrics = {
        "cases": len(cases),
        "expected": totals["tp"] + totals["fn"],
        "predicted": totals["predicted"],
        "true_positive": totals["tp"],
        "false_positive": totals["fp"],
        "false_negative": totals["fn"],
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round((2 * precision * recall / (precision + recall))
                    if precision + recall else 0.0, 4),
        "validated": totals["validated"],
        "validation_rate": round(validation_rate, 4),
        "remediated_verified": totals["reverified"],
        "remediation_attempted": totals["attempted"],
        "remediation_rate": round(remediation_rate, 4),
        "line_accuracy": round(line_rate, 4),
        "line_expected": totals["line_expected"],
        "latency_ms": round(wall_ms, 2),
        "cpu_ms": round((cpu_end - cpu_start) * 1000.0, 2),
        "ram_peak_mb": round(rss / 1024.0, 2),
        "deterministic": deterministic,
    }
    passed = (metrics["cases"] >= 1 and metrics["expected"] > 0
              and metrics["predicted"] > 0
              and metrics["remediation_attempted"] > 0
              and metrics["precision"] >= 0.9
              and metrics["recall"] >= 0.9
              and metrics["validation_rate"] >= 0.8
              and metrics["line_accuracy"] >= 0.8
              and deterministic and remediation_rate >= 0.8)
    return {"schema": 1, "corpus": str(corpus_path)[:300],
            "metrics": metrics, "cases": rows, "passed": passed}


__all__ = ["BenchError", "run_benchmark", "DEFAULT_CORPUS"]
