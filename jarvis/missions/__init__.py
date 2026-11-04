"""Missions 3.3 — persistent multi-dot objectives.

Public API:

- Mission / MissionManager — persistent mission lifecycle, objectives,
  state transitions, persistence, world mirroring, event emission.
- MissionRuntime / MissionContext / StepReport — one bounded mission
  step per advance() call, emergency-stop checked, PolicyEngine-gated.
- MissionApprovalGate — policy-gated mission step execution with
  approval tokens for higher-risk steps (builds on Phase 3 Approval UX).
- MissionReplanner — observation-driven mission replanning: detects
  world state changes and proposes mission modifications via
  MissionProposal.
- MissionDependencies — live subsystems injected by the loop.
- Verification (VERDICTS, verify_all, verify_criterion) — objective
  verification with evidence.
- Proposals (MissionProposal, ProposalStatus) — evidence-backed
  suggestions awaiting approval.
"""

from .manager import MissionDependencies, MissionManager
from .model import (
    MISSION_SCHEMA_VERSION,
    MISSION_TERMINAL,
    InvalidMissionTransition,
    InvalidObjectiveTransition,
    Mission,
    MissionStatus,
    Objective,
    ObjectiveStatus,
    compute_progress,
    ready_objectives,
    validate_mission_transition,
)
from .runtime import MissionContext, MissionRuntime, StepReport
from .verification import VERDICTS, verify_all, verify_criterion
from .proposals import (
    MissionProposal, ProposalStatus, proposal_dedup_key, score_proposal,
)
from .approval_gate import MissionApprovalGate, MissionStepVerdict
from .replanner import MissionReplanner, ChangeImpact

__all__ = [
    # Mission lifecycle
    "MISSION_SCHEMA_VERSION",
    "MISSION_TERMINAL",
    "InvalidMissionTransition",
    "InvalidObjectiveTransition",
    "Mission",
    "MissionContext",
    "MissionDependencies",
    "MissionManager",
    "MissionRuntime",
    "MissionStatus",
    "Objective",
    "ObjectiveStatus",
    "StepReport",
    "VERDICTS",
    "verify_all",
    "verify_criterion",
    # Proposals
    "MissionProposal",
    "ProposalStatus",
    "proposal_dedup_key",
    "score_proposal",
    # Approval gate
    "MissionApprovalGate",
    "MissionStepVerdict",
    # Replanner
    "MissionReplanner",
    "ChangeImpact",
]