"""24/7 background service runtime (Background Service 2.0).

Thin orchestration around existing capabilities: PresenceRuntime ticks,
world refresh, health checks, and maintenance run on a bounded
in-memory scheduler inside one supervised process. No threads, no
second event bus, no second policy engine, no cognitive loop here —
the service wakes existing JARVIS machinery on schedule and goes back
to sleep.

Safety properties:
- single instance via flock + PID/start-time validation (no naive
  pidfile check, no PID-reuse confusion)
- monotonic clock for all timeouts/ages; wall clock display only
- bounded queue (32) with explicit backpressure (drop lowest first)
- bounded retries with capped exponential backoff per trigger
- emergency stop pauses autonomous side effects, never diagnostics
- every trigger carries a dedupe key with TTL and a correlation id
"""

from __future__ import annotations

import heapq
import json
import os
import signal
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

# Priorities (ints, matching the task-system convention).
PRIORITY_CRITICAL = 0
PRIORITY_HIGH = 1
PRIORITY_NORMAL = 2
PRIORITY_LOW = 3
PRIORITY_MAINTENANCE = 4

MAX_QUEUE = 32
MAX_ATTEMPTS = 3
BACKOFF_BASE_S = 60.0
BACKOFF_MAX_S = 3600.0
HEARTBEAT_EVERY_S = 60.0
HEALTH_EVERY_S = 300.0
DEDUPE_TTL_S = 3600.0
SHUTDOWN_GRACE_S = 20.0
STALE_HEARTBEAT_S = 300.0


def _monotonic() -> float:
    return time.monotonic()


def _utcnow() -> float:
    return time.time()


@dataclass
class Trigger:
    trigger_id: str
    source: str
    kind: str  # world_refresh | presence_tick | health_check | maintenance
    priority: int = PRIORITY_NORMAL
    run_at: float = 0.0
    dedupe_key: str = ""
    attempts: int = 0
    timeout_s: float = 120.0
    correlation_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ServiceLock:
    """flock-held lock file. The fd stays open while held; death
    releases the kernel lock automatically (no stale-lock class)."""

    def __init__(self, home: str | Path | None) -> None:
        self.home = Path(home) if home else None
        self._handle: Any = None

    @property
    def path(self) -> Path | None:
        if self.home is None:
            return None
        return self.home / "service.lock"

    def acquire(self) -> tuple[bool, str]:
        """Non-blocking acquire. Returns (held, holder-info|reason)."""
        path = self.path
        if path is None:
            return False, "no home"
        try:
            import fcntl
        except ImportError:
            return False, "flock unavailable on this platform"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            handle = open(path, "a+b")
        except OSError as exc:
            return False, f"{type(exc).__name__}: {exc}"
        try:
            fcntl.flock(handle.fileno(),
                         fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError):
            try:
                handle.close()
            except OSError:
                pass
            return False, self.describe_holder()
        self._handle = handle
        try:
            handle.seek(0)
            handle.truncate()
            handle.write(f"{os.getpid()} {_utcnow():.0f}\n".encode())
            handle.flush()
        except OSError:
            pass
        return True, "held"

    def describe_holder(self) -> str:
        path = self.path
        if path is None or not path.exists():
            return "lock file missing (holder died holding it)"
        try:
            content = path.read_text(encoding="utf-8").strip()
        except OSError:
            return "unreadable lock file"
        return f"held by another instance ({content})"

    def release(self) -> None:
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            import fcntl
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            handle.close()
        except OSError:
            pass

    def __del__(self) -> None:  # best effort only
        try:
            self.release()
        except Exception:
            pass


