"""Proposal detection, scoring, lifecycle, and conversion (3.4).

Detectors read existing subsystem state (missions, goals, tasks, world,
events) and emit MissionProposal drafts. Nothing here executes, approves,
or creates standing permissions. Conversion reuses MissionManager and
re-checks emergency stop, evidence freshness, and staleness first.
"""

from __future__ import annotations

from typing import Any

from ..core.types import now
from .proposals import (
    MissionProposal,
    ProposalStatus,
    proposal_dedup_key,
    score_proposal,
)

FAILURE_THRESHOLD = 3
PROPOSAL_TTL = 7 * 24 * 3600.0


def _scrub_event_refs(refs: list[str]) -> list[str]:
    return [str(r)[:160] for r in refs]


def _new_proposal(manager: Any, title: str, reason: str, source: str,
                  goal: str, blocker: str = "", kind: str = "",
                  priority: int = 5, confidence: float = 0.5,
                  uncertainty: list[str] | None = None,
                  impact: str = "medium", urgency: float = 0.5,
                  relevance: float = 0.5, novelty: float = 0.5,
                  ttl: float = PROPOSAL_TTL,
                  source_refs: list[str] | None = None,
                  goal_refs: list[str] | None = None,
                  world_refs: list[str] | None = None,
                  event_refs: list[str] | None = None,
                  evidence_refs: list[str] | None = None,
                  suggested_objectives: list[dict[str, Any]] | None = None,
                  suggested_dots: list[str] | None = None,
                  mission_template: dict[str, Any] | None = None,
                  weights: dict[str, float] | None = None) -> MissionProposal | None:
    """Create + persist a proposal unless its dedup key already lives."""
    dedup = proposal_dedup_key(source, goal, blocker, kind)
    for existing in manager.list_proposals():
        if existing.dedup_key == dedup and existing.status in (
                ProposalStatus.DRAFT, ProposalStatus.PROPOSED,
                ProposalStatus.APPROVED):
            return None  # live duplicate: do not re-propose
    score, factors = score_proposal(urgency, relevance, novelty,
                                    confidence, weights=weights)
    proposal = MissionProposal(
        title=title, reason=reason, source=source,
        source_refs=list(source_refs or []),
        goal_refs=list(goal_refs or []),
        world_refs=list(world_refs or []),
        event_refs=_scrub_event_refs(list(event_refs or [])),
        mission_template=dict(mission_template or {"goal": goal}),
        suggested_objectives=list(suggested_objectives or []),
        suggested_dots=list(suggested_dots or []),
        priority=priority, confidence=confidence,
        uncertainty=list(uncertainty or []),
        impact=impact, urgency=urgency, relevance=relevance,
        novelty=novelty, score=score, score_factors=factors,
        expires_at=now() + ttl if ttl else None,
        status=ProposalStatus.PROPOSED, dedup_key=dedup,
        evidence_refs=list(evidence_refs or []),
        provenance={"created_by": "proposer-3.4", "at": now()})
    manager.save_proposal(proposal)
    manager._proposal_event("mission.proposal.created", proposal)
    return proposal


def detect_blocked_missions(manager: Any) -> list[MissionProposal]:
    """Blocked missions with a describable recovery direction."""
    out = []
    for mission in manager.list():
        if mission.status.value != "blocked":
            continue
        blockers = list(mission.blocked_by or [])
        evidence = list(mission.evidence_refs[-5:])
        blocker = "; ".join(blockers[:2]) or "unspecified blocker"
        proposal = _new_proposal(
            manager,
            title=f"Recover blocked mission: {mission.name}",
            reason=f"Mission '{mission.name}' is blocked: {blocker}. "
                   f"A recovery mission could diagnose the blocker.",
            source="blocked-mission", goal=mission.goal, blocker=blocker,
            kind="recovery", priority=max(1, mission.priority),
            confidence=0.6,
            uncertainty=["recovery path not guaranteed; diagnosis required"],
            impact="high", urgency=0.7, relevance=0.8, novelty=0.5,
            source_refs=[mission.mission_id], evidence_refs=evidence,
            mission_template={"goal": f"unblock mission {mission.name}",
                              "origin_mission_id": mission.mission_id},
            suggested_objectives=[
                {"name": "Diagnose blocker",
                 "description": f"investigate: {blocker}"},
                {"name": "Apply recovery", "description": "minimal fix only"},
                {"name": "Verify recovery", "description": "confirm unblocked"}],
            suggested_dots=list(mission.dot_ids[:3]))
        if proposal is not None:
            out.append(proposal)
    return out


