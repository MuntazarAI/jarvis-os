"""
Autonomous Agent Loop - Core Loop Infrastructure

Implements the observe → plan → act → reflect cycle with persistent checkpointing,
task queue management, and crash recovery.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
import uuid
import logging
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set
from threading import Lock

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """Task execution status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"


class TaskPriority(Enum):
    """Task priority levels."""
    LOW = 0
    NORMAL = 50
    HIGH = 100
    CRITICAL = 200


@dataclass
class LoopTask:
    """A task in the autonomous loop."""
    task_id: str
    name: str
    description: str
    agent_id: str
    payload: Dict[str, Any]
    priority: TaskPriority = TaskPriority.NORMAL
    status: TaskStatus = TaskStatus.PENDING
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    retries: int = 0
    max_retries: int = 3
    retry_delay: float = 1.0
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        d["priority"] = self.priority.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LoopTask":
        data = data.copy()
        data["status"] = TaskStatus(data["status"])
        data["priority"] = TaskPriority(data["priority"])
        return cls(**data)


@dataclass
class LoopCheckpoint:
    """Checkpoint for crash recovery."""
    checkpoint_id: str
    iteration: int
    timestamp: float
    loop_state: Dict[str, Any]
    pending_tasks: List[Dict[str, Any]]
    running_tasks: List[Dict[str, Any]]
    completed_count: int
    failed_count: int
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, data: str) -> "LoopCheckpoint":
        return cls(**json.loads(data))


