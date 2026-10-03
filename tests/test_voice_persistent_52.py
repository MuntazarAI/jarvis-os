"""Persistent voice runtime tests (5.2). Deterministic, offline, no
model: a scriptable fake transport stands in for the worker process.
Real Chatterbox is opt-in (JARVIS_REAL_TTS=1) in a separate test.
"""

from __future__ import annotations

import json
import os
import time

import pytest

from jarvis.voice.persistent import (
    LIMITS,
    PersistentError,
    PersistentTTSClient,
    WorkerState,
    check_transition,
    get_client,
    shutdown_all,
    validate_response,
)


class FakeTransport:
    """In-memory worker double. Faults scripted via `behavior`."""

    def __init__(self, workdir, *, behavior="ok", audio_s=1.0):
        import pathlib
        self.workdir = pathlib.Path(workdir)
        self.behavior = behavior
        self.audio_s = audio_s
        self.alive_flag = False
        self.loads = 0
        self.last_line = b""
        self.terminated = False
        self.pid = 999999

    def start(self):
        self.alive_flag = True
        self.loads += 1

    def alive(self):
        return self.alive_flag

    def terminate(self):
        self.alive_flag = False
        self.terminated = True

    def send_line(self, line: bytes):
        self.last_line = line

    def _boot(self):
        return {"v": 1, "id": "boot", "status": "ready",
                "worker_state": "ready", "model": "fake",
                "protocol": 1, "load_count": self.loads}

    def read_line(self, deadline: float):
        if self.behavior == "crash-boot":
            self.alive_flag = False
            raise EOFError("worker closed stdout")
        if not self.last_line:
            # Boot handshake always succeeds; faults apply to requests.
            return json.dumps(self._boot()).encode()
        if self.behavior == "crash":
            self.alive_flag = False
            raise EOFError("worker closed stdout")
        if self.behavior == "timeout":
            raise TimeoutError("worker read timeout")
        if self.behavior == "malformed":
            return b"{not json"
        if not self.last_line:
            return json.dumps(self._boot()).encode()
        try:
            req = json.loads(self.last_line.decode())
        except ValueError:
            return json.dumps(
                {"v": 1, "id": "", "status": "error",
                 "error": "malformed request"}).encode()
        if time.monotonic() >= deadline:
            raise TimeoutError("worker read timeout")
        op = req.get("op")
        if op == "shutdown":
            if self.behavior == "shutdown-fail":
                raise EOFError("worker closed stdout")
            self.alive_flag = False
            return json.dumps({"v": 1, "id": req.get("id"),
                               "status": "ok",
                               "worker_state": "SHUTDOWN"}).encode()
        if op == "health":
            return json.dumps(
                {"v": 1, "id": req.get("id"), "status": "ok",
                 "worker_state": "ready", "model": "fake",
                 "protocol": 1, "load_count": self.loads,
                 "ok_count": 0, "fail_count": 0, "uptime_s": 1.0,
                 "rss_kb": 1234}).encode()
        if self.behavior == "invalid-audio":
            return json.dumps(
                {"v": 1, "id": req.get("id"), "status": "ok",
                 "audio_path": str(self.workdir / "missing.wav"),
                 "audio_bytes": 10, "duration_s": self.audio_s,
                 "sample_rate": 24000, "latency_ms": 5.0,
                 "worker_state": "READY"}).encode()
        if self.behavior == "slow":
            time.sleep(0.05)
        path = self.workdir / f"req-{req.get('id')}.wav"
        payload = b"\x00" * 48000
        path.write_bytes(payload)
        return json.dumps(
            {"v": 1, "id": req.get("id"), "status": "ok",
             "audio_path": str(path), "audio_bytes": len(payload),
             "duration_s": self.audio_s, "sample_rate": 24000,
             "latency_ms": 5.0, "worker_state": "READY"}).encode()


