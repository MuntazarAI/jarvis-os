"""Durable command outbox for device control (4.2).

Every device command is a persisted record in
``<home>/device-outbox.json`` (atomic write, merge-load) with an
explicit lifecycle:

    QUEUED -> APPROVED -> DISPATCHING -> SENT -> ACKNOWLEDGED -> COMPLETED
      |          |            |             |          |
      |          |            v             v          v
      |          |        RETRYING -----> FAILED    CANCELLED
      |          |            |             |
      |          |            v             v
      |          +-----> DEAD_LETTER    EXPIRED

Cross-process safety: all mutations go through ``_mutate()``, which
holds an ``flock`` lock file across load-modify-save (POSIX; degrades
to best-effort where ``fcntl`` is unavailable). A second consumer can
never double-transition a record: terminal states are immutable and
completion is single-shot (duplicate results are detected, not applied).

Crash recovery is explicit: ``recover()`` moves stale DISPATCHING/SENT
records (older than their timeout, no ack) back to RETRYING with
``recovered: true`` — at-least-once across crashes, flagged honestly.
"""

from __future__ import annotations

import json
import os
import secrets
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ..core.types import now
from .audit import DeviceAudit
from .security import scrub

OUTBOX_FILENAME = "device-outbox.json"
OUTBOX_LOCKNAME = "device-outbox.lock"

QUEUED = "queued"
APPROVED = "approved"
DISPATCHING = "dispatching"
SENT = "sent"
ACKNOWLEDGED = "acknowledged"
COMPLETED = "completed"
FAILED = "failed"
RETRYING = "retrying"
CANCELLED = "cancelled"
EXPIRED = "expired"
DEAD_LETTER = "dead_letter"

TERMINAL = frozenset({COMPLETED, FAILED, CANCELLED, EXPIRED, DEAD_LETTER})
MAX_HISTORY = 50
DEFAULT_MAX_RETRIES = 3
DEFAULT_TIMEOUT_S = 15.0
DEFAULT_TTL_S = 300.0
BACKOFF_BASE_S = 5.0
BACKOFF_MAX_S = 120.0