class TaskQueue:
    """Persistent task queue with priority ordering and dead-letter handling."""

    def __init__(self, db_path: str = "jarvis_loop_queue.db"):
        self.db_path = db_path
        self._lock = Lock()
        self._init_db()

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    agent_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    priority INTEGER DEFAULT 50,
                    status TEXT DEFAULT 'pending',
                    created_at REAL NOT NULL,
                    started_at REAL,
                    completed_at REAL,
                    retries INTEGER DEFAULT 0,
                    max_retries INTEGER DEFAULT 3,
                    retry_delay REAL DEFAULT 1.0,
                    result TEXT,
                    error TEXT,
                    metadata TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_status_priority
                ON tasks(status, priority DESC, created_at)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS checkpoints (
                    checkpoint_id TEXT PRIMARY KEY,
                    iteration INTEGER NOT NULL,
                    timestamp REAL NOT NULL,
                    loop_state TEXT NOT NULL,
                    pending_tasks TEXT NOT NULL,
                    running_tasks TEXT NOT NULL,
                    completed_count INTEGER DEFAULT 0,
                    failed_count INTEGER DEFAULT 0,
                    metadata TEXT
                )
            """)
            conn.commit()

    @contextmanager
    def _get_conn(self):
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def enqueue(self, task: LoopTask) -> str:
        """Add task to queue."""
        with self._lock, self._get_conn() as conn:
            conn.execute("""
                INSERT INTO tasks (task_id, name, description, agent_id, payload,
                                 priority, status, created_at, max_retries, retry_delay, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                task.task_id, task.name, task.description, task.agent_id,
                json.dumps(task.payload), task.priority.value, task.status.value,
                task.created_at, task.max_retries, task.retry_delay,
                json.dumps(task.metadata)
            ))
            conn.commit()
        logger.info(f"Enqueued task {task.task_id}: {task.name}")
        return task.task_id

    def dequeue(self, agent_id: Optional[str] = None, limit: int = 1) -> List[LoopTask]:
        """Get next pending tasks, optionally filtered by agent."""
        with self._lock, self._get_conn() as conn:
            query = """
                SELECT * FROM tasks
                WHERE status = 'pending'
            """
            params = []
            if agent_id:
                query += " AND agent_id = ?"
                params.append(agent_id)
            query += " ORDER BY priority DESC, created_at LIMIT ?"
            params.append(limit)

            rows = conn.execute(query, params).fetchall()
            tasks = []
            for row in rows:
                task = self._row_to_task(row)
                task.status = TaskStatus.RUNNING
                task.started_at = time.time()
                self._update_task(conn, task)
                tasks.append(task)
            conn.commit()
            return tasks

    def _row_to_task(self, row: sqlite3.Row) -> LoopTask:
        return LoopTask(
            task_id=row["task_id"],
            name=row["name"],
            description=row["description"],
            agent_id=row["agent_id"],
            payload=json.loads(row["payload"]),
            priority=TaskPriority(row["priority"]),
            status=TaskStatus(row["status"]),
            created_at=row["created_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            retries=row["retries"],
            max_retries=row["max_retries"],
            retry_delay=row["retry_delay"],
            result=json.loads(row["result"]) if row["result"] else None,
            error=row["error"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {}
        )

    def _update_task(self, conn: sqlite3.Connection, task: LoopTask):
        conn.execute("""
            UPDATE tasks SET status=?, started_at=?, completed_at=?,
                           retries=?, result=?, error=?, metadata=?
            WHERE task_id=?
        """, (
            task.status.value, task.started_at, task.completed_at,
            task.retries, json.dumps(task.result) if task.result else None,
            task.error, json.dumps(task.metadata), task.task_id
        ))

    def complete(self, task_id: str, result: Dict[str, Any]):
        """Mark task as completed."""
        with self._lock, self._get_conn() as conn:
            task = self._get_task(conn, task_id)
            if task:
                task.status = TaskStatus.COMPLETED
                task.completed_at = time.time()
                task.result = result
                self._update_task(conn, task)
                conn.commit()
                logger.info(f"Completed task {task_id}")

    def fail(self, task_id: str, error: str):
        """Mark task as failed, handle retry logic."""
        with self._lock, self._get_conn() as conn:
            task = self._get_task(conn, task_id)
            if not task:
                return

            task.retries += 1
            task.error = error

            if task.retries >= task.max_retries:
                task.status = TaskStatus.DEAD_LETTER
                task.completed_at = time.time()
                logger.error(f"Task {task_id} moved to dead letter after {task.retries} retries: {error}")
            else:
                task.status = TaskStatus.PENDING
                task.started_at = None
                # Exponential backoff
                task.retry_delay *= 2
                logger.warning(f"Task {task_id} failed (attempt {task.retries}/{task.max_retries}): {error}. Retrying in {task.retry_delay}s")

            self._update_task(conn, task)
            conn.commit()

    def _get_task(self, conn: sqlite3.Connection, task_id: str) -> Optional[LoopTask]:
        row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        return self._row_to_task(row) if row else None

    def get_status(self, task_id: str) -> Optional[TaskStatus]:
        with self._get_conn() as conn:
            row = conn.execute("SELECT status FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            return TaskStatus(row["status"]) if row else None

    def get_stats(self) -> Dict[str, int]:
        with self._get_conn() as conn:
            stats = {}
            for status in TaskStatus:
                count = conn.execute(
                    "SELECT COUNT(*) FROM tasks WHERE status = ?", (status.value,)
                ).fetchone()[0]
                stats[status.value] = count
            return stats

    def get_dead_letter(self, limit: int = 100) -> List[LoopTask]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (TaskStatus.DEAD_LETTER.value, limit)
            ).fetchall()
            return [self._row_to_task(r) for r in rows]


class LoopController:
    """Controls the autonomous loop lifecycle."""

    def __init__(self, queue: TaskQueue, checkpoint_dir: str = "checkpoints"):
        self.queue = queue
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(exist_ok=True)

        self._running = False
        self._paused = False
        self._iteration = 0
        self._completed = 0
        self._failed = 0
        self._start_time: Optional[float] = None
        self._loop_task: Optional[asyncio.Task] = None
        self._checkpoint_interval = 10  # checkpoint every N iterations
        self._max_iterations: Optional[int] = None
        self._iteration_timeout = 60.0  # seconds per iteration

        # Callbacks for observe/plan/act/reflect
        self.observe_fn: Optional[Callable] = None
        self.plan_fn: Optional[Callable] = None
        self.act_fn: Optional[Callable] = None
        self.reflect_fn: Optional[Callable] = None

    def set_callbacks(self,
                      observe: Callable,
                      plan: Callable,
                      act: Callable,
                      reflect: Callable):
        self.observe_fn = observe
        self.plan_fn = plan
        self.act_fn = act
        self.reflect_fn = reflect

    def configure(self,
                  checkpoint_interval: int = 10,
                  max_iterations: Optional[int] = None,
                  iteration_timeout: float = 60.0):
        self._checkpoint_interval = checkpoint_interval
        self._max_iterations = max_iterations
        self._iteration_timeout = iteration_timeout

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def iteration(self) -> int:
        return self._iteration

    @property
    def stats(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "paused": self._paused,
            "iteration": self._iteration,
            "completed": self._completed,
            "failed": self._failed,
            "uptime_seconds": time.time() - self._start_time if self._start_time else 0,
            "queue_stats": self.queue.get_stats()
        }

    async def start(self):
        """Start the autonomous loop."""
        if self._running:
            logger.warning("Loop already running")
            return

        if not all([self.observe_fn, self.plan_fn, self.act_fn, self.reflect_fn]):
            raise ValueError("All callbacks (observe, plan, act, reflect) must be set")

        self._running = True
        self._paused = False
        self._iteration = 0
        self._completed = 0
        self._failed = 0
        self._start_time = time.time()

        self._loop_task = asyncio.create_task(self._run_loop())
        logger.info("Autonomous loop started")

    async def stop(self, graceful: bool = True):
        """Stop the autonomous loop."""
        if not self._running:
            return

        self._running = False

        if self._loop_task:
            if graceful:
                # Wait for current iteration to complete
                try:
                    await asyncio.wait_for(self._loop_task, timeout=30.0)
                except asyncio.TimeoutError:
                    logger.warning("Loop didn't stop gracefully, cancelling")
                    self._loop_task.cancel()
            else:
                self._loop_task.cancel()

            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass

        # Final checkpoint
        await self._checkpoint()
        logger.info("Autonomous loop stopped")

    async def pause(self):
        """Pause the loop (finish current iteration)."""
        self._paused = True
        logger.info("Loop paused")

    async def resume(self):
        """Resume the loop."""
        self._paused = False
        logger.info("Loop resumed")

    def configure(self,
                  checkpoint_interval: int = 10,
                  max_iterations: Optional[int] = None,
                  iteration_timeout: float = 60.0,
                  min_iteration_interval: float = 0.1,
                  paused_sleep_interval: float = 0.1):
        self._checkpoint_interval = checkpoint_interval
        self._max_iterations = max_iterations
        self._iteration_timeout = iteration_timeout
        self._min_iteration_interval = min_iteration_interval
        self._paused_sleep_interval = paused_sleep_interval

    async def _run_loop(self):
        """Main loop: observe → plan → act → reflect."""
        logger.info(f"Loop starting, max_iterations={self._max_iterations}")
        while self._running:
            if self._paused:
                await asyncio.sleep(self._paused_sleep_interval)
                continue

            if self._max_iterations and self._iteration >= self._max_iterations:
                logger.info(f"Reached max iterations ({self._max_iterations})")
                break

            iteration_start = time.time()
            self._iteration += 1
            logger.debug(f"Starting iteration {self._iteration}")

            try:
                # Run iteration with timeout
                await asyncio.wait_for(
                    self._run_iteration(),
                    timeout=self._iteration_timeout
                )
                logger.debug(f"Completed iteration {self._iteration}")

                # Checkpoint periodically
                if self._iteration % self._checkpoint_interval == 0:
                    await self._checkpoint()

            except asyncio.TimeoutError:
                logger.error(f"Iteration {self._iteration} timed out after {self._iteration_timeout}s")
                self._failed += 1
            except Exception as e:
                logger.exception(f"Iteration {self._iteration} failed: {e}")
                self._failed += 1

            # Small delay between iterations (configurable, default 0.1s for responsiveness)
            elapsed = time.time() - iteration_start
            min_interval = getattr(self, '_min_iteration_interval', 0.1)
            if elapsed < min_interval:
                await asyncio.sleep(min_interval - elapsed)

        logger.info(f"Loop stopped, iterations={self._iteration}, completed={self._completed}, failed={self._failed}")

    async def _run_iteration(self):
        """Single observe → plan → act → reflect cycle."""
        iteration = self._iteration

        # 1. OBSERVE
        logger.debug(f"Iteration {iteration}: Observe")
        observation = await self._safe_call(self.observe_fn, iteration)

        # 2. PLAN
        logger.debug(f"Iteration {iteration}: Plan")
        plan = await self._safe_call(self.plan_fn, iteration, observation)

        # 3. ACT
        logger.debug(f"Iteration {iteration}: Act")
        action_result = await self._safe_call(self.act_fn, iteration, plan)

        # 4. REFLECT
        logger.debug(f"Iteration {iteration}: Reflect")
        reflection = await self._safe_call(self.reflect_fn, iteration, action_result)

        self._completed += 1

    async def _safe_call(self, fn: Callable, *args) -> Any:
        """Call async or sync function safely."""
        if asyncio.iscoroutinefunction(fn):
            return await fn(*args)
        else:
            return fn(*args)

    async def _checkpoint(self):
        """Save checkpoint for crash recovery."""
        checkpoint = LoopCheckpoint(
            checkpoint_id=str(uuid.uuid4()),
            iteration=self._iteration,
            timestamp=time.time(),
            loop_state={
                "running": self._running,
                "paused": self._paused,
                "iteration": self._iteration,
                "completed": self._completed,
                "failed": self._failed,
                "start_time": self._start_time,
            },
            pending_tasks=[t.to_dict() for t in self.queue.dequeue(limit=1000)],
            running_tasks=[],  # Would need tracking
            completed_count=self._completed,
            failed_count=self._failed,
            metadata={"checkpoint_interval": self._checkpoint_interval}
        )

        checkpoint_file = self.checkpoint_dir / f"checkpoint_{self._iteration}_{int(time.time())}.json"
        checkpoint_file.write_text(checkpoint.to_json())

        # Keep only last 10 checkpoints
        checkpoints = sorted(self.checkpoint_dir.glob("checkpoint_*.json"))
        for old in checkpoints[:-10]:
            old.unlink()

        logger.debug(f"Checkpoint saved: {checkpoint_file}")

    def load_latest_checkpoint(self) -> Optional[LoopCheckpoint]:
        """Load most recent checkpoint."""
        checkpoints = sorted(self.checkpoint_dir.glob("checkpoint_*.json"))
        if not checkpoints:
            return None

        latest = checkpoints[-1]
        try:
            return LoopCheckpoint.from_json(latest.read_text())
        except Exception as e:
            logger.error(f"Failed to load checkpoint {latest}: {e}")
            return None


# Global instances
_task_queue: Optional[TaskQueue] = None
_loop_controller: Optional[LoopController] = None


def get_task_queue(db_path: str = "jarvis_loop_queue.db") -> TaskQueue:
    global _task_queue
    if _task_queue is None:
        _task_queue = TaskQueue(db_path)
    return _task_queue


def get_loop_controller(queue: Optional[TaskQueue] = None,
                        checkpoint_dir: str = "checkpoints") -> LoopController:
    global _loop_controller
    if _loop_controller is None:
        q = queue or get_task_queue()
        _loop_controller = LoopController(q, checkpoint_dir)
    return _loop_controller


async def initialize_autonomous_loop(
    db_path: str = "jarvis_loop_queue.db",
    checkpoint_dir: str = "checkpoints",
    callbacks: Optional[Dict[str, Callable]] = None
) -> LoopController:
    """Initialize and optionally start the autonomous loop."""
    queue = get_task_queue(db_path)
    controller = get_loop_controller(queue, checkpoint_dir)

    if callbacks:
        controller.set_callbacks(
            observe=callbacks.get("observe"),
            plan=callbacks.get("plan"),
            act=callbacks.get("act"),
            reflect=callbacks.get("reflect")
        )

    return controller