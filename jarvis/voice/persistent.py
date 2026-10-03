"""Persistent Chatterbox runtime client (5.2).

Single owner of the worker lifecycle: exactly one
:class:`PersistentTTSClient` per (python, model, reference, workdir)
via :func:`get_client`. The worker (``tts_worker.py``) loads Turbo
once and stays READY across requests over stdio JSONL — no sockets, no
network, no shell. One active synthesis at a time; a BUSY worker
rejects new work deterministically (backpressure).

Failure model: timeouts abandon the request, taint the worker, and
trigger a bounded restart (max 2, backoff). Every response is
correlated by request id AND worker generation — a late line from a
dead worker can never satisfy a new request, because the old worker is
terminated before the new generation starts.

Telemetry carries metadata only (lengths, latencies, counts) — never
speech text, audio, or secrets.
"""

from __future__ import annotations

import atexit
import json
import os
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from .telemetry import TELEMETRY
from .tts_worker import ID_CHARS, MAX_TEXT_CHARS, PROTOCOL_VERSION

# -- centralized limits (no magic numbers elsewhere) ---------------------

LIMITS = {
    "protocol": PROTOCOL_VERSION,
    "max_text_chars": MAX_TEXT_CHARS,
    "max_request_bytes": 64 * 1024,
    "max_audio_bytes": 32 * 1024 * 1024,
    "max_audio_s": 120.0,
    "startup_timeout_s": 120.0,   # spawn + interpreter import
    "ready_timeout_s": 1800.0,    # + model load (first run downloads)
    "request_timeout_s": 900.0,   # worst-case CPU synthesis
    "health_timeout_s": 10.0,
    "shutdown_timeout_s": 15.0,
    "restart_limit": 2,
    "restart_backoff_s": (5.0, 15.0),
    "max_worker_rss_mb": 0,       # 0 = observe only, never enforce
}

MIN_PREFIX_HINT = "persistent"


class WorkerState(str, Enum):
    STARTING = "starting"
    LOADING = "loading"
    READY = "ready"
    BUSY = "busy"
    SHUTDOWN_REQUESTED = "shutdown_requested"
    SHUTDOWN = "shutdown"
    FAILED = "failed"


TRANSITIONS: dict[WorkerState, frozenset[WorkerState]] = {
    WorkerState.STARTING: frozenset({WorkerState.LOADING,
                                     WorkerState.FAILED}),
    WorkerState.LOADING: frozenset({WorkerState.READY,
                                    WorkerState.FAILED}),
    WorkerState.READY: frozenset({WorkerState.BUSY,
                                  WorkerState.SHUTDOWN_REQUESTED,
                                  WorkerState.FAILED}),
    WorkerState.BUSY: frozenset({WorkerState.READY, WorkerState.FAILED}),
    WorkerState.SHUTDOWN_REQUESTED: frozenset({WorkerState.SHUTDOWN,
                                               WorkerState.FAILED}),
    WorkerState.SHUTDOWN: frozenset(),
    WorkerState.FAILED: frozenset({WorkerState.STARTING}),
}


def check_transition(frm: WorkerState, to: WorkerState) -> bool:
    return to in TRANSITIONS.get(frm, frozenset())


class PersistentError(RuntimeError):
    """Structured runtime failure (returned as data, not raised, on the
    synthesis path)."""


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def validate_response(raw: object, expect_id: str) -> dict[str, Any]:
    """Fail-closed response validation. Raises PersistentError."""
    if not isinstance(raw, dict):
        raise PersistentError("malformed worker response")
    if raw.get("v") != PROTOCOL_VERSION:
        raise PersistentError("protocol mismatch")
    if raw.get("id") != expect_id:
        raise PersistentError("stale/unknown response id")
    if raw.get("status") not in ("ok", "ready", "error"):
        raise PersistentError("bad response status")
    return raw


