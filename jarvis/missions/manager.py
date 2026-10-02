"""MissionManager — persistent mission lifecycle, no execution.

The manager owns state transitions, persistence, world mirroring, and
event emission. It never executes tools, never approves actions, and
never bypasses the Orchestrator or PolicyEngine. All work happens in
MissionRuntime (runtime.py), one bounded step at a time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core.types import now
from .model import (
    MISSION_SCHEMA_VERSION,
    MISSION_TERMINAL,
    InvalidMissionTransition,
    Mission,
    MissionStatus,
    Objective,
    ObjectiveStatus,
    compute_progress,
    ready_objectives,
)


def _scrub(value: Any) -> Any:
    """Remove secret-looking material before persistence."""
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items()
                if "password" not in k.lower()
                and "secret" not in k.lower()
                and "token" not in k.lower()
                and "credential" not in k.lower()}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    if isinstance(value, str) and len(value) > 200:
        return value[:200] + "…[truncated]"
    return value


@dataclass
class MissionDependencies:
    """Live subsystems injected by the loop. All optional except tasks."""

    tasks: Any = None
    dots: Any = None  # DotManager
    palace: Any = None
    world_registry: Any = None
    triggers: Any = None
    store: Any = None  # JsonFileWorldStore-like: save(dict)/load() -> dict
    policy: Any = None
    bus: Any = None  # EventBus for mission.* events (optional)
    bus: Any = None  # EventBus for mission.* events (optional)


class MissionManager:
    """Central mission lifecycle owner. No threads, no polling, no execution."""

    def __init__(self, deps: MissionDependencies | None = None) -> None:
        self.deps = deps or MissionDependencies()
        self.missions: dict[str, Mission] = {}
        self.proposals: dict[str, Any] = {}
        if self.deps.store is not None:
            self.load()

    # -- persistence -------------------------------------------------
    def persist(self) -> None:
        if self.deps.store is None:
            return
        self.deps.store.save({
            "schema_version": MISSION_SCHEMA_VERSION,
            "saved_at": now(),
            "missions": {mid: _scrub(m.to_dict())
                         for mid, m in self.missions.items()},
            "proposals": {pid: _scrub(p.to_dict())
                          for pid, p in self.proposals.items()},
        })

    def load(self) -> int:
        if self.deps.store is None:
            return 0
        try:
            data = self.deps.store.load()
        except Exception:
            return 0
        if not isinstance(data, dict):
            return 0
        from .proposals import MissionProposal
        count = 0
        for mid, raw in (data.get("missions") or {}).items():
            try:
                mission = Mission.from_dict(raw)
            except Exception:
                continue  # corrupt entry skipped, rest recover
            mission.mission_id = mid
            self.missions[mid] = mission
            count += 1
        for pid, raw in (data.get("proposals") or {}).items():
            try:
                proposal = MissionProposal.from_dict(raw)
            except Exception:
                continue
            proposal.proposal_id = pid
            self.proposals[pid] = proposal
        return count

    # -- lifecycle ---------------------------------------------------
    def create(self, name: str, goal: str, description: str = "",
               priority: int = 5,
               success_criteria: list[dict[str, Any]] | None = None,
               budget: dict[str, Any] | None = None,
               workspace: dict[str, Any] | None = None,
               owner: str = "user") -> Mission:
        mission = Mission(
            name=name, goal=goal, description=description, priority=priority,
            success_criteria=list(success_criteria or []),
            budget=dict(budget or {}), workspace=dict(workspace or {}),
            owner=owner,
            provenance={"created_by": "mission-control", "at": now()})
        self.missions[mission.mission_id] = mission
        mission.transition(MissionStatus.READY)
        self._mirror_world(mission, "created")
        self._emit(f"mission.created", mission)
        self.persist()
        return mission

    def get(self, mission_id: str) -> Mission | None:
        return self.missions.get(mission_id)

    def list(self) -> list[Mission]:
        return sorted(self.missions.values(),
                      key=lambda m: (-m.priority, m.created_at))

    def inspect(self, mission_id: str) -> dict[str, Any] | None:
        mission = self.missions.get(mission_id)
        if mission is None:
            return None
        data = mission.to_dict()
        data["ready_objectives"] = [o.objective_id
                                    for o in ready_objectives(mission)]
        return data

    def _require(self, mission_id: str) -> Mission:
        mission = self.missions.get(mission_id)
        if mission is None:
            raise KeyError(f"unknown mission: {mission_id}")
        return mission

    def start(self, mission_id: str) -> Mission:
        mission = self._require(mission_id)
        if mission.status == MissionStatus.DRAFT:
            mission.transition(MissionStatus.READY)
        mission.transition(MissionStatus.RUNNING)
        if mission.started_at is None:
            mission.started_at = now()
        self._mirror_world(mission, "started")
        self._emit("mission.started", mission)
        self.persist()
        return mission

    def pause(self, mission_id: str) -> Mission:
        mission = self._require(mission_id)
        mission.transition(MissionStatus.PAUSED)
        self._emit("mission.paused", mission)
        self.persist()
        return mission

    def resume(self, mission_id: str, reason: str = "") -> Mission:
        mission = self._require(mission_id)
        if mission.status == MissionStatus.PAUSED:
            mission.transition(MissionStatus.RUNNING)
        elif mission.status in (MissionStatus.READY, MissionStatus.WAITING,
                                MissionStatus.BLOCKED):
            mission.transition(MissionStatus.RUNNING)
        else:
            raise InvalidMissionTransition(
                f"mission {mission_id} in {mission.status.value} "
                f"cannot resume")
        if reason:
            mission.uncertainty.append(f"resumed: {reason}")
        self._emit("mission.resumed", mission)
        self.persist()
        return mission

    def stop(self, mission_id: str, reason: str = "") -> Mission:
        mission = self._require(mission_id)
        if mission.status not in MISSION_TERMINAL:
            mission.transition(MissionStatus.STOPPED)
        if reason:
            mission.uncertainty.append(f"stopped: {reason}")
        self._emit("mission.stopped", mission)
        self.persist()
        return mission

    def cancel(self, mission_id: str, reason: str = "") -> Mission:
        mission = self._require(mission_id)
        if mission.status in MISSION_TERMINAL:
            raise InvalidMissionTransition(
                f"mission {mission_id} already {mission.status.value}")
        mission.transition(MissionStatus.CANCELLED)
        if reason:
            mission.uncertainty.append(f"cancelled: {reason}")
        self._emit("mission.cancelled", mission)
        self.persist()
        return mission

    def recover(self, mission_id: str, reason: str = "") -> Mission:
        """Restart a terminal/blocked mission in a fresh cycle.

        Archives the previous run into metadata, keeps failures visible,
        preserves checkpoints. Never rewrites history.
        """
        mission = self._require(mission_id)
        if (mission.status not in MISSION_TERMINAL
                and mission.status != MissionStatus.BLOCKED):
            if not self._is_stale(mission):
                raise InvalidMissionTransition(
                    f"mission {mission_id} in {mission.status.value} "
                    f"needs no recovery; use pause/resume instead")
        past = {"status": mission.status.value, "progress": mission.progress,
                "uncertainty": list(mission.uncertainty),
                "checkpoints": list(mission.checkpoint_refs),
                "at": now(), "reason": reason}
        mission.metadata.setdefault("past_runs", []).append(_scrub(past))
        for obj in mission.objectives.values():
            if obj.status not in (ObjectiveStatus.COMPLETED,):
                obj.status = ObjectiveStatus.PENDING
                obj.progress = 0.0
                obj.updated_at = now()
        mission.uncertainty = []
        mission.blocked_by = []
        mission.active_objective = ""
        mission.progress = 0.0
        mission.confidence = 0.5
        mission.status = MissionStatus.READY
        mission.updated_at = now()
        mission.version += 1
        mission.metadata["recovered_at"] = now()
        mission.metadata["recovery_reason"] = reason
        self._mirror_world(mission, "recovered")
        self._emit("mission.resumed", mission)
        self.persist()
        return mission

    def _is_stale(self, mission: Mission) -> bool:
        """An active-status mission with no live objectives/tasks died mid-run.

        A pristine mission (no objectives, no failures, no progress) is
        not stale — there is nothing to recover.
        """
        if mission.status in MISSION_TERMINAL:
            return False
        if any(o.status in (ObjectiveStatus.RUNNING, ObjectiveStatus.VERIFYING)
               for o in mission.objectives.values()):
            return False
        return bool(mission.objectives or mission.uncertainty
                    or mission.progress > 0 or mission.task_ids)

    # -- objectives --------------------------------------------------
    def add_objective(self, mission_id: str, name: str,
                      description: str = "", priority: int = 5,
                      weight: float = 1.0,
                      depends_on: list[str] | None = None,
                      dot_id: str = "",
                      success_criteria: list[dict[str, Any]] | None = None
                      ) -> Objective:
        mission = self._require(mission_id)
        if mission.status in MISSION_TERMINAL:
            raise InvalidMissionTransition(
                f"cannot add objectives to {mission.status.value} mission")
        deps = list(depends_on or [])
        for dep_id in deps:
            if dep_id not in mission.objectives:
                raise KeyError(f"unknown dependency objective: {dep_id}")
        obj = Objective(mission_id=mission_id, name=name,
                        description=description, priority=priority,
                        weight=weight, depends_on=deps, dot_id=dot_id,
                        success_criteria=list(success_criteria or []))
        mission.objectives[obj.objective_id] = obj
        mission.updated_at = now()
        mission.version += 1
        self._mirror_world(mission, "objective-added")
        self.persist()
        return obj

    def assign_dot(self, mission_id: str, objective_id: str,
                   dot_id: str) -> Objective:
        mission = self._require(mission_id)
        obj = mission.objectives.get(objective_id)
        if obj is None:
            raise KeyError(f"unknown objective: {objective_id}")
        obj.dot_id = dot_id
        obj.updated_at = now()
        if dot_id not in mission.dot_ids:
            mission.dot_ids.append(dot_id)
        self.persist()
        return obj

    # -- progress ----------------------------------------------------
    def refresh_progress(self, mission_id: str) -> float:
        mission = self._require(mission_id)
        mission.progress = compute_progress(mission)
        mission.updated_at = now()
        return mission.progress

    # -- events ------------------------------------------------------
    def _emit(self, event_type: str, mission: Mission,
              extra: dict[str, Any] | None = None) -> None:
        bus = getattr(self.deps, "bus", None)
        if bus is None:
            return
        try:
            from ..events.store import Event as BusEvent
            payload = {"mission_id": mission.mission_id,
                       "name": mission.name, "status": mission.status.value,
                       "progress": mission.progress}
            if extra:
                payload.update(extra)
            bus.publish(BusEvent(type=event_type, payload=payload))
        except Exception:
            pass

    # -- world mirror ------------------------------------------------
    def _mirror_world(self, mission: Mission, event: str) -> None:
        registry = self.deps.world_registry
        if registry is None:
            return
        try:
            entity, _ = registry.upsert_entity(
                "mission", mission.name,
                state={"status": mission.status.value,
                       "progress": mission.progress},
                provenance={"observer": "mission-control",
                            "source": "missions", "event": event},
                confidence=0.9,
                entity_id=f"mission:{mission.mission_id[:8]}")
            for oid, obj in mission.objectives.items():
                oent, _ = registry.upsert_entity(
                    "objective", obj.name,
                    state={"status": obj.status.value,
                           "progress": obj.progress},
                    provenance={"observer": "mission-control",
                                "source": "missions"},
                    confidence=0.8,
                    entity_id=f"objective:{oid[:8]}")
                registry.relate(entity.id, "contains", oent.id,
                                provenance={"source": "missions"})
            if mission.goal:
                try:
                    gent, _ = registry.upsert_entity(
                        "goal", mission.goal[:60],
                        provenance={"observer": "mission-control",
                                    "source": "missions"},
                        confidence=0.7)
                    registry.relate(entity.id, "related_to", gent.id,
                                    provenance={"source": "missions"})
                except Exception:
                    pass
        except Exception:
            pass

    # -- proposals (3.4) ---------------------------------------------
    def save_proposal(self, proposal: Any) -> Any:
        """Persist a proposal. Idempotent on proposal_id."""
        self.proposals[proposal.proposal_id] = proposal
        self.persist()
        return proposal

    def get_proposal(self, proposal_id: str) -> Any | None:
        return self.proposals.get(proposal_id)

    def list_proposals(self, status: str = "") -> list[Any]:
        items = list(self.proposals.values())
        if status:
            items = [p for p in items if p.status.value == status]
        return sorted(items, key=lambda p: (-p.score, p.created_at))

    def _require_proposal(self, proposal_id: str) -> Any:
        proposal = self.proposals.get(proposal_id)
        if proposal is None:
            raise KeyError(f"unknown proposal: {proposal_id}")
        return proposal

    def _proposal_event(self, event_type: str, proposal: Any,
                        extra: dict[str, Any] | None = None) -> None:
        bus = getattr(self.deps, "bus", None)
        if bus is None:
            return
        try:
            from ..events.store import Event as BusEvent
            payload = {"proposal_id": proposal.proposal_id,
                       "title": proposal.title,
                       "status": proposal.status.value,
                       "score": proposal.score}
            if extra:
                payload.update(extra)
            bus.publish(BusEvent(type=event_type, payload=payload))
        except Exception:
            pass

    def _emergency_engaged(self) -> bool:
        policy = getattr(self.deps, "policy", None)
        if policy is None:
            return False
        try:
            return bool(policy._emergency_stop())
        except Exception:
            return False

    def approve_proposal(self, proposal_id: str,
                         by: str = "user") -> Any:
        """PROPOSED → APPROVED. Records approver; executes nothing."""
        from .proposals import ProposalStatus
        proposal = self._require_proposal(proposal_id)
        proposal.transition(ProposalStatus.APPROVED)
        proposal.provenance["approved_by"] = by
        proposal.provenance["approved_at"] = now()
        self._proposal_event("mission.proposal.approved", proposal,
                             {"by": by})
        self.persist()
        return proposal

    def reject_proposal(self, proposal_id: str, reason: str = "") -> Any:
        from .proposals import ProposalStatus
        proposal = self._require_proposal(proposal_id)
        proposal.transition(ProposalStatus.REJECTED)
        if reason:
            proposal.uncertainty.append(f"rejected: {reason}")
        self._proposal_event("mission.proposal.rejected", proposal,
                             {"reason": reason})
        self.persist()
        return proposal

    def ignore_proposal(self, proposal_id: str) -> Any:
        from .proposals import ProposalStatus
        proposal = self._require_proposal(proposal_id)
        proposal.transition(ProposalStatus.IGNORED)
        self._proposal_event("mission.proposal.ignored", proposal)
        self.persist()
        return proposal

    def expire_proposals(self) -> list[str]:
        """Mark past-expiry PROPOSED proposals EXPIRED. Returns IDs."""
        from .proposals import ProposalStatus
        expired = []
        for proposal in self.proposals.values():
            if proposal.status == ProposalStatus.PROPOSED and proposal.expired:
                proposal.transition(ProposalStatus.EXPIRED)
                self._proposal_event("mission.proposal.expired", proposal)
                expired.append(proposal.proposal_id)
        if expired:
            self.persist()
        return expired

    def convert_proposal(self, proposal_id: str,
                         still_valid: Any = None) -> Any:
        """APPROVED → Mission via MissionManager.create. Re-checks e-stop,
        expiry, and current conditions first. Idempotent: a second call
        returns the already-created mission instead of duplicating it.
        """
        from .proposals import ProposalStatus
        proposal = self._require_proposal(proposal_id)
        if proposal.converted_mission_id:
            existing = self.missions.get(proposal.converted_mission_id)
            if existing is not None:
                return existing
        if proposal.status != ProposalStatus.APPROVED:
            raise InvalidProposalState(
                f"proposal {proposal_id} is {proposal.status.value}; "
                f"only APPROVED proposals convert")
        if proposal.expired:
            proposal.transition(ProposalStatus.EXPIRED)
            self.persist()
            raise InvalidProposalState(
                f"proposal {proposal_id} expired before conversion")
        if self._emergency_engaged():
            raise InvalidProposalState("emergency stop engaged: no conversion")
        if still_valid is not None:
            valid, note = still_valid()
            if not valid:
                proposal.transition(ProposalStatus.CANCELLED)
                proposal.uncertainty.append(f"stale at conversion: {note}")
                self._proposal_event("mission.proposal.cancelled", proposal,
                                     {"reason": f"stale: {note}"})
                self.persist()
                raise InvalidProposalState(
                    f"proposal {proposal_id} no longer necessary: {note}")
        template = proposal.mission_template or {}
        mission = self.create(
            name=template.get("name", proposal.title),
            goal=template.get("goal", proposal.title),
            description=proposal.description,
            priority=proposal.priority,
            budget=dict(template.get("budget", {})),
            workspace=dict(template.get("workspace", {})),
            owner=proposal.provenance.get("approved_by", "user"))
        for spec in proposal.suggested_objectives:
            try:
                self.add_objective(
                    mission.mission_id,
                    name=str(spec.get("name", "objective")),
                    description=str(spec.get("description", "")),
                    priority=int(spec.get("priority", 5)),
                    weight=float(spec.get("weight", 1.0)),
                    depends_on=list(spec.get("depends_on", [])),
                    dot_id=str(spec.get("dot_id", "")),
                    success_criteria=list(spec.get("success_criteria", [])))
            except (KeyError, ValueError):
                continue  # bad suggestion skipped, rest convert
        mission.metadata["proposal_id"] = proposal.proposal_id
        proposal.converted_mission_id = mission.mission_id
        proposal.transition(ProposalStatus.CONVERTED)
        self._proposal_event("mission.proposal.converted", proposal,
                             {"mission_id": mission.mission_id})
        self.persist()
        return mission


class InvalidProposalState(Exception):
    """Proposal not in a state allowing the requested operation."""