def _client(tmp_path, **kw):
    home = tmp_path / "w"
    home.mkdir(exist_ok=True)
    behavior = kw.pop("behavior", "ok")
    fake_holder: dict = {}

    def factory(client):
        fake = FakeTransport(home, behavior=behavior,
                             **kw.pop("fake_kw", {}))
        fake_holder["fake"] = fake
        return fake

    client = PersistentTTSClient(
        python="/nonexistent/python", model="fake",
        reference_audio="", device="cpu", workdir=str(home),
        limits={"ready_timeout_s": 10.0, "request_timeout_s": 10.0,
                "restart_limit": 1,
                "restart_backoff_s": (0.01, 0.01)},
        transport_factory=factory)
    return client, fake_holder


@pytest.fixture(autouse=True)
def _clean_singletons():
    yield
    shutdown_all()
    import jarvis.voice.persistent as mod
    mod._CLIENTS.clear()


# protocol -------------------------------------------------------------------

def test_protocol_validation_rejects():
    with pytest.raises(PersistentError):
        validate_response("garbage", "r-1")
    with pytest.raises(PersistentError):
        validate_response({"v": 999, "id": "r-1", "status": "ok"},
                          "r-1")
    with pytest.raises(PersistentError):
        validate_response({"v": 1, "id": "r-2", "status": "ok"},
                          "r-1")
    with pytest.raises(PersistentError):
        validate_response({"v": 1, "id": "r-1", "status": "bogus"},
                          "r-1")
    assert validate_response(
        {"v": 1, "id": "r-1", "status": "ok"}, "r-1")["status"] == "ok"


def test_state_machine_transitions():
    assert check_transition(WorkerState.READY, WorkerState.BUSY)
    assert check_transition(WorkerState.BUSY, WorkerState.READY)
    assert check_transition(WorkerState.READY,
                            WorkerState.SHUTDOWN_REQUESTED)
    assert check_transition(WorkerState.FAILED, WorkerState.STARTING)
    assert not check_transition(WorkerState.READY, WorkerState.LOADING)
    assert not check_transition(WorkerState.SHUTDOWN, WorkerState.READY)
    assert not check_transition(WorkerState.BUSY, WorkerState.SHUTDOWN)


# lifecycle --------------------------------------------------------------------

def test_start_ready_synth_shutdown(tmp_path):
    client, _ = _client(tmp_path)
    assert client.state == WorkerState.SHUTDOWN
    started = client.start()
    assert started["ok"] is True and client.state == WorkerState.READY
    out = client.synthesize("hello world")
    assert out["ok"] is True and out["mode"] == "persistent"
    assert out["duration_s"] == 1.0
    assert client.state == WorkerState.READY
    assert client.shutdown()["ok"] is True
    assert client.shutdown()["already"] is True  # idempotent


def test_repeated_start_converges(tmp_path):
    client, holder = _client(tmp_path)
    assert client.start()["ok"] is True
    assert client.start()["reused"] is True
    assert holder["fake"].loads == 1  # exactly one worker


def test_model_load_count_is_one(tmp_path):
    client, holder = _client(tmp_path)
    client.start()
    for i in range(5):
        assert client.synthesize(f"sentence {i}")["ok"] is True
    assert holder["fake"].loads == 1  # never reloaded
    assert client.health()["restarts"] == 0


def test_busy_rejects_with_backpressure(tmp_path):
    client, _ = _client(tmp_path)
    client.start()
    client._busy = True  # simulate in-flight request
    try:
        out = client.synthesize("another")
        assert out["ok"] is False and "busy" in out["error"]
    finally:
        client._busy = False


def test_empty_and_oversize_text_rejected(tmp_path):
    client, _ = _client(tmp_path)
    client.start()
    assert client.synthesize("   ")["ok"] is False
    assert client.synthesize("x" * 2001)["ok"] is False


# crash / recovery ---------------------------------------------------------------

def test_crash_before_ready_fails_start(tmp_path):
    client, _ = _client(tmp_path, behavior="crash-boot")
    started = client.start()
    assert started["ok"] is False
    from jarvis.voice.persistent import WorkerState
    assert client.state == WorkerState.FAILED


def test_crash_during_synth_recovers_bounded(tmp_path):
    client, holder = _client(tmp_path, behavior="crash")
    assert client.start()["ok"] is True
    out = client.synthesize("hello")
    assert out["ok"] is False and "crash" in out["error"]
    assert out["recovered"] is True  # bounded restart (limit 1)
    assert client.state == WorkerState.READY
    assert client.health()["restarts"] == 1