class StdioTransport:
    """Real worker transport: argv list, no shell, pipes only."""

    def __init__(self, python: str, workdir: Path, model: str,
                 reference: str, device: str = "cpu") -> None:
        self.python = python
        self.workdir = workdir
        self.model = model
        self.reference = reference
        self.device = device
        self.proc: subprocess.Popen | None = None
        self.pid = 0

    def start(self) -> None:
        project = str(Path(__file__).resolve().parent.parent.parent)
        helper = Path(__file__).resolve().parent / "tts_worker.py"
        env = dict(os.environ)
        # The worker module lives in this repo, which the venv does not
        # know about. Extend the CHILD's path only (never the parent's,
        # never system site-packages).
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = project + (
            os.pathsep + existing if existing else "")
        self.proc = subprocess.Popen(
            [self.python, str(helper), "--workdir", str(self.workdir),
             "--model", self.model, "--reference", self.reference,
             "--device", self.device],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=False, shell=False,
            cwd=str(self.workdir), env=env)
        self.pid = int(self.proc.pid)

    def send_line(self, line: bytes) -> None:
        assert self.proc is not None and self.proc.stdin is not None
        self.proc.stdin.write(line + b"\n")
        self.proc.stdin.flush()

    def read_line(self, deadline: float) -> bytes:
        """Read one stdout line before the monotonic deadline."""
        assert self.proc is not None and self.proc.stdout is not None
        import selectors
        sel = selectors.DefaultSelector()
        sel.register(self.proc.stdout, selectors.EVENT_READ)
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("worker read timeout")
                ready = sel.select(timeout=min(remaining, 1.0))
                if ready:
                    line = self.proc.stdout.readline(
                        LIMITS["max_request_bytes"] + 4096)
                    if not line:
                        raise EOFError("worker closed stdout")
                    return line
        finally:
            try:
                sel.unregister(self.proc.stdout)
            except Exception:
                pass

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def terminate(self) -> None:
        proc, self.proc = self.proc, None
        if proc is None:
            return
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    pass
        try:
            if proc.stdin:
                proc.stdin.close()
        except BrokenPipeError:
            pass
        try:
            if proc.stdout:
                proc.stdout.close()
        except BrokenPipeError:
            pass