def detect_blocked_objectives(manager: Any) -> list[MissionProposal]:
    out = []
    for mission in manager.list():
        for oid, obj in (mission.objectives or {}).items():
            if getattr(obj, "status", "") != "blocked":
                continue
            waiting_deps = [d for d in (obj.depends_on or [])
                            if (mission.objectives.get(d) is not None
                                and mission.objectives[d].status != "completed")]
            proposal = _new_proposal(
                manager,
                title=f"Unblock objective: {obj.name}",
                reason=f"Objective '{obj.name}' in mission '{mission.name}' "
                       f"is blocked.",
                source="blocked-objective", goal=mission.goal,
                blocker="; ".join(waiting_deps[:2]),
                kind="recovery", priority=5, confidence=0.55,
                uncertainty=["may need user input on blocked dependencies"],
                impact="medium", urgency=0.6, relevance=0.7, novelty=0.5,
                source_refs=[mission.mission_id, oid],
                mission_template={"goal": f"unblock {obj.name}",
                                  "origin_mission_id": mission.mission_id,
                                  "origin_objective_id": oid},
                suggested_objectives=[
                    {"name": "Inspect blockers",
                     "description": "list blocking dependencies"},
                    {"name": "Resolve or reroute",
                     "description": "minimal unblocking change"}])
            if proposal is not None:
                out.append(proposal)
    return out


def detect_unfinished_goals(manager: Any, palace: Any,
                            max_proposals: int = 3) -> list[MissionProposal]:
    """Goals in MemoryPalace with no linked mission become candidates."""
    out = []
    if palace is None:
        return out
    try:
        goals = palace.all(tier="goal", limit=50)
    except Exception:
        return out
    linked = set()
    for mission in manager.list():
        linked.update(getattr(mission, "goal_refs", []) or [])
        for ref in mission.metadata.get("goal_memory_ids", []) \
                if hasattr(mission, "metadata") else []:
            linked.add(ref)
    count = 0
    for mem in goals:
        if count >= max_proposals:
            break
        content = getattr(mem, "content", "")
        mid = getattr(mem, "id", "")
        if not content.strip() or mid in linked:
            continue
        proposal = _new_proposal(
            manager,
            title=f"Advance goal: {content[:60]}",
            reason="A stated goal has no linked mission; a concrete "
                   "mission could advance it.",
            source="goal", goal=content, kind="advance", priority=4,
            confidence=0.5,
            uncertainty=["goal may already be satisfied; verify first"],
            impact="medium", urgency=0.4, relevance=0.8, novelty=0.6,
            goal_refs=[mid],
            mission_template={"goal": content},
            suggested_objectives=[
                {"name": "Verify goal state",
                 "description": "check whether the goal is already met"},
                {"name": "Plan next step",
                 "description": "smallest concrete action"}])
        if proposal is not None:
            count += 1
            out.append(proposal)
    return out


def detect_repeated_failures(manager: Any, tasks: Any,
                             threshold: int = FAILURE_THRESHOLD,
                             cooldown_s: float = 3600.0) -> list[MissionProposal]:
    """Same task/goal failing ≥ threshold times (cooled down)."""
    out = []
    if tasks is None:
        return out
    try:
        items = list(tasks.tasks.values())
    except Exception:
        return out
    now_ts = now()
    for task in items:
        attempts = int(getattr(task, "attempts", 0) or 0)
        state = str(getattr(getattr(task, "state", ""), "value", "")
                    or getattr(task, "state", ""))
        last_fail = 0.0
        for entry in getattr(task, "history", []) or []:
            if isinstance(entry, dict) and entry.get("event") == "failed":
                last_fail = max(last_fail, float(entry.get("at", 0.0)))
        if attempts < threshold or state not in ("failed", "blocked"):
            continue
        if last_fail and now_ts - last_fail < cooldown_s:
            continue
        goal = str(getattr(task, "goal", "") or "")
        proposal = _new_proposal(
            manager,
            title=f"Break failure loop: {goal[:60]}",
            reason=f"Task failed {attempts} time(s); same approach keeps "
                   f"failing ({state}).",
            source="failure", goal=goal, blocker=f"{attempts}x {state}",
            kind="debug", priority=6, confidence=0.6,
            uncertainty=["root cause unknown until investigated"],
            impact="medium", urgency=0.7, relevance=0.7, novelty=0.4,
            source_refs=[getattr(task, "task_id", "")],
            mission_template={"goal": f"fix recurring failure: {goal[:80]}"},
            suggested_objectives=[
                {"name": "Reproduce + isolate",
                 "description": "minimal reproduction first"},
                {"name": "Fix root cause",
                 "description": "no workarounds without evidence"},
                {"name": "Regression check",
                 "description": "verify fix holds"}])
        if proposal is not None:
            out.append(proposal)
    return out


