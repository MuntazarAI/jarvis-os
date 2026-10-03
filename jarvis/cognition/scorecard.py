"""Machine-readable intelligence scorecard + benchmark suite (5.0).

Every score is computed from deterministic in-process probes — never
hand-assigned. Each category runs its probe battery and reports
score (pass rate), evidence, limitations, and next improvement.
`run_benchmarks()` measures latencies for the same paths.
"""

from __future__ import annotations

import time
from typing import Any, Callable

SCORECARD_VERSION = 1


def _timed(fn: Callable[[], Any]) -> tuple[Any, float]:
    started = time.perf_counter()
    try:
        result = fn()
    except Exception as exc:
        return {"error": f"{type(exc).__name__}"[:120]}, -1.0
    return result, (time.perf_counter() - started) * 1000.0


def _pass_rate(results: list[bool]) -> float:
    if not results:
        return 0.0
    return round(sum(1 for result in results if result) / len(results), 3)


def run_scorecard(probes: dict[str, list[Callable[[], bool]]] | None = None
                  ) -> dict[str, Any]:
    """Score each category by its probe pass rate. Empty battery = 0."""
    probes = probes or {}
    categories: dict[str, Any] = {}
    for name in sorted(probes):
        outcomes: list[bool] = []
        evidence: list[str] = []
        for probe in probes[name]:
            try:
                outcomes.append(bool(probe()))
                evidence.append("pass" if outcomes[-1] else "fail")
            except Exception as exc:
                outcomes.append(False)
                evidence.append(f"error: {type(exc).__name__}"[:80])
        categories[name] = {
            "score": _pass_rate(outcomes),
            "probes": len(outcomes),
            "evidence": evidence[:10],
            "limitation": "probe battery covers contracts, not open world"
            if outcomes else "no probes registered",
        }
    overall = round(sum(category["score"] for category in
                        categories.values()) / max(1, len(categories)), 3)
    return {"version": SCORECARD_VERSION, "overall": overall,
            "categories": categories}


def run_benchmarks(scenarios: dict[str, Callable[[], Any]] | None = None
                   ) -> dict[str, Any]:
    """Time named scenarios. Failures recorded, never raised."""
    scenarios = scenarios or {}
    results: dict[str, Any] = {}
    for name in sorted(scenarios):
        _, duration_ms = _timed(scenarios[name])
        results[name] = {"duration_ms": round(duration_ms, 2),
                         "ok": duration_ms >= 0.0}
    return {"scenarios": results}


__all__ = ["run_scorecard", "run_benchmarks", "SCORECARD_VERSION"]
