"""Soak harness: long-lived process, varied deterministic cycles (1.0).

One Jarvis instance handles N cycles across interleaved sessions with
a fake model/router (no network, no GPU, no mic). Every cycle records
outcome, verification, events, duration, and storage/RSS deltas; every
Kth cycle re-verifies cross-session isolation. SOAK_CYCLES env extends
the run (default 100; 500/1000 for manual deeper runs).
"""

from __future__ import annotations

import os
import statistics
import time

import pytest

from jarvis.cognition.trace import trace_cycle
from jarvis.core.config import JarvisConfig
from jarvis.core.loop import Jarvis

SEED = 42
DEFAULT_CYCLES = 100

SCENARIOS = (
    "hello there",
    "remember that soak fact ALPHA is green",
    "what is my favorite color?",
    "calculate 6*7",
    "calculate 1/0",
    "What is the capital of France?",
    "What is happening in AI today?",
    "remember that soak fact BETA is blue",
    "what is soak fact ALPHA?",
    "tell me a story about perseverance:Rq!9z endless " * 4,
    "",
    "hi",
)


def _cycles_requested() -> int:
    try:
        return max(1, int(os.environ.get("SOAK_CYCLES", DEFAULT_CYCLES)))
    except ValueError:
        return DEFAULT_CYCLES


class _FakeRouter:
    def complete(self, task: str = "", prompt: str = "",
                 system: str = "", **kw: object) -> dict[str, object]:
        return {"ok": True, "text": "A static soak answer."}


def _rss_kb() -> int:
    try:
        with open("/proc/self/status", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return 0


def _db_bytes(home) -> int:
    total = 0
    for name in ("events.db", "jarvis.db"):
        try:
            total += (home / name).stat().st_size
        except OSError:
            pass
    return total


def run_soak(home, cycles: int, sessions: int = 4,
             seed: int = SEED) -> dict:
    """Execute the soak. Returns the machine-readable summary."""
    import random
    rng = random.Random(seed)
    config = JarvisConfig()
    config.paths.home = home
    jarvis = Jarvis(config=config)
    jarvis.router = _FakeRouter()
    summary: dict = {"cycles": cycles, "failures": 0,
                     "recovered": 0, "sessions": sessions,
                     "events": 0, "durations_ms": [],
                     "verifications": {}, "responses_over_cap": 0,
                     "isolation_violations": 0,
                     "rss_start_kb": _rss_kb(), "rss_end_kb": 0,
                     "max_rss_kb": 0, "db_start": _db_bytes(home),
                     "db_end": 0, "belief_start": 0, "belief_end": 0,
                     "learned": 0}
    try:
        import jarvis.worldintel.research as research_mod
        real_fetch = research_mod.fetch_hn
        research_mod.fetch_hn = lambda top_n=10: (_ for _ in ()
                                                  ).throw(
            OSError("soak offline"))
    except ImportError:
        real_fetch = None
    session_ids = [f"soak-session-{i}" for i in range(sessions)]
    cycle_session: dict[int, str] = {}
    try:
        summary["belief_start"] = len(jarvis.beliefs._beliefs)
        order = list(range(cycles))
        rng.shuffle(order)
        for n in order:
            session = session_ids[n % sessions]
            text = SCENARIOS[n % len(SCENARIOS)]
            started = time.monotonic()
            try:
                result = jarvis.cycle_once(text, source="soak",
                                           session_id=session)
                failed = False
            except Exception:
                failed = True
                summary["failures"] += 1
                continue
            cycle_session[jarvis.cycle] = session
            elapsed_ms = (time.monotonic() - started) * 1000.0
            summary["durations_ms"].append(round(elapsed_ms, 2))
            ver = result.verification
            summary["verifications"][ver] = \
                summary["verifications"].get(ver, 0) + 1
            if result.learned:
                summary["learned"] += 1
            if len(result.response) > 2000:
                summary["responses_over_cap"] += 1
            if n % 10 == 0:
                # True isolation probe: rows belonging to this cycle's
                # session must never appear under another session's
                # trace, and vice versa.
                actual = cycle_session.get(jarvis.cycle, session)
                others = [s for s in session_ids if s != actual]
                if others:
                    foreign = trace_cycle(
                        str(home), f"cycle-{jarvis.cycle}",
                        session_id=others[0])
                    leaked = [e for e in foreign["conversation"]
                              if e.get("session_id") == actual]
                    if leaked:
                        summary["isolation_violations"] += 1
                    own = trace_cycle(
                        str(home), f"cycle-{jarvis.cycle}",
                        session_id=actual)
                    if not any(e.get("session_id") == actual
                               for e in own["conversation"]):
                        summary["isolation_violations"] += 1
            rss = _rss_kb()
            summary["max_rss_kb"] = max(summary["max_rss_kb"], rss)
        summary["rss_end_kb"] = _rss_kb()
        summary["db_end"] = _db_bytes(home)
        summary["belief_end"] = len(jarvis.beliefs._beliefs)
        store_events = jarvis.events.count()
        summary["events"] = store_events
    finally:
        if real_fetch is not None:
            research_mod.fetch_hn = real_fetch
        try:
            jarvis.close()
        except Exception:
            pass
    durations = summary.pop("durations_ms")
    if durations:
        ordered = sorted(durations)
        summary["avg_cycle_ms"] = round(statistics.mean(ordered), 2)
        summary["p95_cycle_ms"] = round(
            ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 2)
        summary["max_cycle_ms"] = round(ordered[-1], 2)
    else:
        summary["avg_cycle_ms"] = summary["p95_cycle_ms"] = \
            summary["max_cycle_ms"] = 0.0
    return summary


def test_soak_100_cycles(tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    summary = run_soak(home, _cycles_requested())
    assert summary["failures"] == 0, summary
    assert summary["isolation_violations"] == 0, summary
    assert summary["responses_over_cap"] == 0, summary
    assert summary["events"] > summary["cycles"], summary
    growth_kb = summary["rss_end_kb"] - summary["rss_start_kb"]
    assert growth_kb < 100 * 1024, summary  # <100MB in-process growth
    assert summary["db_end"] >= summary["db_start"]
    assert summary["p95_cycle_ms"] < 5000.0, summary


def test_soak_trace_complete(tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    run_soak(home, 20, sessions=2)
    trace = trace_cycle(str(home), "cycle-5", session_id="soak-session-1")
    assert len(trace["events"]) >= 2
    assert trace["conversation"] or trace["episodes"]
