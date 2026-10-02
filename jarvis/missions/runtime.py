"""MissionRuntime — one bounded mission step at a time.

advance() executes exactly one objective activation, then stops. No loops,
no threads, no polling. Every step: emergency-stop check → ready
objectives → bounded activation (Dot or Orchestrator directly) →
evidence collection → verification → state update → checkpoint →
persist → notify.

Tool execution only ever happens inside DotRuntime.activate or
Orchestrator.run, both behind PolicyEngine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core.types import now
from .model import (
    MISSION_TERMINAL,
    Mission,
    MissionStatus,
    Objective,
    ObjectiveStatus,
    compute_progress,
    ready_objectives,
)
from .verification import verify_all


@dataclass
class MissionContext:
    """Live subsystems for one mission step. Orchestrator is required."""

    orchestrator: Any = None
    tasks: Any = None
    dots: Any = None  # DotManager
    palace: Any = None
    world_registry: Any = None
    policy: Any = None
    notifier: Any = None  # notify.Notifier-like: deliver(notification)
    proactive: Any = None
    max_tool_calls: int = 6
    max_runtime_s: float = 90.0


@dataclass
class StepReport:
    mission_id: str
    step: str = ""
    objective_id: str = ""
    outcome: str = ""  # advanced | waiting | blocked | needs_approval |
    #                    completed | failed | stopped | skipped
    reason: str = ""
    evidence_refs: list[str] = field(default_factory=list)
    verification: str = ""
    progress: float = 0.0
    at: float = field(default_factory=now)

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def _emergency_engaged(policy: Any) -> bool:
    if policy is None:
        return False
    try:
        return bool(policy._emergency_stop())
    except Exception:
        return False


def _scan_event(event: dict[str, Any]) -> tuple[bool, str]:
    try:
        from ..security.guards import scan_injection
    except Exception:
        return True, ""
    text = f"{event.get('summary', '')} {event.get('entity', '')}"
    result = scan_injection(text)
    if not result.get("clean", True):
        return False, f"injection markers in trigger: {result.get('verdict')}"
    return True, ""


class MissionRuntime:
    """Executes one bounded mission step per advance() call."""

    def __init__(self, manager: Any) -> None:
        self.manager = manager

    def advance(self, mission_id: str, ctx: MissionContext,
                event: dict[str, Any] | None = None) -> StepReport:
        """Run a single mission step. Returns a report; persists state."""
        mission = self.manager._require(mission_id)
        if mission.status in MISSION_TERMINAL:
            return StepReport(mission_id, step="noop",
                              outcome="skipped",
                              reason=f"mission already {mission.status.value}")
        if _emergency_engaged(ctx.policy):
            return StepReport(mission_id, step="guard", outcome="blocked",
                              reason="emergency stop engaged")
        if event is not None:
            clean, why = _scan_event(event)
            if not clean:
                return StepReport(mission_id, step="guard", outcome="blocked",
                                  reason=why)
        if mission.status == MissionStatus.READY:
            mission.transition(MissionStatus.RUNNING)
            if mission.started_at is None:
                mission.started_at = now()
        if mission.status not in (MissionStatus.RUNNING,
                                  MissionStatus.VERIFYING):
            return StepReport(
                mission_id, step="guard", outcome="skipped",
                reason=f"mission is {mission.status.value}; "
                f"resume or recover first")
        ready = ready_objectives(mission)
        if not ready:
            return self._settle_no_ready(mission, ctx)
        objective = ready[0]
        mission.active_objective = objective.objective_id
        return self._activate_objective(mission, objective, ctx)

    # -- internals ---------------------------------------------------
    def _settle_no_ready(self, mission: Mission,
                         ctx: MissionContext) -> StepReport:
        objs = list(mission.objectives.values())
        if objs and all(o.status == ObjectiveStatus.COMPLETED for o in objs):
            return self._verify_mission(mission, ctx)
        blocked = [o for o in objs if o.status == ObjectiveStatus.BLOCKED]
        failed = [o for o in objs if o.status == ObjectiveStatus.FAILED]
        if failed:
            mission.transition(MissionStatus.FAILED)
            mission.uncertainty.append(
                f"objectives failed: {[o.objective_id[:8] for o in failed]}")
            self._close_out(mission, ctx, "failed")
            return StepReport(mission.mission_id, step="settle",
                              outcome="failed",
                              reason=f"objectives failed: "
                              f"{[o.name for o in failed]}",
                              progress=mission.progress)
        if blocked:
            mission.transition(MissionStatus.BLOCKED)
            mission.blocked_by = [o.objective_id for o in blocked]
            self._close_out(mission, ctx, "blocked")
            return StepReport(mission.mission_id, step="settle",
                              outcome="blocked",
                              reason=f"objectives blocked: "
                              f"{[o.name for o in blocked]}",
                              progress=mission.progress)
        mission.transition(MissionStatus.WAITING)
        self.manager.persist()
        return StepReport(mission.mission_id, step="settle", outcome="waiting",
                          reason="no ready objectives yet",
                          progress=mission.progress)

    def _activate_objective(self, mission: Mission, objective: Objective,
                            ctx: MissionContext) -> StepReport:
        objective.status = ObjectiveStatus.RUNNING
        objective.updated_at = now()
        self.manager.persist()
        evidence: list[str] = []
        failure = ""
        ok = False
        task_id = ""
        if objective.dot_id and ctx.dots is not None:
            dot = ctx.dots.get(objective.dot_id)
            if dot is None:
                return self._objective_failed(
                    mission, objective, ctx,
                    f"assigned dot missing: {objective.dot_id}")
            from ..dots.runtime import DotRuntime, RuntimeContext
            runtime = DotRuntime(ctx.dots)
            dot_ctx = RuntimeContext(
                orchestrator=ctx.orchestrator, tasks=ctx.tasks,
                palace=ctx.palace,
                world_registry=ctx.world_registry, policy=ctx.policy)
            try:
                result = runtime.activate(
                    dot, reason=f"mission {mission.name}: {objective.name}",
                    ctx=dot_ctx,
                    max_tool_calls=ctx.max_tool_calls,
                    max_runtime_s=ctx.max_runtime_s)
            except Exception as exc:
                return self._objective_failed(
                    mission, objective, ctx,
                    f"dot activation error: {type(exc).__name__}: {exc}")
            task_id = result.task_id
            evidence.extend(result.evidence_refs)
            if result.outcome == "completed":
                ok = True
            elif result.outcome == "needs_approval":
                return self._objective_waiting(
                    mission, objective, ctx, task_id, evidence,
                    "needs_approval", "dot requested approval")
            elif result.outcome in ("waiting", "blocked"):
                return self._objective_waiting(
                    mission, objective, ctx, task_id, evidence,
                    "waiting" if result.outcome == "waiting" else "blocked",
                    result.reason)
            else:
                failure = result.reason or "dot activation failed"
        else:
            if ctx.orchestrator is None:
                return self._objective_failed(
                    mission, objective, ctx, "no orchestrator bound")
            try:
                out = ctx.orchestrator.run(
                    objective.description or objective.name,
                    depth=2, task_id="",
                    parent_id=mission.mission_id)
            except Exception as exc:
                return self._objective_failed(
                    mission, objective, ctx,
                    f"orchestrator error: {type(exc).__name__}: {exc}")
            task_id = str(out.get("task_id", ""))
            evidence.extend(self._collect_evidence(out))
            if out.get("run_id"):
                evidence.append(f"run:{out['run_id']}")
            failure = str(out.get("failure", "") or "")
            ok = bool(out.get("ok", False))
            if not ok and "approval" in failure.lower():
                return self._objective_waiting(
                    mission, objective, ctx, task_id, evidence,
                    "needs_approval", failure)
        if task_id and task_id not in objective.task_ids:
            objective.task_ids.append(task_id)
        if task_id and task_id not in mission.task_ids:
            mission.task_ids.append(task_id)
        return self._verify_objective(mission, objective, ctx, task_id,
                                      evidence, ok, failure)

    def _verify_objective(self, mission: Mission, objective: Objective,
                          ctx: MissionContext, task_id: str,
                          evidence: list[str], ok: bool,
                          failure: str) -> StepReport:
        vctx = _VerifyContext(ctx, mission)
        report = verify_all(objective.success_criteria, vctx)
        verdict = report["verdict"]
        objective.evidence_refs.extend(
            ref for ref in evidence if ref not in objective.evidence_refs)
        mission.evidence_refs.extend(
            ref for ref in evidence if ref not in mission.evidence_refs)
        if verdict == "SUCCESS":
            objective.status = ObjectiveStatus.COMPLETED
            objective.progress = 1.0
            objective.confidence = min(1.0, objective.confidence + 0.1)
            objective.completed_at = now()
            objective.updated_at = now()
        elif verdict == "FAILURE":
            return self._objective_failed(
                mission, objective, ctx,
                "; ".join(r["detail"] for r in report["results"]
                           if r["verdict"] == "FAILURE") or failure
                or "verification failed")
        else:  # UNCERTAIN or INCOMPLETE — never pretend either way.
            objective.status = ObjectiveStatus.VERIFYING
            objective.uncertainty.append(
                f"verification {verdict.lower()}: "
                f"{'; '.join(r['detail'] for r in report['results'][:2])}")
            objective.updated_at = now()
            mission.transition(MissionStatus.WAITING)
            self._checkpoint(mission, objective, task_id, verdict, evidence)
            self.manager.persist()
            self.manager._emit("mission.verification_failed", mission,
                               {"objective_id": objective.objective_id,
                                "verdict": verdict})
            return StepReport(mission.mission_id, step="verify",
                              objective_id=objective.objective_id,
                              outcome="waiting",
                              reason=f"verification {verdict.lower()}",
                              evidence_refs=list(evidence),
                              verification=verdict,
                              progress=mission.progress)
        mission.progress = self.manager.refresh_progress(mission.mission_id)
        self._checkpoint(mission, objective, task_id, verdict, evidence)
        self._remember(mission, objective, ctx, verdict)
        self.manager._mirror_world(mission, f"objective-{verdict.lower()}")
        self.manager.persist()
        self.manager._emit("mission.objective.completed", mission,
                           {"objective_id": objective.objective_id,
                            "verdict": verdict})
        return StepReport(mission.mission_id, step="advance",
                          objective_id=objective.objective_id,
                          outcome="advanced",
                          reason=f"objective {verdict.lower()}",
                          evidence_refs=list(evidence),
                          verification=verdict,
                          progress=mission.progress)

    def _verify_mission(self, mission: Mission,
                        ctx: MissionContext) -> StepReport:
        mission.transition(MissionStatus.VERIFYING)
        vctx = _VerifyContext(ctx, mission)
        report = verify_all(mission.success_criteria, vctx)
        verdict = report["verdict"]
        if verdict == "SUCCESS":
            mission.transition(MissionStatus.COMPLETED)
            mission.progress = 1.0
            mission.confidence = min(1.0, mission.confidence + 0.1)
            outcome, reason = "completed", "all objectives verified"
        elif verdict == "FAILURE":
            mission.transition(MissionStatus.FAILED)
            mission.uncertainty.append("mission verification failed")
            outcome, reason = "failed", "mission verification failed"
        else:
            mission.transition(MissionStatus.WAITING)
            outcome, reason = "waiting", f"mission verification {verdict.lower()}"
        self._checkpoint(mission, None, "", verdict, [], status_note=reason)
        self._remember(mission, None, ctx, verdict)
        self.manager._mirror_world(mission, f"mission-{verdict.lower()}")
        self.manager.persist()
        self.manager._emit(
            f"mission.{'completed' if verdict == 'SUCCESS' else 'failed'}",
            mission)
        return StepReport(mission.mission_id, step="verify-mission",
                          outcome=outcome, reason=reason,
                          verification=verdict, progress=mission.progress)

    def _objective_failed(self, mission: Mission, objective: Objective,
                          ctx: MissionContext, failure: str) -> StepReport:
        objective.status = ObjectiveStatus.FAILED
        objective.updated_at = now()
        objective.failures.append(failure)
        mission.uncertainty.append(f"objective {objective.name}: {failure}")
        mission.progress = self.manager.refresh_progress(mission.mission_id)
        self._checkpoint(mission, objective, "", "FAILURE", [],
                         status_note=failure)
        self.manager.persist()
        self.manager._emit("mission.objective.failed", mission,
                           {"objective_id": objective.objective_id,
                            "failure": failure[:200]})
        self._notify(mission, ctx, "Objective failed",
                     f"{objective.name}: {failure[:200]}", "high")
        return StepReport(mission.mission_id, step="advance",
                          objective_id=objective.objective_id,
                          outcome="failed", reason=failure,
                          verification="FAILURE",
                          progress=mission.progress)

    def _objective_waiting(self, mission: Mission, objective: Objective,
                           ctx: MissionContext, task_id: str,
                           evidence: list[str], outcome: str,
                           reason: str) -> StepReport:
        objective.status = (ObjectiveStatus.VERIFYING
                            if outcome == "needs_approval"
                            else ObjectiveStatus.WAITING)
        objective.updated_at = now()
        objective.evidence_refs.extend(
            ref for ref in evidence if ref not in objective.evidence_refs)
        if outcome == "needs_approval":
            mission.transition(MissionStatus.NEEDS_APPROVAL)
            self.manager._emit("mission.needs_approval", mission,
                               {"objective_id": objective.objective_id})
        else:
            mission.transition(MissionStatus.WAITING)
        if task_id and task_id not in objective.task_ids:
            objective.task_ids.append(task_id)
        self._checkpoint(mission, objective, task_id, outcome.upper(),
                         evidence, status_note=reason)
        self.manager.persist()
        self._notify(mission, ctx,
                     "Approval required" if outcome == "needs_approval"
                     else "Objective waiting",
                     f"{objective.name}: {reason[:200]}",
                     "high" if outcome == "needs_approval" else "normal",
                     requires_approval=(outcome == "needs_approval"))
        return StepReport(mission.mission_id, step="advance",
                          objective_id=objective.objective_id,
                          outcome=outcome, reason=reason,
                          evidence_refs=list(evidence),
                          progress=mission.progress)

    def _close_out(self, mission: Mission, ctx: MissionContext,
                   outcome: str) -> None:
        self._checkpoint(mission, None, "", outcome.upper(), [],
                         status_note=f"mission {outcome}")
        self._remember(mission, None, ctx, outcome.upper())
        self.manager.persist()

    def _checkpoint(self, mission: Mission, objective: Objective | None,
                    task_id: str, verdict: str, evidence: list[str],
                    status_note: str = "") -> dict[str, Any]:
        checkpoint = {
            "checkpoint_id": f"ckpt-{mission.mission_id[:8]}-"
                             f"{mission.version}",
            "mission_id": mission.mission_id,
            "mission_status": mission.status.value,
            "mission_version": mission.version,
            "active_objective": mission.active_objective,
            "objective_id": objective.objective_id if objective else "",
            "objective_status": objective.status.value if objective else "",
            "task_id": task_id,
            "verdict": verdict,
            "evidence_refs": list(evidence[-8:]),
            "progress": mission.progress,
            "uncertainty": list(mission.uncertainty[-5:]),
            "note": status_note,
            "at": now(),
        }
        mission.checkpoint_refs.append(checkpoint["checkpoint_id"])
        mission.metadata.setdefault("checkpoints", []).append(checkpoint)
        mission.metadata["checkpoints"] = mission.metadata["checkpoints"][-20:]
        return checkpoint

    def _remember(self, mission: Mission, objective: Objective | None,
                  ctx: MissionContext, verdict: str) -> None:
        """Persist only durable outcomes: decisions, verified results,
        user-approved preferences. Never raw runtime chatter."""
        palace = getattr(ctx, "palace", None)
        if palace is None:
            return
        try:
            if verdict == "SUCCESS" and objective is not None:
                mem = palace.store_fact(
                    f"mission {mission.name}: objective "
                    f"{objective.name} verified complete",
                    source="missions", importance=0.7,
                    metadata={"mission_id": mission.mission_id,
                              "objective_id": objective.objective_id,
                              "origin": "system"})
                objective.evidence_refs.append(mem.id)
            elif verdict in ("SUCCESS", "FAILURE") and objective is None:
                palace.store_fact(
                    f"mission {mission.name} {verdict.lower()}",
                    source="missions", importance=0.8,
                    metadata={"mission_id": mission.mission_id,
                              "origin": "system"})
        except Exception:
            pass

    def _notify(self, mission: Mission, ctx: MissionContext, title: str,
                message: str, priority: str = "normal",
                requires_approval: bool = False) -> None:
        notifier = getattr(ctx, "notifier", None)
        if notifier is None:
            return
        try:
            from ..notify.notifications import Notification, scrub_notification
            payload = scrub_notification({
                "source_dot": "",
                "type": ("question" if requires_approval else "info"),
                "title": f"[mission {mission.name[:40]}] {title}",
                "message": message[:500],
                "priority": priority,
                "dedup_key": f"mission:{mission.mission_id}:{title}",
                "evidence_refs": list(mission.evidence_refs[-5:]),
                "requires_approval": requires_approval,
            })
            notifier.deliver(Notification(**payload))
        except Exception:
            pass

    def _collect_evidence(self, out: dict[str, Any]) -> list[str]:
        refs: list[str] = []
        result = out.get("result") or {}
        if isinstance(result, dict):
            for key in ("evidence", "citations", "artifacts"):
                value = result.get(key)
                if isinstance(value, list):
                    refs.extend(str(v)[:160] for v in value[:8])
        for conflict in out.get("conflicts", []) or []:
            refs.append(f"conflict: {str(conflict)[:120]}")
        if out.get("run_id"):
            refs.append(f"run:{out['run_id']}")
        return refs


class _VerifyContext:
    """Adapts MissionRuntime context to the verification engine."""

    def __init__(self, ctx: MissionContext, mission: Mission | None = None) -> None:
        self.tasks = ctx.tasks
        self.palace = ctx.palace
        self.policy = ctx.policy
        self.mission = mission if mission is not None else getattr(ctx, "mission", None)
        self.blackboard = None
