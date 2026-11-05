"""Reasoning Engine - M13 Cognitive Architecture.

Provides multi-step reasoning capabilities including:
- Deductive reasoning: From general rules to specific conclusions
- Inductive reasoning: From specific observations to general rules
- Abductive reasoning: From observations to best explanations
- Analogical reasoning: From similar cases to new conclusions
- Counterfactual reasoning: "What if" scenarios
- Chain-of-thought reasoning: Step-by-step problem solving
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ReasoningStep:
    """A single step in a reasoning chain."""
    step_id: str
    step_type: str  # "observation", "inference", "conclusion", "verification"
    content: str
    confidence: float
    dependencies: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "step_type": self.step_type,
            "content": self.content,
            "confidence": self.confidence,
            "dependencies": self.dependencies,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


@dataclass
class ReasoningChain:
    """A chain of reasoning steps leading to a conclusion."""
    chain_id: str
    goal: str
    steps: list[ReasoningStep] = field(default_factory=list)
    conclusion: str | None = None
    confidence: float = 0.0
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_step(self, step: ReasoningStep) -> None:
        """Add a reasoning step to the chain."""
        self.steps.append(step)

    def compute_confidence(self) -> float:
        """Compute overall confidence based on step confidences."""
        if not self.steps:
            return 0.0
        return sum(s.confidence for s in self.steps) / len(self.steps)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chain_id": self.chain_id,
            "goal": self.goal,
            "steps": [
                {
                    "step_id": s.step_id,
                    "step_type": s.step_type,
                    "content": s.content,
                    "confidence": s.confidence,
                    "dependencies": s.dependencies,
                    "timestamp": s.timestamp,
                }
                for s in self.steps
            ],
            "conclusion": self.conclusion,
            "confidence": self.confidence,
            "created_at": self.created_at,
        }


class ReasoningEngine:
    """Reasoning engine for JARVIS cognitive architecture.

    Supports multiple reasoning modes:
    - Deductive: From general rules to specific conclusions
    - Inductive: From specific observations to general rules
    - Abductive: From observations to best explanations
    - Analogical: From similar cases to new conclusions
    - Counterfactual: "What if" scenarios
    """

    def __init__(self) -> None:
        self.chains: dict[str, ReasoningChain] = {}
        self.created_at = time.time()

    def create_chain(self, goal: str) -> ReasoningChain:
        """Create a new reasoning chain."""
        chain_id = f"chain-{len(self.chains):06d}"
        chain = ReasoningChain(chain_id=chain_id, goal=goal)
        self.chains[chain_id] = chain
        return chain

    def add_step(self, chain_id: str, step_type: str, content: str,
                 confidence: float, dependencies: list[str] | None = None) -> ReasoningStep:
        """Add a reasoning step to a chain."""
        chain = self.chains.get(chain_id)
        if chain is None:
            raise ValueError(f"Chain {chain_id} not found")
        step = ReasoningStep(
            step_id=f"step-{len(chain.steps):03d}",
            step_type=step_type,
            content=content,
            confidence=confidence,
            dependencies=dependencies or [],
        )
        chain.add_step(step)
        return step

    def deduce(self, premises: list[str], conclusion: str,
               confidence: float = 0.8) -> ReasoningStep:
        """Deductive reasoning: If premises are true, conclusion must be true."""
        return ReasoningStep(
            step_id=f"deduce-{len(self.chains):06d}",
            step_type="deduction",
            content=f"Given: {', '.join(premises)}. Therefore: {conclusion}",
            confidence=confidence,
        )

    def induce(self, observations: list[str], generalization: str,
               confidence: float = 0.6) -> ReasoningStep:
        """Inductive reasoning: From specific observations to general rule."""
        return ReasoningStep(
            step_id=f"induce-{len(self.chains):06d}",
            step_type="induction",
            content=f"Observed: {', '.join(observations)}. Therefore: {generalization}",
            confidence=confidence,
        )

    def abduct(self, observation: str, explanation: str,
               confidence: float = 0.5) -> ReasoningStep:
        """Abductive reasoning: From observation to best explanation."""
        return ReasoningStep(
            step_id=f"abduct-{len(self.chains):06d}",
            step_type="abduction",
            content=f"Observed: {observation}. Best explanation: {explanation}",
            confidence=confidence,
        )

    def counterfactual(self, original: str, alternative: str,
                       consequence: str, confidence: float = 0.4) -> ReasoningStep:
        """Counterfactual reasoning: 'What if' analysis."""
        return ReasoningStep(
            step_id=f"counterfactual-{len(self.chains):06d}",
            step_type="counterfactual",
            content=f"If {original} were {alternative}, then {consequence}",
            confidence=confidence,
        )

    def get_chain(self, chain_id: str) -> ReasoningChain | None:
        """Get a reasoning chain by ID."""
        return self.chains.get(chain_id)

    def get_all_chains(self) -> list[ReasoningChain]:
        """Get all reasoning chains."""
        return list(self.chains.values())

    def get_stats(self) -> dict[str, Any]:
        """Get reasoning engine statistics."""
        total_steps = sum(len(c.steps) for c in self.chains.values())
        avg_confidence = (
            sum(c.confidence for c in self.chains.values()) / len(self.chains)
            if self.chains else 0.0
        )
        return {
            "total_chains": len(self.chains),
            "total_steps": total_steps,
            "average_confidence": avg_confidence,
            "completed_chains": sum(1 for c in self.chains.values()
                                    if c.conclusion is not None),
        }


# Global reasoning engine instance
_reasoning_engine: ReasoningEngine | None = None


def get_reasoning_engine() -> ReasoningEngine:
    """Get or create the global reasoning engine."""
    global _reasoning_engine
    if _reasoning_engine is None:
        _reasoning_engine = ReasoningEngine()
    return _reasoning_engine


__all__ = [
    "ReasoningStep",
    "ReasoningChain",
    "ReasoningEngine",
    "get_reasoning_engine",
]