try:
    import fcntl  # POSIX file locking for cross-process mutations

    @contextmanager
    def _lock_file(path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(path, "a+b")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield handle
        finally:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            handle.close()
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None  # type: ignore[assignment]

    @contextmanager
    def _lock_file(path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "ab") as handle:
            yield handle


class OutboxError(ValueError):
    """Raised for outbox misuse (unknown ids, invalid transitions)."""


def _new_command_id() -> str:
    return "cmd-" + secrets.token_hex(8)


class CommandOutbox:
    """Persistent, bounded, crash-recovering command queue."""

    def __init__(self, home: str | Path | None,
                 audit: DeviceAudit | None = None) -> None:
        self.home = Path(home) if home else None
        self.audit = audit or DeviceAudit(home)
        self._commands: dict[str, dict[str, Any]] = {}
        self._loaded_mtime: float = 0.0
        self.load()

    # -- persistence -----------------------------------------------------

    @property
    def path(self) -> Path | None:
        if self.home is None:
            return None
        return self.home / OUTBOX_FILENAME

    @property
    def lock_path(self) -> Path | None:
        if self.home is None:
            return None
        return self.home / OUTBOX_LOCKNAME

    def load(self) -> int:
        path = self.path
        self._loaded_mtime = 0.0
        if path is None or not path.exists():
            return 0
        try:
            self._loaded_mtime = path.stat().st_mtime
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return 0
        if not isinstance(raw, dict):
            return 0
        loaded = 0
        for cid, item in (raw.get("commands") or {}).items():
            if isinstance(item, dict) and item.get("command_id") == cid:
                self._commands[str(cid)] = item
                loaded += 1
        return loaded

    def _write_unlocked(self) -> None:
        path = self.path
        if path is None:
            return
        payload = {"version": 1, "commands": self._commands}
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".device-outbox-",
                                   dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True,
                          default=str)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        try:
            self._loaded_mtime = path.stat().st_mtime
        except OSError:
            pass

    @contextmanager
    def _mutate(self):
        """Lock, reload, yield self, persist. Cross-process atomic."""
        if fcntl is None or self.lock_path is None:
            self.load()
            yield self
            try:
                self._write_unlocked()
            except OSError:
                pass
            return
        lock = self.lock_path
        try:
            lock.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        with _lock_file(lock):
            self.load()
            yield self
            try:
                self._write_unlocked()
            except OSError:
                pass

    def _maybe_reload(self) -> None:
        path = self.path
        if path is None:
            return
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return
        if mtime != self._loaded_mtime:
            self.load()

    # -- lifecycle ---------------------------------------------------------

    def _stamp(self, record: dict[str, Any], event: str,
               detail: str = "") -> None:
        record["updated_at"] = now()
        history = record.setdefault("history", [])
        history.append({"at": record["updated_at"], "event": event,
                        "detail": detail[:200]})
        del history[:-MAX_HISTORY]

    def enqueue(self, device_id: str, capability: str, command: str,
                args: dict[str, Any] | None = None, *, actor: str = "",
                approval_id: str = "",
                max_retries: int = DEFAULT_MAX_RETRIES,
                timeout_s: float = DEFAULT_TIMEOUT_S,
                ttl_s: float = DEFAULT_TTL_S,
                dedupe_key: str = "") -> dict[str, Any]:
        """Persist a QUEUED command. Same dedupe_key + live record reuses it."""
        if not device_id or not capability or not command:
            raise OutboxError("device_id, capability and command are required")
        with self._mutate():
            stamp = now()
            if dedupe_key:
                for record in self._commands.values():
                    if (record.get("dedupe_key") == dedupe_key
                            and record.get("state") not in TERMINAL):
                        return dict(record)
            record = {
                "command_id": _new_command_id(),
                "dedupe_key": dedupe_key,
                "device_id": device_id,
                "capability": capability,
                "command": command,
                "args": scrub(dict(args or {})),
                "actor": actor,
                "approval_id": approval_id,
                "state": QUEUED,
                "retries": 0,
                "max_retries": max(0, int(max_retries)),
                "created_at": stamp,
                "updated_at": stamp,
                "next_attempt_at": stamp,
                "timeout_s": float(timeout_s or DEFAULT_TIMEOUT_S),
                "expires_at": (stamp + ttl_s) if ttl_s and ttl_s > 0 else 0.0,
                "result": None,
                "error": "",
                "history": [{"at": stamp, "event": "queued",
                             "detail": f"actor={actor}"[:200]}],
            }
            self._commands[record["command_id"]] = record
            self.audit.record("device.command.queued", actor=actor,
                              device_id=device_id, ok=True,
                              extra={"command_id": record["command_id"],
                                     "capability": capability})
            return dict(record)

    def get(self, command_id: str) -> dict[str, Any] | None:
        self._maybe_reload()
        record = self._commands.get(command_id)
        return dict(record) if record is not None else None

    def transition(self, command_id: str, to: str, *,
                   detail: str = "") -> dict[str, Any]:
        """Move a record to a new state. Terminal states are immutable."""
        with self._mutate():
            record = self._commands.get(command_id)
            if record is None:
                raise OutboxError(f"unknown command: {command_id}")
            if record.get("state") in TERMINAL:
                raise OutboxError(
                    f"command {command_id} is terminal "
                    f"({record.get('state')})")
            record["state"] = to
            self._stamp(record, to, detail)
            return dict(record)

    def cancel(self, command_id: str, *, by: str = "",
               reason: str = "") -> dict[str, Any]:
        """Cancel a live command. Terminal records stay untouched."""
        with self._mutate():
            record = self._commands.get(command_id)
            if record is None:
                raise OutboxError(f"unknown command: {command_id}")
            if record.get("state") in TERMINAL:
                return dict(record)
            record["state"] = CANCELLED
            self._stamp(record, "cancelled",
                        f"by={by} {reason}"[:200])
            self.audit.record("device.command.cancelled", actor=by,
                              device_id=str(record.get("device_id", "")),
                              ok=True, reasons=[reason[:200]] if reason else [],
                              extra={"command_id": command_id})
            return dict(record)

    def complete(self, command_id: str, result: Any) -> tuple[bool, str]:
        """Single-shot completion. Duplicates are detected, not applied."""
        with self._mutate():
            record = self._commands.get(command_id)
            if record is None:
                return False, "unknown command"
            if record.get("state") == COMPLETED:
                return False, "already completed (duplicate ignored)"
            if record.get("state") in TERMINAL:
                return False, f"terminal ({record.get('state')})"
            record["state"] = COMPLETED
            record["result"] = result
            self._stamp(record, "completed")
            self.audit.record("device.command.completed", actor="drainer",
                              device_id=str(record.get("device_id", "")),
                              ok=True,
                              extra={"command_id": command_id})
            return True, "completed"

    def fail(self, command_id: str, error: str, *,
             retryable: bool = True) -> dict[str, Any]:
        """Record failure; retry (bounded, backoff) or dead-letter."""
        with self._mutate():
            record = self._commands.get(command_id)
            if record is None:
                raise OutboxError(f"unknown command: {command_id}")
            if record.get("state") in TERMINAL:
                return dict(record)
            record["error"] = str(error)[:500]
            record["retries"] = int(record.get("retries", 0)) + 1
            if retryable and record["retries"] <= int(record.get(
                    "max_retries", DEFAULT_MAX_RETRIES)):
                record["state"] = RETRYING
                delay = min(BACKOFF_BASE_S * (2 ** (record["retries"] - 1)),
                            BACKOFF_MAX_S)
                record["next_attempt_at"] = now() + delay
                self._stamp(record, "retrying",
                            f"attempt={record['retries']} in={delay:.0f}s")
            elif retryable:
                record["state"] = DEAD_LETTER
                self._stamp(record, "dead_letter", "retries exhausted")
                self.audit.record("device.command.dead_letter", actor="drainer",
                                  device_id=str(record.get("device_id", "")),
                                  ok=False, reasons=[str(error)[:200]],
                                  extra={"command_id": command_id})
            else:
                record["state"] = FAILED
                self._stamp(record, "failed", str(error)[:200])
                self.audit.record("device.command.failed", actor="drainer",
                                  device_id=str(record.get("device_id", "")),
                                  ok=False, reasons=[str(error)[:200]],
                                  extra={"command_id": command_id})
            return dict(record)

    def claim_due(self, at: float = 0.0) -> list[dict[str, Any]]:
        """Records ready to dispatch: QUEUED/APPROVED/RETRYING-due,
        non-expired, no deferred wait outstanding. Callers transition
        CLAIMED records to DISPATCHING."""
        self._maybe_reload()
        stamp = at or now()
        due: list[dict[str, Any]] = []
        for record in self._commands.values():
            state = record.get("state")
            if state not in (QUEUED, APPROVED, RETRYING):
                continue
            expires = float(record.get("expires_at") or 0.0)
            if expires and stamp >= expires:
                continue  # swept to EXPIRED by sweep()
            if float(record.get("next_attempt_at") or 0.0) > stamp:
                continue
            due.append(dict(record))
        due.sort(key=lambda r: (float(r.get("created_at") or 0.0)))
        return due

    def defer(self, command_id: str, delay_s: float,
              *, detail: str = "") -> dict[str, Any]:
        """Postpone a live record without changing its state."""
        with self._mutate():
            record = self._commands.get(command_id)
            if record is None:
                raise OutboxError(f"unknown command: {command_id}")
            if record.get("state") in TERMINAL:
                return dict(record)
            record["next_attempt_at"] = now() + max(0.0, float(delay_s))
            self._stamp(record, "deferred", detail)
            return dict(record)

    def sweep(self, at: float = 0.0) -> dict[str, int]:
        """Expire TTL-passed live records. Returns {expired: n}."""
        stamp = at or now()
        expired = 0
        with self._mutate():
            for record in self._commands.values():
                if record.get("state") in TERMINAL:
                    continue
                expires = float(record.get("expires_at") or 0.0)
                if expires and stamp >= expires:
                    record["state"] = EXPIRED
                    self._stamp(record, "expired")
                    self.audit.record("device.command.expired", actor="sweep",
                                      device_id=str(record.get("device_id", "")),
                                      ok=False, reasons=["ttl exceeded"],
                                      extra={"command_id": str(record.get("command_id", ""))})
                    expired += 1
        return {"expired": expired}

    def recover(self, at: float = 0.0) -> dict[str, int]:
        """Crash recovery: stale DISPATCHING/SENT (past timeout, no ack)
        go back to RETRYING with recovered=true (or FAILED when the
        retry budget is spent). Explicit at-least-once, flagged honestly."""
        stamp = at or now()
        recovered = 0
        with self._mutate():
            for record in self._commands.values():
                if record.get("state") not in (DISPATCHING, SENT):
                    continue
                updated = float(record.get("updated_at") or 0.0)
                timeout = float(record.get("timeout_s") or DEFAULT_TIMEOUT_S)
                if stamp - updated < timeout:
                    continue
                record["retries"] = int(record.get("retries", 0)) + 1
                record["recovered"] = True
                if record["retries"] <= int(record.get(
                        "max_retries", DEFAULT_MAX_RETRIES)):
                    record["state"] = RETRYING
                    delay = min(BACKOFF_BASE_S * (2 ** (record["retries"] - 1)),
                                BACKOFF_MAX_S)
                    record["next_attempt_at"] = stamp + delay
                    self._stamp(record, "recovered",
                                f"attempt={record['retries']}")
                else:
                    record["state"] = FAILED
                    record["error"] = "unacknowledged after crash recovery"
                    self._stamp(record, "failed", "recovery budget spent")
                recovered += 1
        return {"recovered": recovered}

    def depth(self) -> dict[str, Any]:
        self._maybe_reload()
        by_state: dict[str, int] = {}
        for record in self._commands.values():
            by_state[record.get("state", "?")] = by_state.get(
                record.get("state", "?"), 0) + 1
        return {"total": len(self._commands), "by_state": by_state}

    def prune_terminal(self, keep: int = 200) -> int:
        """Drop oldest terminal records beyond `keep`. Returns count dropped."""
        with self._mutate():
            terminal = sorted(
                (r for r in self._commands.values()
                 if r.get("state") in TERMINAL),
                key=lambda r: float(r.get("updated_at") or 0.0))
            drop = terminal[:max(0, len(terminal) - keep)]
            for record in drop:
                del self._commands[record["command_id"]]
            return len(drop)


__all__ = [
    "CommandOutbox",
    "OutboxError",
    "QUEUED",
    "APPROVED",
    "DISPATCHING",
    "SENT",
    "ACKNOWLEDGED",
    "COMPLETED",
    "FAILED",
    "RETRYING",
    "CANCELLED",
    "EXPIRED",
    "DEAD_LETTER",
]
