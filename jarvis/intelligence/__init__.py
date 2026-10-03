"""JARVIS intelligence package: unified cognitive loop over subsystems."""

from .loop import CycleRecord, IntelligenceLoop, LoopState, StageResult, STAGES
from .sensory import SensoryBus, SensoryEvent, SENSORY_TYPES
from .snapshot import CycleSnapshot, capture, compare, replay
from . import wiring

__all__ = [
    "CycleRecord", "CycleSnapshot", "IntelligenceLoop", "LoopState",
    "SENSORY_TYPES", "STAGES", "StageResult", "SensoryBus", "SensoryEvent",
    "capture", "compare", "replay", "wiring",
]


from .adaptive import (
    AdaptiveIntelligence,
    Belief,
    BeliefStatus,
    CausalStatus,
    DecisionMode,
    Evidence,
    EvidenceStatus,
    Experience,
    ExperienceStore,
    Goal,
    GoalInterpreter,
    Hypothesis,
    HypothesisEngine,
    InformationGatherer,
    InformationRequest,
    LearningEngine,
    Outcome,
    Plan,
    PlanCritic,
    PlanStep,
    Prediction,
    capability_fingerprint,
)

__all__ += [
    "AdaptiveIntelligence", "Belief", "BeliefStatus", "CausalStatus",
    "DecisionMode", "Evidence", "EvidenceStatus", "Experience",
    "ExperienceStore", "Goal", "GoalInterpreter", "Hypothesis",
    "HypothesisEngine", "InformationGatherer", "InformationRequest",
    "LearningEngine", "Outcome", "Plan", "PlanCritic", "PlanStep",
    "Prediction", "capability_fingerprint",
]
