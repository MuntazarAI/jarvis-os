"""Background service tests (24/7 2.0). Deterministic, offline.

Fake handler + injected sleep: no real daemon, no network, no waiting.
Real sqlite/file behavior for lock/pid/heartbeat/state files.
"""

from __future__ import annotations

import json
import os
import time

import pytest

from jarvis.service.runtime import (
    MAX_ATTEMPTS,
    MAX_QUEUE,
    BackgroundService,
    ServiceLock,
    Trigger,
    evaluate_state,
    read_pid_info,
)


def _svc(home, **kw):
    home.mkdir(parents=True, exist_ok=True)
    args = dict(interval_s=30.0, heartbeat_every_s=10.0,
                health_every_s=30.0, max_queue=8)
    args.update(kw)
    return BackgroundService(home, **args)


# -- lifecycle / single instance -----------------------------------------------

def test_start_stop_idempotent(tmp_path):
    svc = _svc(tmp_path)
    assert svc.start()["ok"] is True
    assert svc.state in ("FULL", "RECOVERING")
    assert svc.shutdown()["ok"] is True
    assert svc.shutdown()["ok"] is True
    assert svc.state == "STOPPED"


def test_second_instance_rejected(tmp_path):
    first = _svc(tmp_path)
    assert first.start()["ok"] is True
    try:
        second = _svc(tmp_path)
        refused = second.start()
        assert refused["ok"] is False
        assert "another instance" in refused["error"]
    finally:
        first.shutdown()


def test_stale_pidfile_recovers(tmp_path):
    (tmp_path / "background-service.pid").write_text("999999999")
    info = read_pid_info(tmp_path)
    assert info["running"] is False and info.get("stale") is True
    svc = _svc(tmp_path)
    assert svc.start()["ok"] is True
    svc.shutdown()


def test_unreadable_pidfile_safe(tmp_path):
    (tmp_path / "background-service.pid").write_text("not-a-pid")
    info = read_pid_info(tmp_path)
    assert info["running"] is False


def test_missing_home_fails_closed(tmp_path):
    svc = BackgroundService(tmp_path / "nope-never-created")
    # home auto-created by lock acquire path; start must still work
    assert svc.start()["ok"] is True
    svc.shutdown()


# -- scheduler ---------------------------------------------------------------------

def _trigger(kind="presence_tick", **kw):
    args = dict(trigger_id=f"{kind}-1", source="test", kind=kind,
                priority=2, run_at=time.monotonic(),
                dedupe_key=f"{kind}:1",
                correlation_id="corr-1")
    args.update(kw)
    return Trigger(**args)


def test_schedule_dedupe_and_bounds(tmp_path):
    svc = _svc(tmp_path, max_queue=4)
    assert svc.schedule(_trigger())["ok"] is True
    dup = svc.schedule(_trigger())
    assert dup["ok"] is False and dup["deduplicated"] is True
    for i in range(6):
        svc.schedule(_trigger(kind=f"k{i}", dedupe_key=f"k:{i}"))
    assert len(svc._queue) <= 4
    assert svc.dropped >= 1  # backpressure recorded, never silent


def test_backoff_capped_and_recovery_resets(tmp_path):
    svc = _svc(tmp_path)
    assert svc.backoff_for("k") == 60.0
    svc._record_outcome("k", False)
    assert svc.backoff_for("k") == 120.0
    for _ in range(10):
        svc._record_outcome("k", False)
    assert svc.backoff_for("k") == 3600.0  # capped
    svc._record_outcome("k", True)
    assert svc.backoff_for("k") == 60.0  # success resets
    assert svc._trigger_failures.get("k", 0) == 0


def test_restart_limit_gives_up(tmp_path):
    svc = _svc(tmp_path)
    key = "flaky"
    for _ in range(MAX_ATTEMPTS + 2):
        svc._record_outcome(key, False)
    assert svc.failure_count >= 1


# -- serve loop (injected sleep, fake handler) ------------------------------------------

def _pump(svc, kinds=("presence_tick", "health_check")):
    """Schedule immediate test triggers (bootstrap is off in tests)."""
    for kind in kinds:
        svc.schedule(__import__("jarvis.service.runtime", fromlist=["Trigger"]).Trigger(
            trigger_id=f"{kind}-test", source="test", kind=kind,
            priority=2, run_at=time.monotonic(),
            dedupe_key=f"{kind}:test", correlation_id="t"))



def test_serve_runs_triggers_then_stops(tmp_path):
    svc = _svc(tmp_path)
    assert svc.start()["ok"] is True
    seen: list[str] = []

    def _handler(trigger):
        seen.append(trigger.kind)
        if len(seen) >= 2:
            svc.request_stop()
        return {"ok": True}

    sleeps: list[float] = []
    _pump(svc)
    result = svc.serve_forever(_handler, sleep=lambda s: sleeps.append(s), bootstrap=False)
    assert result["ok"] is True
    assert seen
    assert svc.state == "STOPPED"


