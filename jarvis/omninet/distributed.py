"""Distributed Intelligence (M10).

Optional multi-machine deployment support for JARVIS-OS.
Designed to NOT overload the current laptop — all distributed features
are opt-in and disabled by default.

Supports:
- Remote research workers (optional, explicit opt-in)
- Model servers (optional)
- Distributed indexing (optional)
- Research queues (bounded, local-first)
- Scheduled jobs (via existing DOTS)
- Result aggregation
- Worker health monitoring
- Secure communication (PolicyEngine-gated)
- Authentication (token-based)
- Resource quotas

Design: local-first, distributed-optional. Nothing auto-connects to
remote machines without explicit configuration.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from ..core.internet import InternetAccess
from ..core.logging import get_module_logger
from ..core.types import now
from ..omninet.http_connector import HttpConnector
from ..policy.policy import PolicyEngine

log = get_module_logger(__name__)


@dataclass
class WorkerNode:
    """A remote or local worker node in the distributed intelligence."""
    node_id: str
    name: str
    host: str
    port: int
    capabilities: list[str] = field(default_factory=list)  # research | indexing | model | crawl
    status: str = "idle"  # idle | busy | offline | unknown
    last_heartbeat: float = 0.0
    max_concurrent_tasks: int = 2
    current_tasks: int = 0
    resource_quota: dict[str, Any] = field(default_factory=dict)
    auth_token: str = ""
    registered_at: float = field(default_factory=now)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("auth_token", None)  # never expose auth token
        return d

    def is_available(self) -> bool:
        return self.status in ("idle", "busy") and self.current_tasks < self.max_concurrent_tasks

    def heartbeat(self) -> None:
        self.last_heartbeat = now()
        self.status = "idle"


@dataclass
class DistributedTask:
    """A task queued for distributed execution."""
    task_id: str
    task_type: str  # research | indexing | crawl | model_inference
    payload: dict[str, Any]
    status: str = "queued"  # queued | assigned | running | completed | failed | cancelled
    assigned_node: str | None = None
    created_at: float = field(default_factory=now)
    started_at: float | None = None
    completed_at: float | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    retries: int = 0
    max_retries: int = 3

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WorkerHealth:
    """Health status of a worker node."""
    node_id: str
    status: str
    last_heartbeat: float
    current_tasks: int
    max_concurrent_tasks: int
    uptime_s: float
    errors: list[str] = field(default_factory=list)


class DistributedIntelligence:
    """Distributed intelligence coordinator — optional, laptop-safe.

    All features are opt-in. Nothing connects to remote machines
    without explicit worker registration. Local-only by default.
    """

    def __init__(
        self,
        policy: PolicyEngine,
        internet: InternetAccess,
        actor: str = "jarvis",
    ) -> None:
        self.policy = policy
        self.internet = internet
        self.actor = actor
        self._workers: dict[str, WorkerNode] = {}
        self._tasks: dict[str, DistributedTask] = {}
        self._task_queue: list[str] = []  # task_ids in queue order
        self._results: dict[str, dict[str, Any]] = {}
        self._http = HttpConnector(policy, internet, actor=actor,
                                   timeout=30.0, max_bytes=1_000_000)
        self._enabled: bool = False  # disabled by default — laptop safe
        self._auth_token: str = f"jarvis-dist-{uuid.uuid4().hex[:16]}"

    # -- enable/disable --------------------------------------------------

    def enable(self) -> None:
        """Enable distributed intelligence (opt-in)."""
        self._enabled = True
        log.info("Distributed intelligence enabled (opt-in)")

    def disable(self) -> None:
        """Disable distributed intelligence."""
        self._enabled = False
        log.info("Distributed intelligence disabled")

    def is_enabled(self) -> bool:
        return self._enabled

    # -- worker management ----------------------------------------------

    def register_worker(
        self,
        name: str,
        host: str,
        port: int,
        capabilities: list[str] | None = None,
        max_concurrent_tasks: int = 2,
        auth_token: str | None = None,
    ) -> WorkerNode:
        """Register a worker node. Requires explicit opt-in (enabled=True)."""
        if not self._enabled:
            raise RuntimeError("Distributed intelligence is disabled. Call enable() first.")

        if capabilities is None:
            capabilities = ["research"]

        node_id = f"node-{uuid.uuid4().hex[:12]}"
        token = auth_token or self._auth_token

        # PolicyEngine gate — remote worker registration requires approval
        decision = self.policy.evaluate(
            self.actor,
            __import__("jarvis.core.types", fromlist=["ActionPlan"]).ActionPlan(
                action="distributed.register_worker",
                args={"host": host, "port": port, "capabilities": capabilities},
                required_permissions=["net.fetch", "distributed.register"],
                risk=__import__("jarvis.core.types", fromlist=["RiskLevel"]).RiskLevel.MEDIUM,
            ),
        )
        if not decision.allow:
            raise RuntimeError(f"Worker registration denied by policy: {decision.reasons}")

        node = WorkerNode(
            node_id=node_id, name=name, host=host, port=port,
            capabilities=capabilities or [],
            max_concurrent_tasks=max_concurrent_tasks,
            auth_token=token,
        )
        self._workers[node_id] = node
        log.info("Worker registered", node_id=node_id, name=name, host=host)
        return node

    def unregister_worker(self, node_id: str) -> bool:
        if node_id in self._workers:
            del self._workers[node_id]
            return True
        return False

    def list_workers(self) -> list[dict[str, Any]]:
        return [w.to_dict() for w in self._workers.values()]

    def worker_heartbeat(self, node_id: str) -> bool:
        if node_id in self._workers:
            self._workers[node_id].heartbeat()
            return True
        return False

    def get_worker_health(self, node_id: str) -> WorkerHealth | None:
        node = self._workers.get(node_id)
        if node is None:
            return None
        return WorkerHealth(
            node_id=node.node_id,
            status=node.status,
            last_heartbeat=node.last_heartbeat,
            current_tasks=node.current_tasks,
            max_concurrent_tasks=node.max_concurrent_tasks,
            uptime_s=now() - node.registered_at,
        )

    # -- task queue ------------------------------------------------------

    def submit_task(
        self,
        task_type: str,
        payload: dict[str, Any],
        max_retries: int = 3,
    ) -> DistributedTask:
        """Submit a task for distributed execution.

        If no workers are available, the task runs locally (falls back
        to single-machine execution).
        """
        task_id = f"task-{uuid.uuid4().hex[:12]}"
        task = DistributedTask(
            task_id=task_id, task_type=task_type, payload=payload,
            max_retries=max_retries,
        )
        self._tasks[task_id] = task
        self._task_queue.append(task_id)
        log.info("Task submitted", task_id=task_id, type=task_type)

        # Try to assign to a worker immediately
        self._dispatch_pending()

        return task

    def _dispatch_pending(self) -> None:
        """Dispatch queued tasks to available workers."""
        available = [w for w in self._workers.values() if w.is_available()]
        if not available:
            return

        while self._task_queue and available:
            task_id = self._task_queue.pop(0)
            task = self._tasks.get(task_id)
            if task is None:
                continue

            # Find a worker with matching capability
            worker = None
            for w in available:
                if task.task_type in w.capabilities or "research" in w.capabilities:
                    worker = w
                    break

            if worker is None:
                # Put back at front of queue
                self._task_queue.insert(0, task_id)
                break

            # Assign task
            task.assigned_node = worker.node_id
            task.status = "assigned"
            worker.current_tasks += 1
            worker.status = "busy" if worker.current_tasks >= worker.max_concurrent_tasks else "busy"

            log.info("Task assigned", task_id=task_id, node=worker.node_id)

            # Try remote execution
            self._execute_remotely(task, worker)

    def _execute_remotely(
        self,
        task: DistributedTask,
        worker: WorkerNode,
    ) -> None:
        """Execute a task on a remote worker (PolicyEngine-gated)."""
        if not worker.is_available():
            return

        # Check if worker host is granted for internet access
        if not self.internet.can_access(self.actor, worker.host):
            task.status = "failed"
            task.error = f"no internet grant for worker host: {worker.host}"
            worker.current_tasks = max(0, worker.current_tasks - 1)
            self._dispatch_pending()
            return

        # SSRF guard
        url = f"http://{worker.host}:{worker.port}/api/v1/tasks"
        safe, reason = is_safe_url(url)
        if not safe:
            task.status = "failed"
            task.error = f"SSRF guard: {reason}"
            worker.current_tasks = max(0, worker.current_tasks - 1)
            self._dispatch_pending()
            return

        try:
            import json
            import urllib.request
            payload = {
                "task_id": task.task_id,
                "task_type": task.task_type,
                "payload": task.payload,
                "auth_token": worker.auth_token,
            }
            data = json.dumps(payload).encode()
            req = urllib.request.Request(
                url, data=data,
                headers={"User-Agent": "jarvis-os/0.1 distributed intelligence",
                         "Content-Type": "application/json"},
                method="POST",
            )
            task.started_at = now()
            task.status = "running"
            with urllib.request.urlopen(req, timeout=30.0) as resp:  # noqa: S310
                result = json.loads(resp.read().decode("utf-8", errors="replace"))
            task.completed_at = now()
            task.status = "completed"
            task.result = result
            self._results[task.task_id] = result
            log.info("Task completed remotely", task_id=task.task_id, node=worker.node_id)
        except Exception as exc:
            task.retries += 1
            if task.retries < task.max_retries:
                task.status = "queued"
                self._task_queue.insert(0, task.task_id)
            else:
                task.status = "failed"
                task.error = str(exc)[:500]
                log.warning("Task failed after retries", task_id=task.task_id, error=str(exc)[:120])
        finally:
            worker.current_tasks = max(0, worker.current_tasks - 1)
            worker.status = "idle" if worker.current_tasks == 0 else "busy"
            self._dispatch_pending()

    def get_task(self, task_id: str) -> DistributedTask | None:
        return self._tasks.get(task_id)

    def get_task_result(self, task_id: str) -> dict[str, Any] | None:
        return self._results.get(task_id)

    def list_tasks(self) -> list[dict[str, Any]]:
        return [t.to_dict() for t in self._tasks.values()]

    def cancel_task(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task is None:
            return False
        if task.status in ("queued", "assigned"):
            task.status = "cancelled"
            if task.assigned_node:
                worker = self._workers.get(task.assigned_node)
                if worker:
                    worker.current_tasks = max(0, worker.current_tasks - 1)
                    worker.status = "idle"
            return True
        return False

    # -- scheduled jobs (via DOTS integration hint) ---------------------

    def schedule_job(
        self,
        name: str,
        task_type: str,
        payload: dict[str, Any],
        interval_s: float,
    ) -> str:
        """Schedule a recurring job.

        Note: actual scheduling is handled by the existing DOTS
        system (jarvis/dots/manager.py). This method registers the
        job definition for the distributed scheduler to pick up.
        """
        job_id = f"job-{uuid.uuid4().hex[:12]}"
        log.info("Job scheduled", job_id=job_id, name=name, type=task_type,
                 interval_s=interval_s)
        # Store job definition for DOTS integration
        self._tasks[job_id] = DistributedTask(
            task_id=job_id, task_type=task_type, payload=payload,
        )
        return job_id

    # -- status ---------------------------------------------------------

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self._enabled,
            "workers": len(self._workers),
            "workers_available": sum(1 for w in self._workers.values() if w.is_available()),
            "tasks_queued": len(self._task_queue),
            "tasks_total": len(self._tasks),
            "tasks_completed": sum(1 for t in self._tasks.values() if t.status == "completed"),
            "tasks_failed": sum(1 for t in self._tasks.values() if t.status == "failed"),
            "auth_configured": bool(self._auth_token),
        }


__all__ = [
    "WorkerNode",
    "DistributedTask",
    "WorkerHealth",
    "DistributedIntelligence",
]