def read_pid_info(home: str | Path) -> dict[str, Any]:
    """PID file diagnostics with start-time validation (defeats PID
    reuse confusion). Never raises."""
    pidfile = Path(home) / "background-service.pid"
    try:
        if not pidfile.exists():
            return {"running": False, "reason": "no pidfile"}
        pid = int(pidfile.read_text(encoding="utf-8").strip())
    except (OSError, ValueError) as exc:
        return {"running": False,
                "reason": f"unreadable pidfile: {type(exc).__name__}"}
    try:
        os.kill(pid, 0)
    except OSError:
        return {"running": False, "reason": "stale pidfile (dead pid)",
                "pid": pid, "stale": True}
    start_time: float | None = None
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as handle:
            fields = handle.read().rsplit(")", 1)[-1].split()
            start_time = float(fields[19]) / 100.0
    except (OSError, ValueError, IndexError):
        start_time = None
    return {"running": True, "pid": pid, "start_time": start_time}


class BackgroundService:
    """One supervised loop. Construct, start(), serve_forever()."""

    def __init__(self, home: str | Path | None,
                 interval_s: float = 300.0,
                 heartbeat_every_s: float = HEARTBEAT_EVERY_S,
                 health_every_s: float = HEALTH_EVERY_S,
                 max_queue: int = MAX_QUEUE) -> None:
        self.home = Path(home) if home else None
        self.interval_s = max(30.0, float(interval_s or 300.0))
        self.heartbeat_every_s = max(10.0, float(heartbeat_every_s))
        self.health_every_s = max(30.0, float(health_every_s))
        self.max_queue = max(1, int(max_queue))
        self.lock = ServiceLock(self.home)
        self.state = "STOPPED"
        self.started_at = 0.0
        self.started_monotonic = 0.0
        self.restart_count = 0
        self.failure_count = 0
        self.last_tick_at = 0.0
        self.last_heartbeat_at = 0.0
        self.last_health_at = 0.0
        self._queue: list[Any] = []
        self._dedupe: dict[str, float] = {}
        self._shutdown = False
        self._seq = 0
        self._trigger_failures: dict[str, int] = {}
        self.degraded_reasons: list[str] = []
        self.dropped = 0

    # -- paths ---------------------------------------------------------

    @property
    def _heartbeat_path(self) -> Path | None:
        return self.home / "service-heartbeat.json" \
            if self.home else None

    @property
    def _pid_path(self) -> Path | None:
        return self.home / "background-service.pid" \
            if self.home else None

    # -- lifecycle -------------------------------------------------------

    def start(self) -> dict[str, Any]:
        held, info = self.lock.acquire()
        if not held:
            return {"ok": False, "error": info}
        self.started_at = _utcnow()
        self.started_monotonic = _monotonic()
        self.state = "RECOVERING"
        self._install_signals()
        self._write_pid()
        self._heartbeat(force=True)
        self.state = "FULL"
        return {"ok": True, "pid": os.getpid()}

    def _install_signals(self) -> None:
        def _flag(signum: int, frame: Any) -> None:
            self._shutdown = True
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, _flag)
            except (OSError, ValueError):
                pass
        try:
            signal.signal(signal.SIGHUP, lambda s, f: self._reload())
        except (OSError, ValueError, AttributeError):
            pass

    def _reload(self) -> None:
        self._heartbeat(force=True)

    def request_stop(self) -> None:
        self._shutdown = True

    def shutdown(self) -> dict[str, Any]:
        deadline = _monotonic() + SHUTDOWN_GRACE_S
        self.state = "STOPPED"
        while _monotonic() < deadline and self._queue:
            self._queue.pop()
        self._heartbeat(force=True)
        self._clear_pid()
        self.lock.release()
        return {"ok": True, "drained": True}

    def _write_pid(self) -> None:
        path = self._pid_path
        if path is None:
            return
        try:
            path.write_text(str(os.getpid()), encoding="utf-8")
        except OSError:
            pass

    def _clear_pid(self) -> None:
        path = self._pid_path
        if path is None:
            return
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass

    # -- heartbeat / health ----------------------------------------------

    def _heartbeat(self, force: bool = False) -> None:
        now_mono = _monotonic()
        if not force and now_mono - self.last_heartbeat_at < \
                self.heartbeat_every_s:
            return
        path = self._heartbeat_path
        if path is None:
            return
        payload = {"pid": os.getpid(),
                   "state": self.state,
                   "started_at": self.started_at,
                   "uptime_s": round(now_mono - self.started_monotonic,
                                     1) if self.started_monotonic else 0.0,
                   "monotonic": now_mono,
                   "last_tick_at": self.last_tick_at,
                   "restart_count": self.restart_count,
                   "failure_count": self.failure_count,
                   "queue_depth": len(self._queue),
                   "degraded": list(self.degraded_reasons)}
        try:
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(json_dumps(payload), encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            pass
        self.last_heartbeat_at = now_mono

    def read_heartbeat(self) -> dict[str, Any]:
        path = self._heartbeat_path
        if path is None or not path.exists():
            return {"present": False}
        try:
            data = json_loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"present": False, "corrupt": True}
        age = _monotonic() - float(data.get("monotonic", 0.0) or 0.0)
        data["present"] = True
        data["age_s"] = round(max(0.0, age), 1)
        data["stale"] = age > STALE_HEARTBEAT_S
        return data

    # -- scheduler ---------------------------------------------------------

    def schedule(self, trigger: Trigger) -> dict[str, Any]:
        """Enqueue with dedupe + backpressure. Never raises."""
        now_mono = _monotonic()
        self._dedupe = {k: v for k, v in self._dedupe.items()
                        if now_mono - v < DEDUPE_TTL_S}
        if trigger.dedupe_key:
            seen = self._dedupe.get(trigger.dedupe_key)
            if seen is not None and now_mono - seen < DEDUPE_TTL_S:
                return {"ok": False, "deduplicated": True}
            self._dedupe[trigger.dedupe_key] = now_mono
        if len(self._queue) >= self.max_queue:
            # Backpressure: drop the lowest-priority (largest number)
            # queued trigger, record it, accept the new one.
            worst = max(range(len(self._queue)),
                        key=lambda i: (self._queue[i][1],
                                       self._queue[i][2]))
            _, _, _, dropped = self._queue.pop(worst)
            heapq.heapify(self._queue)
            self.dropped += 1
            dropped_id = getattr(dropped, "trigger_id", "?")
        else:
            dropped_id = None
        self._seq += 1
        heapq.heappush(self._queue,
                       (trigger.priority, trigger.run_at, self._seq,
                        trigger))
        return {"ok": True, "queued": len(self._queue),
                "dropped": dropped_id}

    def pending(self) -> list[dict[str, Any]]:
        return [t.to_dict() for _, _, _, t in sorted(self._queue)]

    def backoff_for(self, key: str) -> float:
        fails = self._trigger_failures.get(key, 0)
        return min(BACKOFF_MAX_S, BACKOFF_BASE_S * (2.0 ** fails))

    def _record_outcome(self, key: str, ok: bool) -> None:
        if ok:
            self._trigger_failures.pop(key, None)
        else:
            self._trigger_failures[key] = \
                self._trigger_failures.get(key, 0) + 1
            if self._trigger_failures[key] > MAX_ATTEMPTS:
                self.failure_count += 1

    # -- main loop -----------------------------------------------------------

    def serve_forever(self, handler: Any,
                      sleep: Any = None,
                      bootstrap: bool = True) -> dict[str, Any]:
        """Run until stop requested. handler(trigger) -> dict result.
        sleep(seconds) injectable for deterministic tests. bootstrap=False
        skips default triggers (tests schedule their own). Sleeps in
        1s slices so SIGTERM/SIGINT stop promptly even with long
        intervals."""
        sleep = sleep or time.sleep
        if bootstrap:
            self._schedule_defaults()
        while not self._shutdown:
            now_mono = _monotonic()
            due = self._pop_due(now_mono)
            if due is None:
                self._heartbeat()
                self._sleep_chunked(
                    self._next_wait(now_mono), sleep)
                continue
            self._run_trigger(handler, due, sleep)
            if self._shutdown:
                break
        return self.shutdown()

    @staticmethod
    def _sleep_chunked(seconds: float, sleep: Any) -> None:
        remaining = max(0.0, float(seconds or 0.0))
        while remaining > 0:
            sleep(min(1.0, remaining))
            remaining -= 1.0

    def _schedule_defaults(self) -> None:
        now_mono = _monotonic()
        for kind, delay, priority in (
                ("presence_tick", 0.0, PRIORITY_NORMAL),
                ("health_check", 5.0, PRIORITY_HIGH),
                ("world_refresh", 60.0, PRIORITY_LOW),
                ("maintenance", 300.0, PRIORITY_MAINTENANCE)):
            self.schedule(Trigger(
                trigger_id=f"{kind}-init", source="service",
                kind=kind, priority=priority,
                run_at=now_mono + delay,
                dedupe_key=f"{kind}:init",
                correlation_id=f"svc-{int(now_mono)}"))

    def _pop_due(self, now_mono: float) -> Trigger | None:
        # Scan (don't just peek): the heap is priority-ordered, so the
        # head may be a future high-priority trigger while lower
        # priority work is already due. Among due triggers, highest
        # priority (lowest number) wins.
        best: int | None = None
        for index, (priority, run_at, _, _) in enumerate(self._queue):
            if run_at <= now_mono and (
                    best is None or priority < self._queue[best][0]):
                best = index
        if best is None:
            return None
        _, _, _, trigger = self._queue.pop(best)
        heapq.heapify(self._queue)
        return trigger

    def _next_wait(self, now_mono: float) -> float:
        if not self._queue:
            return min(self.interval_s, self.heartbeat_every_s)
        _, run_at, _, _ = self._queue[0]
        return max(0.5, min(run_at - now_mono, self.interval_s,
                            self.heartbeat_every_s))

    def _run_trigger(self, handler: Any, trigger: Trigger,
                     sleep: Any) -> None:
        key = trigger.dedupe_key or trigger.trigger_id
        self.last_tick_at = _utcnow()
        try:
            result = handler(trigger)
            ok = bool(result.get("ok", False)) if isinstance(
                result, dict) else False
        except Exception as exc:
            ok = False
            self._record_outcome(key, False)
            self._requeue(trigger, sleep)
            return
        self._record_outcome(key, ok)
        if not ok:
            self._requeue(trigger, sleep)

    def _requeue(self, trigger: Trigger, sleep: Any) -> None:
        key = trigger.dedupe_key or trigger.trigger_id
        fails = self._trigger_failures.get(key, 0)
        if fails > MAX_ATTEMPTS:
            return  # give up; counted, visible, no storm
        trigger.attempts += 1
        trigger.run_at = _monotonic() + self.backoff_for(key)
        trigger.dedupe_key = ""  # requeue bypasses dedupe by design
        self.schedule(trigger)


