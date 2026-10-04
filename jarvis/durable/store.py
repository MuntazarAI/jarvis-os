"""Durable task store (Durable Autonomous Tasks 1.0).

One atomic JSON file (`durable-tasks.json`) with schema versioning,
mtime reload for cross-process visibility, per-mutation file locking
(reusing the fcntl pattern from policy), and fail-closed loading:
corrupt or unknown-version data never parses into authority.

Distinction kept: this file is AUTHORITATIVE TASK STATE. EventStore
holds event history, tracing holds diagnostics, logs hold text.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from .task import SCHEMA_VERSION, Task, TaskError

STORE_FILENAME = "durable-tasks.json"
MAX_TASKS = 200


class TaskStoreError(RuntimeError):
    """Store-level failure (not a task validation error)."""


class TaskStore:
    def __init__(self, home: str | Path | None,
                 max_tasks: int = MAX_TASKS) -> None:
        self.home = Path(home) if home else None
        self.max_tasks = max(1, int(max_tasks))
        self._tasks: dict[str, Task] = {}
        self._loaded_mtime: float = 0.0
        self.corrupt: str = ""
        self.load()

    @property
    def path(self) -> Path | None:
        if self.home is None:
            return None
        return self.home / STORE_FILENAME

    def _lock_path(self) -> Path | None:
        path = self.path
        return path.with_name(path.name + ".lock") if path else None

    @staticmethod
    @contextlib.contextmanager
    def _locked(path: Path | None):
        if path is None:
            yield
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        try:
            import fcntl
        except ImportError:
            yield
            return
        try:
            with open(path, "a+b") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    try:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                    except OSError:
                        pass
        except OSError:
            yield

    def load(self) -> int:
        path = self.path
        self._tasks = {}
        self.corrupt = ""
        self._loaded_mtime = 0.0
        if path is None or not path.exists():
            return 0
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            self.corrupt = f"{type(exc).__name__}"
            return 0
        if not isinstance(raw, dict):
            self.corrupt = "root not an object"
            return 0
        version = raw.get("version", 0)
        if version != SCHEMA_VERSION:
            self.corrupt = f"unsupported version {version}"
            return 0
        loaded = 0
        for tid, item in (raw.get("tasks") or {}).items():
            if not isinstance(item, dict):
                continue
            try:
                task = Task(
                    task_id=str(tid),
                    version=int(item.get("version", SCHEMA_VERSION)),
                    created_at=float(item.get("created_at", 0.0) or 0.0),
                    updated_at=float(item.get("updated_at", 0.0) or 0.0),
                    title=str(item.get("title", "")),
                    source=str(item.get("source", "")),
                    priority=int(item.get("priority", 5)),
                    state=str(item.get("state", "created")),
                    deadline=float(item.get("deadline", 0.0) or 0.0),
                    cancel_requested=bool(
                        item.get("cancel_requested", False)),
                    retry_policy=item.get("retry_policy") or {},
                    plan_ref=str(item.get("plan_ref", "")),
                    plan_version=str(item.get("plan_version", "")),
                    current_step=str(item.get("current_step", "")),
                    steps=item.get("steps") or [],
                    checkpoints=item.get("checkpoints") or [],
                    dependencies=[str(d) for d in
                                  (item.get("dependencies") or [])],
                    provenance=item.get("provenance") or {})
            except (TaskError, ValueError, TypeError):
                continue  # one bad record never poisons the store
            if task.task_id == tid:
                self._tasks[tid] = task
                loaded += 1
        try:
            self._loaded_mtime = path.stat().st_mtime
        except OSError:
            pass
        return loaded

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

    def save(self) -> None:
        path = self.path
        if path is None:
            return
        payload = {"version": SCHEMA_VERSION,
                   "tasks": {tid: task.to_dict() for tid, task in
                             list(self._tasks.items())[:self.max_tasks]}}
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".durable-tasks-",
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
        except OSError as exc:
            raise TaskStoreError(f"save failed: {exc}")

    def mutate(self, task_id: str):
        """Lock, reload, yield live task, persist. Cross-process atomic."""
        store = self

        @contextlib.contextmanager
        def _guard():
            with store._locked(store._lock_path()):
                store._maybe_reload()
                task = store._tasks.get(task_id)
                if task is None:
                    raise TaskStoreError(f"unknown task: {task_id}")
                yield task
                task.updated_at = time.time()
                store.save()
        return _guard()

    def create(self, task: Task) -> Task:
        with self._locked(self._lock_path()):
            self._maybe_reload()
            if len(self._tasks) >= self.max_tasks:
                raise TaskStoreError("task registry full")
            if task.task_id in self._tasks:
                raise TaskStoreError("duplicate task id")
            self._tasks[task.task_id] = task
            self.save()
            return task

    def get(self, task_id: str) -> Task | None:
        self._maybe_reload()
        return self._tasks.get(str(task_id or ""))

    def list(self, state: str = "") -> list[Task]:
        self._maybe_reload()
        tasks = sorted(self._tasks.values(),
                       key=lambda t: t.created_at)
        if state:
            tasks = [t for t in tasks if t.state.value == state]
        return tasks

    def remove(self, task_id: str) -> bool:
        with self._locked(self._lock_path()):
            self._maybe_reload()
            if task_id not in self._tasks:
                return False
            del self._tasks[task_id]
            self.save()
            return True


__all__ = ["TaskStore", "TaskStoreError", "STORE_FILENAME"]