def detect_capability_gaps(manager: Any, tools: Any,
                           required: list[str] | None = None) -> list[MissionProposal]:
    """Mission-referenced tools/skills missing from the registry."""
    out = []
    if tools is None:
        return out
    try:
        available = {t.spec.name for t in tools.list_tools()
                     if hasattr(t, "spec")}
    except Exception:
        try:
            available = set(tools.list_tools())
        except Exception:
            return out
    needed: dict[str, list[str]] = {}
    for mission in manager.list():
        for oid, obj in (mission.objectives or {}).items():
            for tool in getattr(obj, "required_tools", []) or []:
                if tool not in available:
                    needed.setdefault(tool, []).append(
                        f"{mission.mission_id}:{oid}")
    for extra in (required or []):
        if extra not in available:
            needed.setdefault(extra, []).append("explicit-request")
    for tool, refs in sorted(needed.items()):
        proposal = _new_proposal(
            manager,
            title=f"Enable missing capability: {tool}",
            reason=f"Objectives reference '{tool}' which is not registered. "
                   f"Referenced by: {', '.join(refs[:3])}.",
            source="capability-gap", goal=f"enable {tool}",
            blocker=f"missing tool: {tool}", kind="enablement",
            priority=4, confidence=0.55,
            uncertainty=["capability may be intentionally unavailable"],
            impact="medium", urgency=0.5, relevance=0.6, novelty=0.6,
            mission_template={"goal": f"enable capability {tool}"},
            suggested_objectives=[
                {"name": "Assess need",
                 "description": f"confirm {tool} is genuinely required"},
                {"name": "Enable safely",
                 "description": "register with least privilege"}])
        if proposal is not None:
            out.append(proposal)
    return out


def detect_world_changes(manager: Any, tracker: Any,
                         limit: int = 5) -> list[MissionProposal]:
    """Important World Model 2.x changes become low-pressure proposals."""
    out = []
    if tracker is None:
        return out
    try:
        changes = tracker.latest_changes(limit * 2)
    except Exception:
        return out
    important = [c for c in changes
                 if getattr(c, "kind", "") in (
                     "removed", "stopped", "disconnected", "failed")
                 or "fail" in str(getattr(c, "entity", "")).lower()]
    for change in important[:limit]:
        entity = str(getattr(change, "entity", ""))
        proposal = _new_proposal(
            manager,
            title=f"Respond to change: {entity[:60]}",
            reason=f"World change observed: {change.describe()}.",
            source="world-change", goal=f"respond to {entity}",
            kind="respond", priority=4, confidence=0.5,
            uncertainty=["change may be transient or expected"],
            impact="medium", urgency=0.55, relevance=0.6, novelty=0.6,
            world_refs=[entity],
            evidence_refs=[f"change:{entity}"],
            mission_template={"goal": f"respond to change in {entity}"},
            suggested_objectives=[
                {"name": "Assess change",
                 "description": "determine if action is needed"},
                {"name": "Respond minimally",
                 "description": "smallest safe response"}])
        if proposal is not None:
            out.append(proposal)
    return out


def scan_all(manager: Any, palace: Any = None, tasks: Any = None,
             tools: Any = None, tracker: Any = None,
             weights: dict[str, float] | None = None) -> list:
    """Run every detector. Read-only except persisting new proposals."""
    out = []
    out.extend(detect_blocked_missions(manager))
    out.extend(detect_blocked_objectives(manager))
    out.extend(detect_unfinished_goals(manager, palace))
    out.extend(detect_repeated_failures(manager, tasks))
    out.extend(detect_capability_gaps(manager, tools))
    out.extend(detect_world_changes(manager, tracker))
    if weights:
        for proposal in out:
            score, factors = score_proposal(
                proposal.urgency, proposal.relevance, proposal.novelty,
                proposal.confidence, weights=weights)
            proposal.score, proposal.score_factors = score, factors
    return out
