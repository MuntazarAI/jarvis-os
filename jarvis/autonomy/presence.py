"""Background presence runtime (Autonomy 1.0).

Thin service wrapper: PID file (no duplicates, stale detection),
tick() driven by the caller (CLI/cron — no hidden threads, no
daemonization magic), graceful shutdown, bounded retries, health.
Each tick: emergency-stop check → due triggers (world refresh,
watched files) → notify via the existing Notifier/policy → telemetry
into EventStore. A trigger can observe, reason, recommend, notify, or
perform a grant-authorized low-risk action — never elevate privilege.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

PID_FILENAME = "presence.pid"
STATE_FILENAME = "presence-state.json"
DEFAULT_INTERVAL_S = 300.0
MAX_TICK_S = 120.0


def _utcnow() -> float:
    return time.time()


class PresenceRuntime:
    def __init__(self, home: str | Path | None,
                 interval_s: float = DEFAULT_INTERVAL_S) -> None:
        self.home = Path(home) if home else None
        self.interval_s = max(30.0, float(interval_s or 0.0))
        self.started_at = 0.0
        self.ticks = 0
        self.errors = 0
        self.last_tick_at = 0.0
        self._stop_requested = False
        self._seen: dict[str, float] = {}
        self._seen_loaded = False

    @property
    def pid_path(self) -> Path | None:
        if self.home is None:
            return None
        return self.home / PID_FILENAME

    @property
    def state_path(self) -> Path | None:
        if self.home is None:
            return None
        return self.home / STATE_FILENAME

    def _read_pid(self) -> int | None:
        path = self.pid_path
        if path is None or not path.exists():
            return None
        try:
            pid = int(path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None
        try:
            os.kill(pid, 0)
            return pid
        except OSError:
            return None  # stale: process gone

    def start(self) -> dict[str, Any]:
        """Claim the runtime slot. Second start fails honestly."""
        if self.home is None:
            return {"ok": False, "error": "no home"}
        running = self._read_pid()
        if running is not None:
            if running == os.getpid():
                return {"ok": True, "already": True, "pid": running}
            return {"ok": False, "error": f"already running (pid {running})"}
        path = self.pid_path
        assert path is not None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(os.getpid()), encoding="utf-8")
        except OSError as exc:
            return {"ok": False, "error": f"{type(exc).__name__}"}
        self.started_at = _utcnow()
        self._stop_requested = False
        return {"ok": True, "pid": os.getpid()}

    def request_stop(self) -> None:
        self._stop_requested = True

    def stop(self) -> dict[str, Any]:
        self._stop_requested = True
        path = self.pid_path
        if path is not None:
            try:
                if path.exists():
                    path.unlink()
            except OSError:
                pass
        return {"ok": True, "ticks": self.ticks}

    def health(self) -> dict[str, Any]:
        running = self._read_pid()
        return {"claimed": running is not None,
                "pid": running, "ticks": self.ticks,
                "errors": self.errors,
                "last_tick_at": self.last_tick_at,
                "uptime_s": round(_utcnow() - self.started_at, 1)
                if self.started_at else 0.0}

    def tick(self, jarvis: Any) -> dict[str, Any]:
        """One bounded presence pass. Never raises."""
        started = time.monotonic()
        report: dict[str, Any] = {"ok": True, "actions": [],
                                  "notifications": 0, "errors": []}
        try:
            if self._stop_requested:
                return {"ok": False, "actions": [],
                        "notifications": 0,
                        "errors": ["stop requested"]}
            if self._emergency(jarvis):
                report["actions"].append("emergency-stop: paused")
                return report
            self._tick_world(jarvis, report)
            self._tick_files(jarvis, report)
        except Exception as exc:
            self.errors += 1
            report["errors"].append(f"{type(exc).__name__}"[:120])
        finally:
            self.ticks += 1
            self.last_tick_at = _utcnow()
            elapsed = time.monotonic() - started
            report["tick_s"] = round(elapsed, 2)
            if elapsed > MAX_TICK_S:
                report["errors"].append("tick over budget")
            self._save_state(extra={
                "last_actions": [str(a)[:160] for a in
                                 report.get("actions", [])][:20]})
        return report

    def _emergency(self, jarvis: Any) -> bool:
        try:
            check = getattr(jarvis.policy, "_emergency_stop", None)
            return bool(check()) if callable(check) else False
        except Exception:
            return False

    def _tick_world(self, jarvis: Any, report: dict) -> None:
        try:
            from ..worldintel.refresh import refresh_all
            summary = refresh_all(
                str(jarvis.config.paths.home),
                interval_s=float(getattr(
                    jarvis.config.world, "refresh_interval_s",
                    3600.0)),
                notifier=lambda event: self._notify(jarvis, event),
                world_registry=getattr(jarvis, "world_registry", None),
                graph=getattr(jarvis, "graph", None))
            report["actions"].append(
                f"world: refreshed={summary.get('refreshed', 0)} "
                f"notified={summary.get('notified', 0)}")
            report["notifications"] += int(summary.get("notified", 0))
        except Exception as exc:
            report["errors"].append(f"world: {type(exc).__name__}")

    def _tick_files(self, jarvis: Any, report: dict) -> None:
        try:
            watch = list(getattr(getattr(jarvis.config, "autonomy",
                                         None),
                                 "watch_paths", []) or [])
        except Exception:
            watch = []
        seen = self._load_seen()
        changed = False
        for raw in watch[:16]:
            try:
                path = Path(str(raw)).expanduser()
                if not path.exists() or not path.is_file():
                    continue
                mtime = path.stat().st_mtime
                key = str(path)
                if seen.get(key) != mtime:
                    seen[key] = mtime
                    changed = True
                    report["actions"].append(f"file changed: {path.name}")
                    self._notify_file(jarvis, path, report)
            except OSError:
                continue
        if changed:
            self._save_seen(seen)

    def _notify_file(self, jarvis: Any, path: Path,
                     report: dict) -> None:
        try:
            from ..notify.notifications import Notification
            notifier = getattr(jarvis, "notifier", None)
            if notifier is None:
                return
            note = Notification(title="File changed",
                                message=f"{path.name} changed "
                                        "(presence watch).")
            result = notifier.deliver(note)
            if result.get("ok"):
                report["notifications"] += 1
        except Exception:
            pass

    def _notify(self, jarvis: Any, event: Any) -> Any:
        try:
            candidate = jarvis.proactive.notify(event)
            if candidate is None:
                return None
            from ..notify.notifications import Notification
            notifier = getattr(jarvis, "notifier", None)
            if notifier is None:
                return candidate
            notifier.deliver(Notification(
                title="World change",
                message=str(getattr(event, "summary", ""))[:200]))
            return candidate
        except Exception:
            return None

    def _load_seen(self) -> dict[str, float]:
        if self._seen_loaded:
            return self._seen
        self._seen_loaded = True
        path = self.state_path
        if path is None or not path.exists():
            return self._seen
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            seen = raw.get("seen", {})
            self._seen = {str(k): float(v) for k, v in seen.items()
                          if isinstance(v, (int, float))}
        except (OSError, ValueError):
            pass
        return self._seen

    def _save_seen(self, seen: dict[str, float]) -> None:
        self._save_state(extra={"seen": seen})

    def _save_state(self, extra: dict | None = None) -> None:
        path = self.state_path
        if path is None:
            return
        payload = {"ticks": self.ticks, "errors": self.errors,
                   "last_tick_at": self.last_tick_at,
                   "seen": dict(self._seen)}
        if extra:
            payload.update(extra)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, sort_keys=True),
                            encoding="utf-8")
        except OSError:
            pass


__all__ = ["PresenceRuntime", "PID_FILENAME", "DEFAULT_INTERVAL_S"]