class PersistentTTSClient:
    """One worker, one model, one active synthesis. Idempotent
    start/shutdown; bounded restarts; generation-guarded responses."""

    def __init__(self, *, python: str, model: str = "chatterbox-turbo",
                 reference_audio: str = "", device: str = "cpu",
                 workdir: str | Path | None = None,
                 limits: dict[str, Any] | None = None,
                 transport_factory: Any = None) -> None:
        self.python = python
        self.model = model
        self.reference_audio = reference_audio
        self.device = device
        self.workdir = Path(workdir) if workdir else Path(
            os.path.expanduser("~/.config/jarvis/tts-worker"))
        self.limits = dict(LIMITS)
        if limits:
            self.limits.update(limits)
        self._factory = transport_factory
        self._transport: Any = None
        self._state = WorkerState.SHUTDOWN
        self._gen = 0
        self._busy = False
        self._restarts = 0
        self._ok = 0
        self._failed = 0
        self._timeouts = 0
        self._last_ok_at = 0.0

    # -- state ---------------------------------------------------------
    @property
    def state(self) -> WorkerState:
        return self._state

    def _set(self, to: WorkerState) -> None:
        if not check_transition(self._state, to) and not (
                self._state == to):
            raise PersistentError(
                f"illegal worker transition {self._state}->{to}")
        self._state = to

    # -- lifecycle -----------------------------------------------------
    def start(self) -> dict[str, Any]:
        """Idempotent: repeated start() converges on one worker."""
        if self._state in (WorkerState.READY, WorkerState.BUSY):
            return {"ok": True, "reused": True,
                    "state": self._state.value}
        if self._state not in (WorkerState.SHUTDOWN, WorkerState.FAILED):
            raise PersistentError(
                f"cannot start from {self._state}")
        if self._state == WorkerState.FAILED:
            self._set(WorkerState.STARTING)
        else:
            self._state = WorkerState.STARTING
        started = time.monotonic()
        try:
            self.workdir.mkdir(parents=True, exist_ok=True)
            for stale in self.workdir.glob("req-*.wav"):
                try:
                    stale.unlink()
                except OSError:
                    pass
            self._transport = self._make_transport()
            self._transport.start()
            self._gen += 1
            self._set(WorkerState.LOADING)
            ready = self._await_ready(started)
            self._set(WorkerState.READY)
            TELEMETRY.record("voice.worker.start", status="ok",
                             latency_ms=round(
                                 (time.monotonic() - started) * 1000, 1))
            return {"ok": True, "reused": False, "state": "ready",
                    "time_to_ready_s": round(
                        time.monotonic() - started, 1),
                    "model": ready.get("model", self.model)}
        except Exception as exc:
            self._cleanup_transport()
            try:
                self._set(WorkerState.FAILED)
            except PersistentError:
                self._state = WorkerState.FAILED
            TELEMETRY.record("voice.worker.start", status="failed",
                             detail=f"{type(exc).__name__}"[:64])
            return {"ok": False, "state": "failed",
                    "error": f"{type(exc).__name__}: {exc}"[:300]}

    def _make_transport(self) -> Any:
        if self._factory is not None:
            return self._factory(self)
        return StdioTransport(self.python, self.workdir, self.model,
                              self.reference_audio, self.device)

    def _await_ready(self, started: float) -> dict[str, Any]:
        deadline = started + float(self.limits["ready_timeout_s"])
        assert self._transport is not None
        skipped = 0
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError("worker readiness timeout")
            if not self._transport.alive():
                raise EOFError("worker died during startup")
            try:
                line = self._transport.read_line(
                    min(deadline, time.monotonic() + 5.0))
            except TimeoutError:
                continue
            try:
                raw = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                # Third-party import banners on stdout: tolerate a few
                # during startup only. Request path stays strict.
                skipped += 1
                if skipped > 20:
                    raise PersistentError("malformed readiness line")
                continue
            if raw.get("status") == "ready" and raw.get("id") == "boot":
                if raw.get("v") != PROTOCOL_VERSION:
                    raise PersistentError("protocol mismatch")
                return raw
            if raw.get("status") == "error" and not raw.get("id"):
                raise PersistentError(
                    str(raw.get("error", "worker failed"))[:200])

    def shutdown(self) -> dict[str, Any]:
        """Idempotent: repeated shutdown() is safe."""
        if self._state == WorkerState.SHUTDOWN:
            return {"ok": True, "already": True}
        if self._state == WorkerState.BUSY:
            return {"ok": False,
                    "error": "worker busy; cancel first"}
        if self._state != WorkerState.SHUTDOWN_REQUESTED:
            try:
                self._set(WorkerState.SHUTDOWN_REQUESTED)
            except PersistentError:
                self._cleanup_transport()
                self._state = WorkerState.SHUTDOWN
                return {"ok": True}
        if self._transport is not None:
            try:
                req_id = _new_id("r")
                self._transport.send_line(json.dumps(
                    {"v": PROTOCOL_VERSION, "id": req_id,
                     "op": "shutdown"}).encode())
                self._transport.read_line(
                    time.monotonic() + float(
                        self.limits["shutdown_timeout_s"]))
            except Exception:
                pass
        self._cleanup_transport()
        try:
            self._set(WorkerState.SHUTDOWN)
        except PersistentError:
            self._state = WorkerState.SHUTDOWN
        return {"ok": True}

    def _cleanup_transport(self) -> None:
        transport, self._transport = self._transport, None
        self._busy = False
        if transport is not None:
            try:
                transport.terminate()
            except Exception:
                pass

    # -- synthesis -----------------------------------------------------
    def synthesize(self, text: str, *, request_id: str = "",
                   exaggeration: float = 0.5, temperature: float = 0.8,
                   cfg_weight: float = 0.5,
                   language: str = "en") -> dict[str, Any]:
        """One bounded synthesis. Never raises: failures are data."""
        started = time.monotonic()
        if self._state != WorkerState.READY:
            return {"ok": False, "provider": "chatterbox",
                    "mode": "persistent", "recovered": False,
                    "error": f"worker not ready ({self._state.value})"}
        if self._busy:
            return {"ok": False, "provider": "chatterbox",
                    "mode": "persistent",
                    "error": "worker busy; backpressure: retry later"}
        if not text.strip() or len(text) > int(
                self.limits["max_text_chars"]):
            return {"ok": False, "provider": "chatterbox",
                    "mode": "persistent",
                    "error": "text empty or too long"}
        req_id = request_id or _new_id("r")
        self._busy = True
        try:
            self._set(WorkerState.BUSY)
        except PersistentError as exc:
            self._busy = False
            return {"ok": False, "provider": "chatterbox",
                    "mode": "persistent", "error": str(exc)[:160]}
        deadline = started + float(self.limits["request_timeout_s"])
        gen = self._gen
        try:
            payload = {"v": PROTOCOL_VERSION, "id": req_id,
                       "op": "synthesize", "text": text,
                       "exaggeration": exaggeration,
                       "temperature": temperature,
                       "cfg_weight": cfg_weight}
            raw_line = json.dumps(payload).encode()
            if len(raw_line) > int(self.limits["max_request_bytes"]):
                raise PersistentError("request too large")
            assert self._transport is not None
            self._transport.send_line(raw_line)
            line = self._transport.read_line(deadline)
            try:
                raw = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                raise PersistentError("malformed worker response")
            data = validate_response(raw, req_id)
            if gen != self._gen:
                raise PersistentError("stale worker generation")
            if data.get("status") != "ok":
                raise PersistentError(
                    str(data.get("error", "synthesis failed"))[:200])
            audio_path = str(data.get("audio_path", ""))
            if not self._validate_artifact(audio_path, data):
                raise PersistentError("invalid audio artifact")
            self._ok += 1
            self._last_ok_at = time.time()
            latency = round((time.monotonic() - started) * 1000.0, 1)
            TELEMETRY.record("voice.worker.synth", status="ok",
                             latency_ms=latency,
                             text_len=len(text),
                             audio_duration_s=float(
                                 data.get("duration_s", 0.0)),
                             correlation_id=req_id)
            return {"ok": True, "provider": "chatterbox",
                    "mode": "persistent",
                    "audio_path": audio_path,
                    "audio_bytes": int(data.get("audio_bytes", 0)),
                    "duration_s": float(data.get("duration_s", 0.0)),
                    "sample_rate": int(data.get("sample_rate", 24000)),
                    "latency_ms": latency,
                    "worker_state": "ready", "tts_id": req_id}
        except (TimeoutError, EOFError, PersistentError,
                OSError) as exc:
            kind = ("timeout" if isinstance(exc, TimeoutError)
                    else "crash" if isinstance(exc, EOFError)
                    else "error")
            self._failed += 1
            if isinstance(exc, TimeoutError):
                self._timeouts += 1
            TELEMETRY.record("voice.worker.synth", status="failed",
                             latency_ms=round(
                                 (time.monotonic() - started) * 1000.0,
                                 1),
                             text_len=len(text),
                             correlation_id=req_id,
                             detail=kind)
            recovered = self._recover(kind, str(exc)[:160])
            return {"ok": False, "provider": "chatterbox",
                    "mode": "persistent",
                    "error": f"worker {kind}: {exc}"[:200],
                    "recovered": recovered}
        finally:
            self._busy = False
            if self._state == WorkerState.BUSY:
                try:
                    self._set(WorkerState.READY)
                except PersistentError:
                    pass

    def _validate_artifact(self, path: str, data: dict) -> bool:
        if not path:
            return False
        candidate = Path(path)
        try:
            if not candidate.is_file():
                return False
            # Confined to the client-owned workdir (no traversal).
            if self.workdir.resolve() not in \
                    candidate.resolve().parents:
                return False
            size = candidate.stat().st_size
            if size <= 0 or size > int(self.limits["max_audio_bytes"]):
                return False
            duration = float(data.get("duration_s", 0.0))
            if duration <= 0.0 or duration > float(
                    self.limits["max_audio_s"]):
                return False
            if int(data.get("audio_bytes", 0)) != size:
                return False
            return True
        except (OSError, ValueError):
            return False

    def cancel(self) -> dict[str, Any]:
        """Abandon current work: terminate + bounded restart. Model-level
        cancellation is unsafe mid-inference, so cancellation happens at
        the request boundary (documented limitation)."""
        if not self._busy:
            return {"ok": True, "nothing": True}
        self._cleanup_transport()
        try:
            self._set(WorkerState.FAILED)
        except PersistentError:
            self._state = WorkerState.FAILED
        recovered = self._recover("cancelled", "cancel requested")
        return {"ok": True, "cancelled": True, "recovered": recovered}

    def _recover(self, kind: str, detail: str) -> bool:
        """Bounded restart with backoff. Returns True if a fresh READY
        worker stands afterwards."""
        self._cleanup_transport()
        try:
            self._set(WorkerState.FAILED)
        except PersistentError:
            self._state = WorkerState.FAILED
        if self._restarts >= int(self.limits["restart_limit"]):
            TELEMETRY.record("voice.worker.restart", status="failed",
                             detail="restart limit reached")
            return False
        backoff = float(self.limits["restart_backoff_s"][min(
            self._restarts,
            len(self.limits["restart_backoff_s"]) - 1)])
        time.sleep(min(backoff, 30.0))
        self._restarts += 1
        TELEMETRY.record("voice.worker.restart", status="ok",
                         detail=f"{kind}; attempt {self._restarts}")
        result = self.start()
        return bool(result.get("ok"))

    # -- health --------------------------------------------------------
    def health(self) -> dict[str, Any]:
        base: dict[str, Any] = {
            "provider": "chatterbox", "mode": "persistent",
            "state": self._state.value, "model": self.model,
            "protocol": PROTOCOL_VERSION, "generation": self._gen,
            "ok": self._ok, "failed": self._failed,
            "timeouts": self._timeouts, "restarts": self._restarts,
            "last_ok_at": self._last_ok_at, "busy": self._busy,
            "rss_kb": 0, "worker": {},
        }
        if self._state != WorkerState.READY or self._transport is None:
            return base
        req_id = _new_id("r")
        try:
            self._transport.send_line(json.dumps(
                {"v": PROTOCOL_VERSION, "id": req_id,
                 "op": "health"}).encode())
            line = self._transport.read_line(
                time.monotonic() + float(
                    self.limits["health_timeout_s"]))
            data = validate_response(
                json.loads(line.decode("utf-8")), req_id)
            base["worker"] = {
                k: data.get(k) for k in
                ("worker_state", "load_count", "ok_count",
                 "fail_count", "uptime_s", "rss_kb")}
            base["rss_kb"] = int(data.get("rss_kb", 0) or 0)
            cap = int(self.limits.get("max_worker_rss_mb", 0) or 0)
            if cap > 0 and base["rss_kb"] > cap * 1024:
                base["memory_pressure"] = True
        except Exception as exc:
            base["worker_error"] = f"{type(exc).__name__}"[:64]
        return base


