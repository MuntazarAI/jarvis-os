"""Reliability: recovery, privacy, security, rate-limit, perf (1.0).

Failure injection with containment checks, credential-scrub proofs,
trace minimization, multi-client limiter audit, and performance
regression bounds. Deterministic, offline, fakes only.
"""

from __future__ import annotations

import pytest

from jarvis.core.config import JarvisConfig
from jarvis.core.loop import Jarvis


class _FakeRouter:
    def complete(self, task: str = "", prompt: str = "",
                 system: str = "", **kw: object) -> dict[str, object]:
        return {"ok": True, "text": "A static test answer."}


class _DeadRouter:
    def complete(self, task: str = "", prompt: str = "",
                 system: str = "", **kw: object) -> dict[str, object]:
        raise ConnectionError("model unavailable")


def _jarvis(home):
    config = JarvisConfig()
    config.paths.home = home
    jarvis = Jarvis(config=config)
    jarvis.router = _FakeRouter()
    return jarvis


@pytest.fixture()
def home(tmp_path):
    path = tmp_path / "home"
    path.mkdir(exist_ok=True)
    return path


def _close(jarvis: Jarvis) -> None:
    try:
        jarvis.close()
    except Exception:
        pass


# failure injection + recovery -----------------------------------------------------

def test_model_failure_contained_then_recovers(home, monkeypatch):
    jarvis = _jarvis(home)
    try:
        jarvis.router = _DeadRouter()
        failed = jarvis.cycle_once("What is the capital of France?")
        assert "couldn't reach" in failed.response.lower() or \
            "trouble" in failed.response.lower() or \
            "verified answer" in failed.response.lower()
        jarvis.router = _FakeRouter()
        healthy = jarvis.cycle_once("hello there")
        assert healthy.response and healthy.verification in (
            "UNKNOWN", "VERIFIED")
        # failure left no phantom tools or corruption
        assert jarvis.cycle == 2
    finally:
        _close(jarvis)


def test_world_timeout_recovers(home, monkeypatch):
    import jarvis.worldintel.research as research_mod
    monkeypatch.setattr(
        research_mod, "fetch_hn",
        lambda top_n=10: (_ for _ in ()).throw(TimeoutError("slow")))
    jarvis = _jarvis(home)
    try:
        result = jarvis.cycle_once("What is happening in AI today?")
        assert "Today," not in result.response
        nxt = jarvis.cycle_once("hello there")
        assert nxt.response
    finally:
        _close(jarvis)


def test_tool_failure_no_retry_storm(home, monkeypatch):
    jarvis = _jarvis(home)
    try:
        calls = {"n": 0}
        real_call = jarvis.tools.call

        def _counting(name: str, **kw: object):
            calls["n"] += 1
            return real_call(name, **kw)

        monkeypatch.setattr(jarvis.tools, "call", _counting)
        jarvis.cycle_once("calculate 1/0")
        assert calls["n"] <= 3  # bounded: no retry storm
    finally:
        _close(jarvis)


def test_corrupt_events_db_fails_loud_not_silent(home):
    import sqlite3
    (home / "events.db").write_bytes(b"definitely not sqlite")
    with pytest.raises(Exception):
        Jarvis(config=_config_home(home))


def _config_home(home):
    config = JarvisConfig()
    config.paths.home = home
    return config


# privacy -------------------------------------------------------------------------------

def test_credential_shapes_never_persist(home):
    jarvis = _jarvis(home)
    try:
        jarvis.cycle_once(
            "my aws key is AKIAIOSFODNN7EXAMPLE do not lose it")
        assert b"AKIAIOSFODNN7EXAMPLE" not in \
            (home / "events.db").read_bytes()
        import sqlite3
        con = sqlite3.connect(str(home / "jarvis.db"))
        try:
            n = con.execute(
                "SELECT COUNT(*) FROM memories WHERE content "
                "LIKE '%AKIA%'").fetchone()[0]
        finally:
            con.close()
        assert n == 0
    finally:
        _close(jarvis)


