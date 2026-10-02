"""Mission verification — evidence-consuming, never trust-only.

Verdicts: SUCCESS | FAILURE | UNCERTAIN | INCOMPLETE.
A criterion that cannot be checked yields UNCERTAIN (not failure, not
success). Missing evidence yields INCOMPLETE. Only positive proof of
the criterion yields SUCCESS; only positive proof of absence/failure
yields FAILURE.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core.types import now

VERDICTS = ("SUCCESS", "FAILURE", "UNCERTAIN", "INCOMPLETE")

CRITERION_KINDS = (
    "task_completed",
    "tests_passed",
    "evidence_exists",
    "objectives_completed",
    "files_exist",
    "command_recorded",
    "security_passed",
    "manual_approval",
)


@dataclass
class CriterionResult:
    kind: str
    verdict: str
    evidence: list[str] = field(default_factory=list)
    detail: str = ""
    checked_at: float = field(default_factory=now)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "verdict": self.verdict,
                "evidence": self.evidence, "detail": self.detail,
                "checked_at": self.checked_at}


def verify_criterion(criterion: dict[str, Any], ctx: Any) -> CriterionResult:
    """Check one criterion dict against live subsystems in ctx.

    ctx attributes used (all optional): tasks, palace, world_registry,
    orchestrator, policy. Anything missing → UNCERTAIN, never assumed.
    """
    kind = str(criterion.get("kind", ""))
    if kind not in CRITERION_KINDS:
        return CriterionResult(kind=kind or "unknown", verdict="UNCERTAIN",
                               detail=f"unknown criterion kind: {kind!r}")
    try:
        handler = _HANDLERS[kind]
    except KeyError:
        return CriterionResult(kind=kind, verdict="UNCERTAIN",
                               detail="no checker implemented")
    try:
        return handler(criterion, ctx)
    except Exception as exc:
        return CriterionResult(kind=kind, verdict="UNCERTAIN",
                               detail=f"checker error: {type(exc).__name__}: {exc}")


def verify_all(criteria: list[dict[str, Any]],
               ctx: Any) -> dict[str, Any]:
    """Aggregate: FAILURE dominates, then INCOMPLETE, then UNCERTAIN."""
    results = [verify_criterion(c, ctx) for c in criteria]
    verdict = "SUCCESS"
    for result in results:
        if result.verdict == "FAILURE":
            verdict = "FAILURE"
            break
    else:
        for result in results:
            if result.verdict == "INCOMPLETE":
                verdict = "INCOMPLETE"
                break
        else:
            for result in results:
                if result.verdict == "UNCERTAIN":
                    verdict = "UNCERTAIN"
                    break
    return {"verdict": verdict,
            "results": [r.to_dict() for r in results],
            "checked_at": now()}


def _task_of(ctx: Any, task_id: str) -> Any | None:
    tasks = getattr(ctx, "tasks", None)
    if tasks is None:
        return None
    return (getattr(tasks, "tasks", {}) or {}).get(task_id)


def _check_task_completed(criterion: dict[str, Any], ctx: Any) -> CriterionResult:
    task_id = str(criterion.get("task_id", ""))
    task = _task_of(ctx, task_id)
    if task is None:
        return CriterionResult("task_completed", "UNCERTAIN",
                               detail=f"task not found: {task_id}")
    state = getattr(getattr(task, "state", ""), "value", "")
    if state == "completed":
        return CriterionResult(
            "task_completed", "SUCCESS",
            evidence=[f"task:{task_id}", f"result:{str(task.result)[:160]}"],
            detail=f"task {task_id} completed")
    if state in ("failed",):
        return CriterionResult(
            "task_completed", "FAILURE",
            evidence=[f"task:{task_id}"],
            detail=f"task {task_id} failed: {task.error}")
    return CriterionResult("task_completed", "INCOMPLETE",
                           detail=f"task {task_id} is {state or 'unknown'}")


def _check_tests_passed(criterion: dict[str, Any], ctx: Any) -> CriterionResult:
    text = str(criterion.get("output", "") or "")
    if not text.strip():
        task = _task_of(ctx, str(criterion.get("task_id", "")))
        if task is not None and isinstance(task.result, dict):
            text = str(task.result.get("output", "") or "")
    if not text.strip():
        return CriterionResult("tests_passed", "INCOMPLETE",
                               detail="no test output recorded")
    lowered = text.lower()
    if "failed" in lowered or "error" in lowered:
        return CriterionResult("tests_passed", "FAILURE",
                               evidence=[text[-300:]],
                               detail="test output reports failures")
    if "passed" in lowered:
        return CriterionResult("tests_passed", "SUCCESS",
                               evidence=[text[-300:]],
                               detail="test output reports passes")
    return CriterionResult("tests_passed", "UNCERTAIN",
                           detail="test output inconclusive")


def _check_evidence_exists(criterion: dict[str, Any], ctx: Any) -> CriterionResult:
    refs = [str(r) for r in criterion.get("refs", [])]
    if not refs:
        return CriterionResult("evidence_exists", "INCOMPLETE",
                               detail="no evidence refs listed")
    missing = [r for r in refs if not r.strip()]
    if missing:
        return CriterionResult("evidence_exists", "INCOMPLETE",
                               detail="empty evidence reference listed")
    return CriterionResult("evidence_exists", "SUCCESS", evidence=refs,
                           detail=f"{len(refs)} evidence ref(s) present")


def _check_objectives_completed(criterion: dict[str, Any],
                                ctx: Any) -> CriterionResult:
    mission = getattr(ctx, "mission", None)
    ids = [str(i) for i in criterion.get("objective_ids", [])]
    if mission is None:
        return CriterionResult("objectives_completed", "UNCERTAIN",
                               detail="no mission context bound")
    if not ids:
        return CriterionResult("objectives_completed", "INCOMPLETE",
                               detail="no objective IDs listed")
    failed, incomplete, missing = [], [], []
    for oid in ids:
        obj = mission.objectives.get(oid)
        if obj is None:
            missing.append(oid)
        elif obj.status.value == "failed":
            failed.append(oid)
        elif obj.status.value != "completed":
            incomplete.append(f"{oid}:{obj.status.value}")
    if missing:
        return CriterionResult("objectives_completed", "UNCERTAIN",
                               detail=f"unknown objectives: {missing}")
    if failed:
        return CriterionResult("objectives_completed", "FAILURE",
                               evidence=failed,
                               detail=f"objectives failed: {failed}")
    if incomplete:
        return CriterionResult("objectives_completed", "INCOMPLETE",
                               detail=f"objectives pending: {incomplete}")
    return CriterionResult("objectives_completed", "SUCCESS",
                           evidence=ids, detail="all listed objectives completed")


def _check_files_exist(criterion: dict[str, Any], ctx: Any) -> CriterionResult:
    from pathlib import Path
    paths = [str(p) for p in criterion.get("paths", [])]
    if not paths:
        return CriterionResult("files_exist", "INCOMPLETE",
                               detail="no paths listed")
    missing = [p for p in paths if not Path(p).exists()]
    if missing:
        return CriterionResult("files_exist", "FAILURE", evidence=paths,
                               detail=f"missing files: {missing}")
    return CriterionResult("files_exist", "SUCCESS", evidence=paths,
                           detail=f"{len(paths)} file(s) present")


def _check_command_recorded(criterion: dict[str, Any],
                            ctx: Any) -> CriterionResult:
    task = _task_of(ctx, str(criterion.get("task_id", "")))
    if task is None:
        return CriterionResult("command_recorded", "UNCERTAIN",
                               detail="task not found")
    history = task.history or []
    needle = str(criterion.get("command", "")).lower()
    matches = [h for h in history
               if needle and needle in str(h).lower()] if needle else history
    if not history:
        return CriterionResult("command_recorded", "INCOMPLETE",
                               detail="task has no recorded history")
    if needle and not matches:
        return CriterionResult("command_recorded", "FAILURE",
                               detail=f"command {needle!r} not in task history")
    return CriterionResult("command_recorded", "SUCCESS",
                           evidence=[str(matches[-1])[:200]],
                           detail="command found in task history")


def _check_security_passed(criterion: dict[str, Any],
                           ctx: Any) -> CriterionResult:
    board = getattr(ctx, "blackboard", None)
    entries = []
    if board is not None:
        try:
            entries = [e for e in board.read("verification")]
        except Exception:
            entries = []
    for entry in entries:
        content = entry.content if hasattr(entry, "content") else entry
        text = str(content).lower()
        if "security" in text:
            if "fail" in text or "blocked" in text:
                return CriterionResult("security_passed", "FAILURE",
                                       evidence=[text[:200]],
                                       detail="security check failed")
            if "pass" in text or "clear" in text or "ok" in text:
                return CriterionResult("security_passed", "SUCCESS",
                                       evidence=[text[:200]],
                                       detail="security check passed")
    return CriterionResult("security_passed", "UNCERTAIN",
                           detail="no security verdict recorded")


def _check_manual_approval(criterion: dict[str, Any],
                           ctx: Any) -> CriterionResult:
    token = str(criterion.get("token", ""))
    policy = getattr(ctx, "policy", None)
    if not token:
        return CriterionResult("manual_approval", "INCOMPLETE",
                               detail="no approval token supplied")
    if policy is None:
        return CriterionResult("manual_approval", "UNCERTAIN",
                               detail="no policy bound")
    try:
        approved = bool(policy.approved(token))
    except Exception:
        return CriterionResult("manual_approval", "UNCERTAIN",
                               detail="approval check unavailable")
    if approved:
        return CriterionResult("manual_approval", "SUCCESS",
                               evidence=[f"token:{token[:12]}…"],
                               detail="approval token valid")
    return CriterionResult("manual_approval", "FAILURE",
                           detail="approval token invalid or expired")


_HANDLERS = {
    "task_completed": _check_task_completed,
    "tests_passed": _check_tests_passed,
    "evidence_exists": _check_evidence_exists,
    "objectives_completed": _check_objectives_completed,
    "files_exist": _check_files_exist,
    "command_recorded": _check_command_recorded,
    "security_passed": _check_security_passed,
    "manual_approval": _check_manual_approval,
}
