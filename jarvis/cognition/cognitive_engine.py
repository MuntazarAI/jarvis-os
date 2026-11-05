"""Cognitive Engine - M13 Cognitive Architecture Integration.

The cognitive engine integrates all cognitive subsystems:
- Reasoning Engine: Deductive, inductive, abductive reasoning
- Planning Engine: Task decomposition and planning
- World Model: World state, objects, events, causality
- Knowledge Graph: Existing knowledge graph infrastructure
- Stark AI Agents: Stark AI agent coordination
- DOTS: Dot lifecycle management

This is the central cognitive coordinator that connects all
cognitive subsystems into a unified intelligent system.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from ..core.config import JarvisConfig
from ..core.types import now
from .reasoning import ReasoningEngine, get_reasoning_engine
from .planning import PlanningEngine, get_planning_engine
from .world_model import (
    WorldState, WorldObject, WorldEvent,
    ObjectModel, get_object_model,
    EventModel, get_event_model,
    CausalModel, get_causal_model,
    PredictiveModel, get_predictive_model,
    UncertaintyModel, get_uncertainty_model,
)
from ..agents.stark import StarkAI, STARK_ROSTER_BY_ID
from ..dots.manager import DotManager


@dataclass
class CognitiveCycle:
    """Represents one cognitive cycle: perceive → reason → plan → act."""
    cycle_id: str
    timestamp: float
    input: str
    reasoning_steps: list[dict] = field(default_factory=list)
    plan_steps: list[dict] = field(default_factory=list)
    actions_taken: list[dict] = field(default_factory=list)
    confidence: float = 0.0
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "timestamp": self.timestamp,
            "input": self.input,
            "reasoning_steps": self.reasoning_steps,
            "plan_steps": self.plan_steps,
            "actions_taken": self.actions_taken,
            "confidence": self.confidence,
            "duration_ms": self.duration_ms,
        }


class CognitiveEngine:
    """Cognitive engine integrating all cognitive subsystems.

    Provides the main cognitive loop:
    1. Perceive: Gather information from sensors and memory
    2. Reason: Apply reasoning to understand the situation
    3. Plan: Create plans to achieve goals
    4. Act: Execute actions through agents and dots
    5. Learn: Update knowledge based on results
    """

    def __init__(self) -> None:
        self.reasoning_engine = get_reasoning_engine()
        self.planning_engine = get_planning_engine()
        self.world_state = WorldState()
        self.object_model = get_object_model()
        self.event_model = get_event_model()
        self.causal_model = get_causal_model()
        self.predictive_model = get_predictive_model()
        self.uncertainty_model = get_uncertainty_model()
        self.knowledge_graph = None  # Will be set by JARVIS
        self.stark_ais = STARK_ROSTER_BY_ID
        self.dots = None  # Will be set by JARVIS
        self.cycles: list[CognitiveCycle] = []
        self.cycle_count = 0
        self.created_at = time.time()

    def set_jarvis(self, jarvis) -> None:
        """Set the JARVIS instance for full integration."""
        self.jarvis = jarvis

    def set_dots(self, dots: DotManager) -> None:
        """Set the DOTS manager."""
        self.dots = dots

    def cycle(self, input_text: str, context: dict[str, Any] | None = None) -> CognitiveCycle:
        """Run one cognitive cycle: perceive → reason → plan → act."""
        start_time = time.time()
        cycle_id = f"cycle-{self.cycle_count:06d}"
        self.cycle_count += 1

        # Step 1: Perceive - gather information
        perception = self._perceive(input_text, context)

        # Step 2: Reason - apply reasoning to understand
        reasoning_result = self._reason(perception)

        # Step 3: Plan - create plan to achieve goals
        plan = self._plan(reasoning_result)

        # Step 4: Act - execute through agents and dots
        actions = self._act(plan)

        # Step 5: Learn - update knowledge from results
        self._learn(result)

        cycle = CognitiveCycle(
            cycle_id=cycle_id,
            timestamp=time.time(),
            input=input_text,
            reasoning_steps=reasoning_result.get("steps", []),
            plan_steps=plan.get("steps", []),
            actions_taken=actions,
            confidence=reasoning_result.get("confidence", 0.0),
            duration_ms=(time.time() - start_time) * 1000,
        )
        self.cycles.append(cycle)

        return cycle

    def _perceive(self, text: str, context: dict[str, Any] | None) -> dict[str, Any]:
        """Perceive input and context."""
        return {
            "input": text,
            "context": context or {},
            "timestamp": time.time(),
            "entities": self._extract_entities(text),
        }

    def _extract_entities(self, text: str) -> list[dict[str, Any]]:
        """Extract entities from text (simple keyword-based)."""
        # Simple keyword-based entity extraction
        entities = []
        words = text.split()
        for word in words:
            if word[0].isupper() and len(word) > 2:
                entities.append({"text": word, "type": "entity", "confidence": 0.5})
        return entities

    def _reason(self, perception: dict[str, Any]) -> dict[str, Any]:
        """Apply reasoning to perception."""
        from ..cognition.reasoning import ReasoningEngine
        engine = get_reasoning_engine()
        chain = engine.create_chain(perception.get("input", ""))

        # Add reasoning steps
        engine.add_step(
            chain.chain_id,
            "observation",
            f"Observed: {perception.get('input', '')}",
            confidence=0.9,
        )
        engine.add_step(
            chain.chain_id,
            "inference",
            f"Inferred intent from: {perception.get('input', '')}",
            confidence=0.7,
            dependencies=[chain.steps[0].step_id if chain.steps else None],
        )
        engine.add_step(
            chain.chain_id,
            "conclusion",
            f"Conclusion: Handle {perception.get('input', '')}",
            confidence=0.6,
            dependencies=[chain.steps[1].step_id if len(chain.steps) > 1 else None],
        )

        return {
            "chain_id": chain.chain_id,
            "steps": [s.to_dict() for s in chain.steps],
            "conclusion": chain.conclusion,
            "confidence": chain.confidence,
        }

    def _plan(self, reasoning_result: dict[str, Any]) -> dict[str, Any]:
        """Create a plan based on reasoning results."""
        planning_engine = get_planning_engine()
        goal = reasoning_result.get("chain_id", "unknown")
        plan = planning_engine.create_plan(
            goal=goal,
            steps=[
                {"step_id": "step-1", "description": "Analyze input", "agent_id": "jarvis"},
                {"step_id": "step-2", "description": "Execute action", "agent_id": "friday"},
            ],
        )
        return {
            "plan_id": plan.plan_id,
            "goal": plan.goal,
            "steps": [s.to_dict() for s in plan.steps],
        }

    def _act(self, plan: dict[str, Any]) -> list[dict[str, Any]]:
        """Execute actions through agents and dots."""
        actions = []
        for step in plan.get("steps", []):
            agent_id = step.get("agent_id")
            if agent_id and ai_id in STARK_ROSTER_BY_ID:
                stark = STARK_ROSTER_BY_ID[ai_id]
                actions.append({
                    "agent_id": stark.ai_id,
                    "name": stark.name,
                    "action": step.get("description"),
                    "status": "dispatched",
                })
        return actions

    def _learn(self, cycle: CognitiveCycle) -> None:
        """Learn from cycle results."""
        # Update world state with new information
        pass

    def get_status(self) -> dict[str, Any]:
        """Get cognitive engine status."""
        return {
            "cycle_count": self.cycle_count,
            "total_cycles": len(self.cycles),
            "reasoning_chains": len(self.reasoning_engine.chains),
            "plans": len(self.planning_engine.plans),
            "world_objects": len(self.world_state.objects),
            "world_events": len(self.world_state.events),
            "recent_cycles": len(self.cycles),
        }


# Global cognitive engine instance
_cognitive_engine: CognitiveEngine | None = None


def get_cognitive_engine() -> CognitiveEngine:
    """Get or create the global cognitive engine."""
    global _cognitive_engine
    if _cognitive_engine is None:
        _cognitive_engine = CognitiveEngine()
    return _cognitive_engine


__all__ = [
    "CognitiveCycle",
    "CognitiveEngine",
    "get_cognitive_engine",
]