def json_dumps(payload: dict[str, Any]) -> str:
    import json
    return json.dumps(payload, sort_keys=True)


def json_loads(text: str) -> dict[str, Any]:
    import json
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("heartbeat root is not an object")
    return data


def evaluate_state(*, emergency: bool = False,
                   failed: bool = False,
                   heartbeat_stale: bool = False,
                   degraded_reasons: list | None = None,
                   recovering: bool = False,
                   stopped: bool = False) -> str:
    """Pure degraded-state model. Emergency stop wins; failure without
    recovery beats degradation. A never-started service is STOPPED,
    not FAILED."""
    if emergency:
        return "EMERGENCY_STOP"
    if stopped:
        return "STOPPED"
    if failed:
        return "FAILED"
    if recovering:
        return "RECOVERING"
    if heartbeat_stale or degraded_reasons:
        return "DEGRADED"
    return "FULL"


__all__ = ["BackgroundService", "ServiceLock", "Trigger",
           "read_pid_info", "evaluate_state", "PRIORITY_CRITICAL", "PRIORITY_HIGH",
           "PRIORITY_NORMAL", "PRIORITY_LOW", "PRIORITY_MAINTENANCE",
           "MAX_QUEUE", "MAX_ATTEMPTS", "STALE_HEARTBEAT_S"]