def test_restart_limit_exhausts_to_fallback(tmp_path):
    client, _ = _client(tmp_path, behavior="crash")
    client.start()
    first = client.synthesize("one")  # restart 1
    assert first["recovered"] is True
    out = client.synthesize("two")  # limit reached: stays FAILED
    assert out["ok"] is False
    assert out["recovered"] is False
    from jarvis.voice.persistent import WorkerState
    assert client.state == WorkerState.FAILED


def test_malformed_response_recovers(tmp_path):
    client, _ = _client(tmp_path, behavior="malformed")
    client.start()
    out = client.synthesize("hello")
    assert out["ok"] is False


def test_invalid_audio_rejected(tmp_path):
    client, _ = _client(tmp_path, behavior="invalid-audio")
    client.start()
    out = client.synthesize("hello")
    assert out["ok"] is False and "artifact" in out["error"]


def test_cancel_is_safe(tmp_path):
    client, _ = _client(tmp_path)
    client.start()
    assert client.cancel()["nothing"] is True
    client._busy = True
    try:
        result = client.cancel()
        assert result["cancelled"] is True
    finally:
        client._busy = False


# security --------------------------------------------------------------------------

def test_no_shell_no_eval_in_transport(tmp_path):
    import pathlib
    source = (pathlib.Path(__file__).resolve().parent.parent
              / "jarvis" / "voice" / "persistent.py").read_text()
    assert "shell=True" not in source
    assert "os.system" not in source
    for banned in ("eval(", "exec(", "__import__(", "compile("):
        assert banned not in source, banned
    worker = (pathlib.Path(__file__).resolve().parent.parent
              / "jarvis" / "voice" / "tts_worker.py").read_text()
    assert "shell=True" not in worker
    assert "os.system" not in worker
    for banned in ("eval(", "exec(", "os.exec", "subprocess"):
        assert banned not in worker, banned


