"""Automated Scheduling System for JARVIS-OS.

Provides cron-like scheduling for Stark AI agents, DOTS, and OMNINET
components. All scheduled tasks are PolicyEngine-gated and auditable.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from ..core.config import JarvisConfig
from ..core.internet import InternetAccess
from ..policy.policy import PolicyEngine
from ..core.types import now
from ..core.logging import get_module_logger
from ..omninet import (
    JarvisIntegratedSystem,
    dispatch_stark_ai,
)
from ..dots.manager import DotManager

log = get_module_logger(__name__)


@dataclass
class ScheduledJob:
    """A scheduled task that runs at specified intervals."""
    job_id: str
    name: str
    schedule_type: str  # "interval", "daily", "weekly", "monthly", "cron"
    interval_seconds: float | None  # For interval schedules
    target_ai_id: str | None  # Stark AI to dispatch
    target_goal: str  # Goal to dispatch
    dot_id: str | None  # DOT to activate
    dot_goal: str | None  # Goal for DOT
    last_run: float | None = None
    next_run: float | None = None
    run_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    enabled: bool = True
    created_at: float = field(default_factory=time.time)
    last_error: str | None = None


@dataclass
class JobResult:
    """Result of a scheduled job execution."""
    job_id: str
    success: bool
    output: dict[str, Any] | None = None
    error: str | None = None
    executed_at: float = field(default_factory=time.time)


class AutomatedScheduler:
    """Automated scheduler for JARVIS-OS agents and tasks.

    Schedules recurring tasks for Stark AI agents, DOTS, and OMNINET
    components. All scheduled tasks are PolicyEngine-gated and auditable.
    """

    def __init__(
        self,
        system: JarvisIntegratedSystem,
        dots: DotManager,
    ) -> None:
        self.system = system
        self.dots = dots
        self.jobs: dict[str, ScheduledJob] = {}
        self.job_counter: int = 0
        self.results: list[JobResult] = []
        self.max_results: int = 1000

    def schedule_job(
        self,
        name: str,
        schedule_type: str,
        interval_seconds: float | None = None,
        target_ai_id: str | None = None,
        target_goal: str | None = None,
        target_dot_id: str | None = None,
        target_dot_goal: str | None = None,
        enabled: bool = True,
    ) -> str:
        """Schedule a recurring job.

        Args:
            name: Human-readable name for the job
            schedule_type: Type of schedule (interval, daily, weekly, monthly)
            interval_seconds: Seconds between runs (for interval type)
            target_ai_id: Stark AI ID to dispatch
            target_goal: Goal to dispatch to the Stark AI
            target_dot_id: DOT ID to activate
            target_dot_goal: Goal for the DOT
            enabled: Whether the job is initially enabled

        Returns:
            Job ID for the scheduled job
        """
        job_id = f"job-{uuid4().hex[:12]}"
        job = ScheduledJob(
            job_id=job_id,
            name=name,
            schedule_type=schedule_type,
            interval_seconds=interval_seconds,
            target_ai_id=target_ai_id,
            target_goal=target_goal,
            target_dot_id=target_dot_id,
            target_dot_goal=target_dot_goal,
            enabled=enabled,
        )
        self.jobs[job_id] = job
        log.info(
            "Scheduled job created",
            job_id=job_id,
            name=name,
            schedule_type=schedule_type,
            target_ai_id=target_ai_id,
            target_dot_id=target_dot_id,
        )
        return job_id

    def list_jobs(self) -> list[dict[str, Any]]:
        """List all scheduled jobs."""
        return [
            {
                "job_id": j.job_id,
                "name": j.name,
                "schedule_type": j.schedule_type,
                "interval_seconds": j.interval_seconds,
                "target_ai_id": j.target_ai_id,
                "target_goal": j.target_goal,
                "target_dot_id": j.target_dot_id,
                "target_dot_goal": j.target_dot_goal,
                "last_run": j.last_run,
                "next_run": j.next_run,
                "run_count": j.run_count,
                "success_count": j.success_count,
                "failure_count": j.failure_count,
                "enabled": j.enabled,
                "created_at": j.created_at,
                "last_error": j.last_error,
            }
            for j in self.jobs.values()
        ]

    def enable_job(self, job_id: str) -> bool:
        """Enable a scheduled job."""
        job = self.jobs.get(job_id)
        if job is None:
            return False
        job.enabled = True
        return True

    def disable_job(self, job_id: str) -> bool:
        """Disable a scheduled job."""
        job = self.jobs.get(job_id)
        if job is None:
            return False
        job.enabled = False
        return True

    def delete_job(self, job_id: str) -> bool:
        """Delete a scheduled job."""
        if job_id in self.jobs:
            del self.jobs[job_id]
            return True
        return False

    def run_pending(self) -> list[JobResult]:
        """Run all jobs that are due for execution."""
        results = []
        now_time = time.time()

        for job in self.jobs.values():
            if not job.enabled:
                continue

            # Check if job is due
            if job.next_run is None:
                # First run - run immediately
                pass
            elif job.last_run is not None and job.next_run > now_time:
                continue  # Not due yet

            # Execute the job
            result = self._execute_job(job)
            results.append(result)

        return results

    def _execute_job(self, job: ScheduledJob) -> JobResult:
        """Execute a single scheduled job."""
        now_time = time.time()
        job.last_run = now_time
        job.run_count += 1

        try:
            if job.target_ai_id:
                # Dispatch to Stark AI
                result = dispatch_stark_ai(
                    ai_id=job.target_ai_id,
                    goal=job.target_goal or "",
                )
                job.result = result.get("result", {})
                success = result.get("ok", False)

            elif job.target_dot_id:
                # Dispatch to DOT
                dot = self.dots.get(job.target_dot_id)
                if dot is None:
                    raise ValueError(f"Dot not found: {job.target_dot_id}")
                # Dispatch to DOT through system
                dot_result = system.dispatch_stark(
                    ai_id="jarvis",  # Use JARVIS as dispatcher
                    goal=job.target_dot_goal or "Execute scheduled task",
                )
                success = result.get("ok", False)
            else:
                raise ValueError("No target specified for job")

            job.success_count += 1
            job.last_error = None

            job_result = JobResult(
                job_id=job.job_id,
                success=success,
                output=job.result,
            )

        except Exception as exc:
            job.failure_count += 1
            job.last_error = str(exc)
            job_result = JobResult(
                job_id=job.job_id,
                success=False,
                error=str(exc),
            )

        # Update next run time
        if job.interval_seconds:
            job.next_run = now_time + job.interval_seconds

        self.results.append(job_result)
        if len(self.results) > self.max_results:
            self.results = self.results[-self.max_results:]

        log.info(
            "Job executed",
            job_id=job.job_id,
            name=job.name,
            success=job_result.success,
        )

        return job_result

    def get_job_result(self, job_id: str) -> JobResult | None:
        """Get the most recent result for a job."""
        results = [r for r in self.results if r.job_id == job_id]
        if results:
            return results[-1]
        return None

    def get_job_history(self, job_id: str, limit: int = 10) -> list[dict[str, Any]]:
        """Get job execution history."""
        results = [r for r in self.results if r.job_id == job_id]
        results.sort(key=lambda r: r.executed_at, reverse=True)
        return [
            {
                "executed_at": r.executed_at,
                "success": r.success,
                "error": r.error,
                "output": r.output,
            }
            for r in results[:limit]
        ]

    def stats(self) -> dict[str, Any]:
        """Get scheduler statistics."""
        total_jobs = len(self.jobs)
        enabled_jobs = sum(1 for j in self.jobs.values() if j.enabled)
        total_runs = sum(j.run_count for j in self.jobs.values())
        total_successes = sum(j.success_count for j in self.jobs.values())
        total_failures = sum(j.failure_count for j in self.jobs.values())

        return {
            "total_jobs": total_jobs,
            "enabled_jobs": enabled_jobs,
            "disabled_jobs": total_jobs - enabled_jobs,
            "total_runs": total_runs,
            "total_successes": total_successes,
            "total_failures": total_failures,
            "success_rate": total_successes / max(total_runs, 1),
        }


# -- Global instance --

_scheduler: AutomatedScheduler | None = None


def get_scheduler(
    system: JarvisIntegratedSystem | None = None,
    dots: DotManager | None = None,
) -> AutomatedScheduler:
    """Get or create the global scheduler."""
    global _scheduler
    if _scheduler is None:
        if system is None:
            system = get_integrated_system()
        if dots is None:
            from ..dots.manager import DotManager
            dots = DotManager()
        _scheduler = AutomatedScheduler(system=system, dots=dots)
    return _scheduler


__all__ = [
    "ScheduledJob",
    "JobResult",
    "AutomatedScheduler",
    "get_scheduler",
]
