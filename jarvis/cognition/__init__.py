"""JARVIS Cognition Module (M13+).

Cognitive architecture for JARVIS-OS including:
- Reasoning Engine: Deductive, inductive, abductive, simulation reasoning
- Planning Engine: Task decomposition, task sequencing, budget management
- Knowledge Graph: Entity relationships, knowledge queries, inference
- World Model: World state, objects, events, relationships, provenance
- Cognitive Engine: Unified cognitive loop integrating all subsystems

All components are designed to work together as a unified cognitive system
that can perceive, reason, plan, act, and learn.
"""

from .reasoning import (
    ReasoningStep,
    ReasoningChain,
    ReasoningEngine,
    get_reasoning_engine,
)
from .planning import (
    PlanStep,
    Plan,
    PlanningEngine,
    get_planning_engine,
)
from .world_model import (
    WorldState,
    WorldObject,
    WorldEvent,
    ObjectModel,
    ObjectState,
    EventModel,
    EventRecord,
    CausalModel,
    CausalRelation,
    PredictiveModel,
    Prediction,
    UncertaintyModel,
    UncertaintyEstimate,
    get_object_model,
    get_event_model,
    get_causal_model,
    get_predictive_model,
    get_uncertainty_model,
)
from .cognitive_engine import (
    CognitiveCycle,
    CognitiveEngine,
    get_cognitive_engine,
)
from .evidence_based_reasoning import (
    Evidence,
    Hypothesis,
    ReasoningResult,
    EvidenceBasedReasoning,
    get_evidence_based_reasoning,
)
from .feedback_collection import (
    UserFeedback,
    FeedbackSummary,
    FeedbackCollector,
    get_feedback_collector,
)

__all__ = [
    # Reasoning
    "ReasoningStep",
    "ReasoningChain",
    "ReasoningEngine",
    "get_reasoning_engine",
    # Planning
    "PlanStep",
    "Plan",
    "PlanningEngine",
    "get_planning_engine",
    # World Model
    "WorldState",
    "WorldObject",
    "WorldEvent",
    "ObjectModel",
    "ObjectState",
    "EventModel",
    "EventRecord",
    "CausalModel",
    "CausalRelation",
    "PredictiveModel",
    "Prediction",
    "UncertaintyModel",
    "UncertaintyEstimate",
    "get_object_model",
    "get_event_model",
    "get_causal_model",
    "get_predictive_model",
    "get_uncertainty_model",
    # Cognitive Engine
    "CognitiveCycle",
    "CognitiveEngine",
    "get_cognitive_engine",
    # Evidence-Based Reasoning (M31)
    "Evidence",
    "Hypothesis",
    "ReasoningResult",
    "EvidenceBasedReasoning",
    "get_evidence_based_reasoning",
    # Feedback Collection (M37)
    "UserFeedback",
    "FeedbackSummary",
    "FeedbackCollector",
    "get_feedback_collector",
]