_CLIENTS: dict[str, PersistentTTSClient] = {}
_ATEXIT_ARMED = False


def client_key(python: str, model: str, reference: str, device: str,
               workdir: str) -> str:
    return "|".join((python, model, reference, device, workdir))


def get_client(*, python: str, model: str, reference_audio: str,
               device: str = "cpu", workdir: str = "",
               limits: dict | None = None,
               transport_factory: Any = None) -> PersistentTTSClient:
    """Process-wide singleton per runtime identity. Repeated calls
    converge on one client (single-owner principle)."""
    global _ATEXIT_ARMED
    key = client_key(python, model, reference_audio, device, workdir)
    client = _CLIENTS.get(key)
    if client is None:
        client = PersistentTTSClient(
            python=python, model=model,
            reference_audio=reference_audio, device=device,
            workdir=workdir or None, limits=limits,
            transport_factory=transport_factory)
        _CLIENTS[key] = client
        if not _ATEXIT_ARMED:
            _ATEXIT_ARMED = True
            atexit.register(shutdown_all)
    return client


def shutdown_all() -> None:
    for client in list(_CLIENTS.values()):
        try:
            client.shutdown()
        except Exception:
            pass


__all__ = ["WorkerState", "TRANSITIONS", "check_transition",
           "PersistentError", "LIMITS", "StdioTransport",
           "PersistentTTSClient", "get_client", "shutdown_all",
           "validate_response"]