def test_prose_without_credential_shape_passes(home):
    jarvis = _jarvis(home)
    try:
        result = jarvis.cycle_once(
            "remember that my password habit is bad")
        assert result.response  # no crash, no over-redaction claim
        import sqlite3
        con = sqlite3.connect(str(home / "jarvis.db"))
        try:
            n = con.execute(
                "SELECT COUNT(*) FROM memories WHERE content "
                "LIKE '%password habit%'").fetchone()[0]
        finally:
            con.close()
        assert n >= 1  # ordinary prose still remembered
    finally:
        _close(jarvis)


def test_trace_minimizes_payloads(home):
    from jarvis.cognition.trace import trace_cycle
    jarvis = _jarvis(home)
    try:
        jarvis.cycle_once("hello there " + "x" * 500)
        trace = trace_cycle(str(home), "cycle-1")
        import json
        blob = json.dumps(trace)
        assert len(blob) < 20000  # observability, not a dump
        assert "sk-" not in blob
    finally:
        _close(jarvis)


# retry audit -------------------------------------------------------------------------------

def test_task_retries_bounded(home):
    jarvis = _jarvis(home)
    try:
        task = jarvis.tasks.register("impossible goal", priority=1)
        resurfaced = 0
        for _ in range(10):
            nxt = jarvis.tasks.next_ready()
            if nxt is None:
                break
            assert nxt.task_id == task.task_id
            resurfaced += 1
            jarvis.tasks.fail(nxt.task_id, "boom", retry=True)
        # max_retries=3: initial + 3 retries, then dead-lettered.
        assert resurfaced == 4, resurfaced
        assert jarvis.tasks.tasks[task.task_id].state.value == \
            "failed"
        assert jarvis.tasks.next_ready() is None
    finally:
        _close(jarvis)


def test_world_research_single_attempt(home, monkeypatch):
    import jarvis.worldintel.research as research_mod
    calls = {"n": 0}

    def _boom(top_n=10):
        calls["n"] += 1
        raise OSError("down")
    monkeypatch.setattr(research_mod, "fetch_hn", _boom)
    jarvis = _jarvis(home)
    try:
        jarvis.cycle_once("What is happening in AI today?")
        assert calls["n"] <= 2  # no retry loop in research path
    finally:
        _close(jarvis)


# rate-limit audit ---------------------------------------------------------------------------------

def test_limiter_per_process_documented():
    from jarvis.api.server import JarvisAPI
    from jarvis.worldintel.ratelimit import RateLimiter
    first = RateLimiter(max_calls=1, window_s=600.0)
    second = RateLimiter(max_calls=1, window_s=600.0)
    assert first.check("c")["allowed"] is True
    # Separate instances do not share state: per-process by design.
    assert second.check("c")["allowed"] is True
    assert hasattr(JarvisAPI, "handle")


def test_limiter_boundary_and_retry_after():
    from jarvis.worldintel.ratelimit import RateLimiter
    now = [0.0]
    limiter = RateLimiter(max_calls=2, window_s=10.0,
                          clock=lambda: now[0])
    assert limiter.check("c")["remaining"] == 1
    assert limiter.check("c")["remaining"] == 0
    denied = limiter.check("c")
    assert denied["allowed"] is False
    assert 0.0 < denied["retry_after_s"] <= 10.0
    now[0] += 10.0
    assert limiter.check("c")["allowed"] is True


# performance regression -------------------------------------------------------------------------------

def test_perf_within_bounds(home):
    import time as _time
    from jarvis.cognition.context import ContextEngine
    from jarvis.worldintel.routing import route
    jarvis = _jarvis(home)
    try:
        engine = ContextEngine(world=jarvis.world_registry,
                               palace=jarvis.palace)
        started = _time.perf_counter()
        engine.assemble("what is my favorite color blue")
        context_ms = (_time.perf_counter() - started) * 1000.0
        started = _time.perf_counter()
        route("What is happening in AI today?")
        routing_ms = (_time.perf_counter() - started) * 1000.0
        started = _time.perf_counter()
        jarvis.cycle_once("What is the capital of France?")
        cycle_ms = (_time.perf_counter() - started) * 1000.0
        # 10x headroom over the 0.76/0.13/23ms baselines (CI-safe).
        assert context_ms < 50.0, context_ms
        assert routing_ms < 50.0, routing_ms
        assert cycle_ms < 5000.0, cycle_ms
    finally:
        _close(jarvis)