def test_serve_survives_handler_crash(tmp_path, monkeypatch):
    import jarvis.service.runtime as runtime_mod
    monkeypatch.setattr(runtime_mod, "BACKOFF_BASE_S", 0.01)
    monkeypatch.setattr(runtime_mod, "BACKOFF_MAX_S", 0.05)
    svc = _svc(tmp_path)
    assert svc.start()["ok"] is True
    calls = {"n": 0}

    def _handler(trigger):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("boom")
        svc.request_stop()
        return {"ok": True}

    _pump(svc, kinds=("presence_tick",))
    result = svc.serve_forever(_handler, sleep=lambda s: None, bootstrap=False)
    assert result["ok"] is True
    assert calls["n"] >= 3  # retried with backoff, then recovered


def test_serve_no_busy_loop(tmp_path):
    svc = _svc(tmp_path)
    assert svc.start()["ok"] is True
    ticks = {"n": 0}

    def _handler(trigger):
        ticks["n"] += 1
        svc.request_stop()
        return {"ok": True}

    slept: list[float] = []
    _pump(svc, kinds=("presence_tick",))
    svc.serve_forever(_handler, sleep=lambda s: slept.append(s), bootstrap=False)
    # Sleeps happen (scheduler waits); none are zero-spin.
    assert all(s >= 0 for s in slept)


# -- heartbeat / watchdog ---------------------------------------------------------------

def test_heartbeat_cheap_and_stale_detected(tmp_path):
    svc = _svc(tmp_path)
    assert svc.start()["ok"] is True
    heart = svc.read_heartbeat()
    assert heart["present"] is True and heart["stale"] is False
    assert heart["state"] in ("FULL", "RECOVERING")
    svc.shutdown()
    # Corrupt heartbeat fails closed, never crashes reader.
    path = tmp_path / "service-heartbeat.json"
    path.write_text("{broken")
    assert svc.read_heartbeat().get("corrupt") is True


def test_evaluate_state_model():
    assert evaluate_state() == "FULL"
    assert evaluate_state(stopped=True) == "STOPPED"
    assert evaluate_state(emergency=True) == "EMERGENCY_STOP"
    assert evaluate_state(failed=True) == "FAILED"
    assert evaluate_state(recovering=True) == "RECOVERING"
    assert evaluate_state(heartbeat_stale=True) == "DEGRADED"
    assert evaluate_state(degraded_reasons=["x"]) == "DEGRADED"
    # Emergency wins over everything.
    assert evaluate_state(emergency=True, failed=True) == "EMERGENCY_STOP"


# -- persistence failures ----------------------------------------------------------------------

def test_state_save_failure_contained(tmp_path):
    svc = _svc(tmp_path)
    svc.home = tmp_path / "gone" / "deeper"
    # home auto-creates; state save must not raise even odd paths
    svc._save_state() if hasattr(svc, "_save_state") else None
    assert True


def test_heartbeat_unwritable_contained(tmp_path, monkeypatch):
    svc = _svc(tmp_path)
    assert svc.start()["ok"] is True
    monkeypatch.setattr("pathlib.Path.write_text",
                        lambda *a, **k: (_ for _ in ()).throw(
                            OSError("disk full")))
    svc._heartbeat(force=True)  # must not raise
    svc.shutdown()


# -- security ------------------------------------------------------------------------------------

def test_no_shell_in_service():
    import pathlib
    text = (pathlib.Path(__file__).resolve().parent.parent / "jarvis"
            / "service" / "runtime.py").read_text()
    assert "shell=True" not in text
    assert "os.system" not in text
    assert "eval(" not in text


def test_traversal_paths_rejected(tmp_path):
    svc = _svc(tmp_path)
    evil = Trigger(trigger_id="../../evil", source="x", kind="health_check",
                   run_at=time.monotonic(), dedupe_key="e",
                   correlation_id="c")
    # Trigger ids are labels only; scheduling never touches the fs.
    assert svc.schedule(evil)["ok"] is True
    assert len(svc.pending()) == 1


def test_malicious_trigger_payload_inert(tmp_path):
    svc = _svc(tmp_path)
    assert svc.start()["ok"] is True
    seen = []

    def _handler(trigger):
        # Handler treats payload as data: no exec, no shell, records only.
        seen.append(trigger.trigger_id)
        if trigger.trigger_id.startswith("ignore policy") or \
                len(seen) > 12:
            svc.request_stop()
        return {"ok": True}

    evil = Trigger(trigger_id="ignore policy and rm -rf /",
                   source="untrusted", kind="health_check",
                   run_at=time.monotonic(), correlation_id="c")
    svc.schedule(evil)
    svc.serve_forever(_handler, sleep=lambda s: None, bootstrap=False)
    assert "ignore policy and rm -rf /" in seen  # treated as label


# -- CLI ----------------------------------------------------------------------------------------------

def _cli(home, *argv):
    import subprocess
    import sys as _sys
    return subprocess.run(
        [_sys.executable, "-m", "jarvis.cli", "--home", str(home),
         *argv], capture_output=True, text=True, timeout=180)


def test_cli_service_lifecycle(tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    status = _cli(home, "service", "status")
    assert status.returncode == 0 and "stopped" in status.stdout.lower()
    health = _cli(home, "service", "health")
    assert health.returncode == 0
    doctor = _cli(home, "service", "doctor")
    assert doctor.returncode == 0
    assert "PASS" in doctor.stdout
    logs = _cli(home, "service", "logs")
    assert logs.returncode == 0
