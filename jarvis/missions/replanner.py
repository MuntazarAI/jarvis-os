"""Mission Replanner — observation-driven mission replanning.

Watches world state changes and detects when mission objectives are
affected. Proposes mission modifications via MissionProposal so the
operator can review and approve replanning.

Never executes anything — proposals flow through MissionManager and
require explicit approval before any mission change.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from ..core.logging import get_module_logger
from ..core.types import now
from .proposals import (
    MissionProposal, ProposalStatus, proposal_dedup_key, score_proposal,
)

log = get_module_logger(__name__)


@dataclass
class ChangeImpact:
    """Assessed impact of a world change on a mission."""
    mission_id: str
    objective_id: str
    change_type: str  # entity_added | entity_updated | entity_removed | timeline_event
    change_description: str
    impact_score: float  # 0..1
    needs_replan: bool
    reason: str


class MissionReplanner:
    """Detects world state changes that affect mission objectives.

    Proposes mission modifications via MissionProposal. Does not execute
    anything — proposals require explicit operator approval before any
    mission change.
    """

    def __init__(self, manager: Any | None = None) -> None:
        self.manager = manager
        self.proposals: list[dict[str, Any]] = []
        self._last_world_snapshot: dict[str, Any] | None = None

    # -- world change detection ------------------------------------------

    def detect_changes(self, previous_snapshot: dict[str, Any],
                       current_snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        """Compare two world snapshots and return detected changes."""
        changes: list[dict[str, Any]] = []

        prev_entities = {e["entity_id"]: e for e in
                         previous_snapshot.get("entities", [])}
        curr_entities = {e["entity_id"]: e for e in
                         current_snapshot.get("entities", [])}

        for eid, curr in curr_entities.items():
            if eid not in prev_entities:
                changes.append({
                    "kind": "entity_added",
                    "entity_id": eid,
                    "name": curr.get("name", ""),
                    "attributes": curr.get("attributes", {}),
                })
            else:
                prev = prev_entities[eid]
                if curr.get("attributes") != prev.get("attributes"):
                    changed = {
                        k: (prev.get(k), curr.get(k))
                        for k in set(curr.get("attributes", {})) |
                                 set(prev.get("attributes", {}))
                        if curr.get(k) != prev.get(k)
                    }
                    changes.append({
                        "kind": "entity_updated",
                        "entity_id": eid,
                        "name": curr.get("name", ""),
                        "changed_attributes": changed,
                    })

        for eid in prev_entities:
            if eid not in curr_entities:
                changes.append({
                    "kind": "entity_removed",
                    "entity_id": eid,
                    "name": prev_entities[eid].get("name", ""),
                })

        prev_count = len(previous_snapshot.get("timeline", []))
        curr_count = len(current_snapshot.get("timeline", []))
        if curr_count > prev_count:
            for ev in current_snapshot["timeline"][prev_count:]:
                changes.append({
                    "kind": "timeline_event",
                    "description": ev.get("description", ""),
                    "source": ev.get("source", "system"),
                    "timestamp": ev.get("timestamp", 0),
                })

        return changes

    # -- impact assessment ----------------------------------------------

    def assess_impact(self, mission: Any, changes: list[dict[str, Any]]
                      ) -> list[ChangeImpact]:
        """Assess how world changes affect mission objectives."""
        impacts: list[ChangeImpact] = []
        objectives = getattr(mission, "objectives", []) or []

        for change in changes:
            for obj in objectives:
                impact = self._assess_single(mission, obj, change)
                if impact and impact.needs_replan:
                    impacts.append(impact)

        return impacts

    def _assess_single(self, mission: Any, objective: Any,
                       change: dict[str, Any]) -> ChangeImpact | None:
        """Assess one change against one objective."""
        change_kind = change["kind"]
        obj_id = getattr(objective, "objective_id", str(objective))
        obj_text = getattr(objective, "description",
                           getattr(objective, "goal", "")) or ""
        obj_text_lower = obj_text.lower()

        impact_score = 0.0
        needs_replan = False
        reason = ""

        # Entity added/updated/removed that matches objective keywords
        if change_kind in ("entity_added", "entity_updated",
                           "entity_removed"):
            entity_name = str(change.get("name", "")).lower()
            entity_id = str(change.get("entity_id", "")).lower()

            # Check if objective mentions this entity
            if entity_name and entity_name in obj_text_lower:
                impact_score = 0.7
                needs_replan = True
                reason = (f"entity '{change.get('name')}' {change_kind} "
                          f"mentioned in objective '{obj_text[:40]}'")
            elif any(word in obj_text_lower for word in
                     ("device", "file", "system", "network", "service")):
                # Generic infrastructure objectives may be affected
                impact_score = 0.4
                needs_replan = True
                reason = (f"infrastructure change '{change.get('name')}' "
                          f"may affect objective '{obj_text[:40]}'")

        # Timeline events that mention objective keywords
        elif change_kind == "timeline_event":
            desc = str(change.get("description", "")).lower()
            if any(word in obj_text_lower for word in desc.split()
                   if len(word) > 3):
                impact_score = 0.5
                needs_replan = True
                reason = (f"timeline event '{change.get('description')[:40]}' "
                          f"may affect objective '{obj_text[:40]}'")

        if not needs_replan:
            return None

        return ChangeImpact(
            mission_id=getattr(mission, "mission_id", ""),
            objective_id=obj_id,
            change_type=change_kind,
            change_description=str(change.get("description", ""))[:200],
            impact_score=impact_score,
            needs_replan=needs_replan,
            reason=reason,
        )

    # -- proposal generation --------------------------------------------

    def propose_replan(self, manager: Any, mission: Any,
                       impacts: list[ChangeImpact]) -> list[MissionProposal]:
        """Generate mission modification proposals for high-impact changes.

        Returns list of MissionProposal objects. Each proposal must be
        explicitly approved before any mission change occurs.
        """
        proposals: list[MissionProposal] = []

        for impact in impacts:
            if impact.impact_score < 0.5:
                continue  # skip low-impact changes

            dedup = proposal_dedup_key(
                "mission-replanner", impact.mission_id,
                f"replan:{impact.objective_id}:{impact.change_type}", "replan")

            # Skip if a live duplicate already exists
            duplicate = False
            for existing in manager.list_proposals():
                if (existing.dedup_key == dedup and
                        existing.status in (
                            ProposalStatus.DRAFT,
                            ProposalStatus.PROPOSED,
                            ProposalStatus.APPROVED)):
                    duplicate = True
                    break
            if duplicate:
                continue

            score, factors = score_proposal(
                urgency=impact.impact_score,
                relevance=impact.impact_score,
                novelty=0.5,
                confidence=0.8,
            )

            goal = getattr(mission, "mission_id", "unknown")
            proposal = MissionProposal(
                title=f"Replan mission {impact.mission_id[:8]}: "
                      f"{impact.change_type} on {impact.objective_id[:8]}",
                reason=impact.reason,
                source="mission-replanner",
                source_refs=[],
                goal_refs=[impact.objective_id],
                world_refs=[],
                event_refs=[],
                mission_template={
                    "goal": getattr(mission, "mission_id", ""),
                    "objective_id": impact.objective_id,
                    "change_type": impact.change_type,
                    "change_description": impact.change_description,
                    "replan_requested": True,
                },
                suggested_objectives=[],
                suggested_dots=[],
                priority=int(impact.impact_score * 10),
                confidence=0.8,
                uncertainty=["replan impact depends on world state"],
                impact="medium",
                urgency=impact.impact_score,
                relevance=impact.impact_score,
                novelty=0.5,
                score=score,
                score_factors=factors,
                expires_at=now() + 7 * 24 * 3600.0,
                status=ProposalStatus.PROPOSED,
                dedup_key=dedup,
                evidence_refs=[],
                provenance={"created_by": "mission-replanner", "at": now()},
            )

            try:
                manager.save_proposal(proposal)
                manager._proposal_event("mission.proposal.created", proposal)
                proposals.append({
                    "proposal_id": proposal.proposal_id,
                    "title": proposal.title,
                    "reason": proposal.reason,
                    "priority": proposal.priority,
                    "confidence": proposal.confidence,
                    "dedup_key": proposal.dedup_key,
                })
                log.info("Mission replan proposed",
                         mission_id=impact.mission_id,
                         objective_id=impact.objective_id,
                         proposal_id=proposal.proposal_id[:8])
            except Exception as exc:  # noqa: BLE001
                log.warning("Failed to save replan proposal",
                            mission_id=impact.mission_id,
                            error=str(exc))

        return proposals

    # -- world snapshot tracking ----------------------------------------

    def update_world_snapshot(self, snapshot: dict[str, Any]) -> None:
        """Record the latest world snapshot for change detection."""
        self._last_world_snapshot = snapshot

    def last_snapshot(self) -> dict[str, Any] | None:
        return self._last_world_snapshot

    def status(self) -> dict[str, Any]:
        return {
            "proposals_generated": len(self.proposals),
            "has_world_snapshot": self._last_world_snapshot is not None,
        }