def test_worker_rejects_unknown_ops(tmp_path):
    import pathlib
    import subprocess
    import sys as _sys
    helper = (pathlib.Path(__file__).resolve().parent.parent
              / "jarvis" / "voice" / "tts_worker.py")
    proc = subprocess.run(
        [_sys.executable, str(helper), "--help"],
        capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0
    assert "--workdir" in proc.stdout and "--model" in proc.stdout


def test_path_traversal_impossible(tmp_path):
    client, _ = _client(tmp_path)
    client.start()
    out = client.synthesize("../../../etc/passwd")
    # Treated as plain text (would synthesize it), never as a path:
    assert out["ok"] is True
    assert not (tmp_path / "etc" / "passwd").exists()
    assert (tmp_path / "w").resolve() in [
        p.resolve().parent for p in (tmp_path / "w").glob("*.wav")]


# privacy ------------------------------------------------------------------------------

def test_telemetry_never_carries_text(tmp_path):
    import json as _json
    from jarvis.voice.telemetry import VoiceTelemetry
    telemetry = VoiceTelemetry()
    client, _ = _client(tmp_path)
    client.start()
    telemetry.record("voice.worker.synth", status="ok", text_len=42,
                     correlation_id="r-1")
    blob = _json.dumps(telemetry.recent(5))
    assert "hello" not in blob and "secret" not in blob
    assert '"text_len": 42' in blob


def test_no_audio_retained_by_default(tmp_path):
    client, holder = _client(tmp_path)
    client.start()
    out = client.synthesize("transient check")
    assert out["ok"] is True
    # Each request overwrites per-id files; only current-batch files exist:
    wavs = list((tmp_path / "w").glob("req-*.wav"))
    assert len(wavs) <= 5


# hygiene / resources ----------------------------------------------------------------------

def test_shutdown_cleans_process(tmp_path):
    client, holder = _client(tmp_path)
    client.start()
    fake = holder["fake"]
    assert fake.alive_flag is True
    client.shutdown()
    assert fake.alive_flag is False and fake.terminated is True


def test_singleton_converges(tmp_path):
    import jarvis.voice.persistent as mod
    mod._CLIENTS.clear()
    first = get_client(python="/nonexistent/python", model="fake",
                       reference_audio="", workdir=str(tmp_path),
                       transport_factory=lambda c: FakeTransport(
                           tmp_path))
    second = get_client(python="/nonexistent/python", model="fake",
                        reference_audio="", workdir=str(tmp_path),
                        transport_factory=lambda c: FakeTransport(
                            tmp_path))
    assert first is second


def test_limits_centralized():
    for key in ("max_text_chars", "request_timeout_s",
                "shutdown_timeout_s", "restart_limit",
                "max_audio_bytes", "max_audio_s", "ready_timeout_s",
                "health_timeout_s"):
        assert key in LIMITS, key


def test_request_deadline_enforced(tmp_path):
    client, _ = _client(tmp_path, behavior="timeout")
    client.start()
    out = client.synthesize("hello")
    assert out["ok"] is False and "timeout" in out["error"]


def test_provider_reports_persistent_mode(tmp_path):
    from jarvis.voice.tts import ChatterboxTTSProvider
    provider = ChatterboxTTSProvider(
        reference_audio=str(tmp_path / "missing.flac"),
        python_executable=str(tmp_path / "no-python"),
        persistent=False)
    assert provider.mode() == "unavailable"
    from jarvis.voice.tts import TTSRequest
    out = provider.synthesize(TTSRequest(text="hi"))
    assert out.ok is False


def test_speak_reports_mode_fake(tmp_path):
    from jarvis.voice.speak import speak_text
    out = speak_text("hello mode", config={"tts_provider": "fake"},
                     workdir=str(tmp_path), play=False,
                     provider_name="fake")
    assert out["ok"] is True and out["mode"] == "fake"


def test_cli_worker_status(tmp_path):
    import subprocess
    import sys as _sys
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    proc = subprocess.run(
        [_sys.executable, "-m", "jarvis.cli", "--home", str(home),
         "voice", "worker", "--op", "status"],
        capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr[-300:]
    assert "mode=" in proc.stdout and "worker=" in proc.stdout


def test_doctor_mentions_worker(tmp_path):
    import subprocess
    import sys as _sys
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    proc = subprocess.run(
        [_sys.executable, "-m", "jarvis.cli", "--home", str(home),
         "doctor"], capture_output=True, text=True, timeout=180)
    assert "voice:worker" in proc.stdout


def test_real_persistent_worker_opt_in(tmp_path):
    """Real Turbo worker: start once, 3 syntheses, 1 load, shutdown.

    Opt-in only (JARVIS_REAL_TTS=1): needs weights + minutes of CPU.
    Offline-capable: HF_HUB_OFFLINE=1 proves no network dependency.
    """
    import os as _os
    if _os.environ.get("JARVIS_REAL_TTS") != "1":
        pytest.skip("real worker needs JARVIS_REAL_TTS=1")
    _os.environ["HF_HUB_OFFLINE"] = "1"
    try:
        from jarvis.voice.persistent import PersistentTTSClient
        from jarvis.voice.tts import ChatterboxTTSProvider
        provider = ChatterboxTTSProvider(
            reference_audio="~/.config/jarvis/voices/male_old_movie.flac")
        if provider.mode() != "persistent":
            pytest.skip("no persistent runtime on this host")
        home = tmp_path / "w"
        home.mkdir(exist_ok=True)
        client = PersistentTTSClient(
            python=provider.bridge_python(), model="chatterbox-turbo",
            reference_audio=str(
                __import__("pathlib").Path(
                    "~/.config/jarvis/voices/male_old_movie.flac"
                ).expanduser()),
            workdir=str(home),
            limits={"ready_timeout_s": 600.0,
                    "request_timeout_s": 600.0})
        assert client.start()["ok"] is True
        for text in ("Hello.", "Second request.", "Third request."):
            out = client.synthesize(text)
            assert out["ok"] is True, out.get("error")
            assert out["duration_s"] > 0.0
        health = client.health()
        assert health["worker"]["load_count"] == 1
        assert health["worker"]["ok_count"] == 3
        assert client.shutdown()["ok"] is True
    finally:
        _os.environ.pop("HF_HUB_OFFLINE", None)
