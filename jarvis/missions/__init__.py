"""Missions 3.3 — persistent multi-dot objectives."""

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

__all__ = [
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
    "compute_progress",
    "ready_objectives",
    "validate_mission_transition",
    "verify_all",
    "verify_criterion",
]
