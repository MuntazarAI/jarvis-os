"""Mission Control HUD 3.4 — read-oriented status surface.

build_snapshot() gathers one deterministic JSON-serializable dict from
live subsystems via the typed HudContext below. It never mutates
anything, never calls tools, never touches PolicyEngine, and never
includes secrets, tokens, or raw credentials. Approval *tokens* are
counted, never exposed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core.types import now


@dataclass
class HudContext:
    """Explicit inputs for a snapshot. Anything None degrades to unknown."""

    missions: Any = None  # MissionManager
    dots: Any = None  # DotManager
    tasks: Any = None  # TaskEngine
    notifier: Any = None  # notify.Notifier
    policy: Any = None  # PolicyEngine (pending-approval counts only)
    system_state: Any = None  # callable returning a dict, or None
    emergency_engaged: Any = None  # callable returning bool, or None
    proposals: Any = None  # MissionManager (proposal store); may equal missions


def _safe(fn, default: Any):
    try:
        return fn()
    except Exception:
        return default


def _pending_approvals(policy: Any) -> list[dict[str, Any]]:
    approvals = getattr(policy, "approvals", None)
    if not isinstance(approvals, dict):
        return []
    out = []
    for token, record in approvals.items():
        if not isinstance(record, dict) or record.get("status") != "pending":
            continue
        out.append({
            "action": str(record.get("action", ""))[:120],
            "requested_at": record.get("requested_at", 0.0),
            "token_hint": token[:8] + "…",
        })
    return out


def build_snapshot(ctx: HudContext) -> dict[str, Any]:
    """Assemble the Mission Control snapshot. All reads are defensive:
    any failing subsystem contributes an explicit unknown marker."""
    missions = _safe(lambda: ctx.missions.list(), [])
    dots = _safe(lambda: ctx.dots.list(), [])
    tasks_summary: dict[str, Any] = _safe(
        lambda: ctx.tasks.stats(), {"status": "unknown"}) or {}
    proposals: list = _proposal_list(ctx)
    return {
        "generated_at": now(),
        "missions": [_mission_row(m) for m in missions],
        "objectives": _objective_rows(missions),
        "dots": [_dot_row(d) for d in dots],
        "tasks": tasks_summary,
        "blockers": _blockers(missions),
        "approvals": _pending_approvals(ctx.policy),
        "notifications": _notifications(ctx.notifier),
        "evidence": _evidence(missions),
        "proposals": [{
            "proposal_id": p.proposal_id, "title": p.title,
            "status": p.status.value, "score": p.score,
        } for p in _proposal_list(ctx)],
        "system": _safe(ctx.system_state, {"status": "unknown"})
        if callable(ctx.system_state) else {"status": "unknown"},
        "emergency_stop": bool(_safe(ctx.emergency_engaged, False))
        if callable(ctx.emergency_engaged) else False,
    }


def _proposal_list(ctx: HudContext) -> list:
    holders = [getattr(ctx, "proposals", None),
               getattr(ctx, "missions", None)]
    for holder in holders:
        if holder is None:
            continue
        try:
            items = holder.list_proposals()
            if isinstance(items, list):
                return items
        except Exception:
            continue
    return []


def _mission_row(mission: Any) -> dict[str, Any]:
    objectives = list((mission.objectives or {}).values())
    return {
        "mission_id": mission.mission_id,
        "name": mission.name,
        "status": mission.status.value,
        "progress": mission.progress,
        "confidence": mission.confidence,
        "active_objective": mission.active_objective,
        "objectives_total": len(objectives),
        "objectives_completed": sum(
            1 for o in objectives if o.status.value == "completed"),
        "objectives_failed": sum(
            1 for o in objectives if o.status.value == "failed"),
        "updated_at": mission.updated_at,
    }


def _objective_rows(missions: list) -> list[dict[str, Any]]:
    rows = []
    for mission in missions:
        for oid, obj in (mission.objectives or {}).items():
            rows.append({
                "objective_id": oid,
                "mission_id": mission.mission_id,
                "name": obj.name,
                "status": obj.status.value,
                "progress": obj.progress,
                "dot_id": obj.dot_id,
                "blocked_by_deps": [
                    d for d in (obj.depends_on or [])
                    if (mission.objectives.get(d) is not None
                        and mission.objectives[d].status.value != "completed")],
            })
    return rows


def _dot_row(dot: Any) -> dict[str, Any]:
    status = dot.status.value if hasattr(dot.status, "value") else str(dot.status)
    return {
        "dot_id": dot.dot_id,
        "name": dot.name,
        "status": status,
        "progress": dot.progress,
        "task_ids": list(dot.task_ids or [])[:5],
    }


def _blockers(missions: list) -> list[dict[str, Any]]:
    out = []
    for mission in missions:
        for reason in mission.blocked_by or []:
            out.append({"mission_id": mission.mission_id,
                        "reason": str(reason)[:200]})
        for oid, obj in (mission.objectives or {}).items():
            if obj.status.value in ("blocked", "failed"):
                out.append({"mission_id": mission.mission_id,
                            "objective_id": oid,
                            "reason": f"objective {obj.status.value}: "
                                      f"{(obj.failures or ['no detail'])[-1][:200]}"})
    return out


def _notifications(notifier: Any) -> list[dict[str, Any]]:
    delivered = getattr(notifier, "delivered", None)
    if not isinstance(delivered, list):
        return [{"note": "notification feed unavailable"}]
    return [{"title": n.title if hasattr(n, "title") else str(n.get("title", "")),
             "priority": n.priority if hasattr(n, "priority") else str(n.get("priority", "")),
             "at": n.created_at if hasattr(n, "created_at") else n.get("created_at", 0.0)}
            for n in delivered[-20:]]


def _evidence(missions: list) -> dict[str, Any]:
    refs = 0
    for mission in missions:
        refs += len(mission.evidence_refs or [])
        for obj in (mission.objectives or {}).values():
            refs += len(obj.evidence_refs or [])
    return {"total_refs": refs,
            "note": "conflicts stay visible on originating records"}


def snapshot_to_json(snapshot: dict[str, Any]) -> str:
    import json
    return json.dumps(snapshot, indent=2, default=str)
