"""Evidence-Based Reasoning - M31.

Builds on:
- ReasoningEngine (M13) for deductive/inductive/abductive reasoning
- WorldModel (M30) for environmental state
- PersistentMemory (M28) for evidence storage
- TemporalKnowledge (M29) for temporal validity

Provides:
- Evidence collection and tracking
- Evidence-based hypothesis generation and evaluation
- Contradiction detection between evidence and hypotheses
- Confidence-weighted reasoning chains
- Evidence provenance tracking
- Hypothesis testing and revision
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any

from ..cognition.reasoning import (
    ReasoningEngine,
    ReasoningChain,
    ReasoningStep,
    get_reasoning_engine,
)
from ..memory.persistent import PersistentMemory, MemorySearchResult
from ..memory.temporal import TemporalKnowledge, TemporalFact

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ..world.model import WorldModel


@dataclass
class Evidence:
    """A piece of evidence supporting or refuting a claim."""
    evidence_id: str
    claim: str
    description: str
    source: str
    provenance: str  # observed, inferred, told, hypothesis, system
    confidence: float  # 0-1
    timestamp: float
    related_entities: list[str] = field(default_factory=list)
    related_memories: list[str] = field(default_factory=list)
    related_events: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "claim": self.claim,
            "description": self.description,
            "source": self.source,
            "provenance": self.provenance,
            "confidence": self.confidence,
            "timestamp": self.timestamp,
            "related_entities": self.related_entities,
            "related_memories": self.related_memories,
            "related_events": self.related_events,
            "metadata": self.metadata,
        }


@dataclass
class Hypothesis:
    """A hypothesis about the world state."""
    hypothesis_id: str
    claim: str
    description: str
    confidence: float  # 0-1
    status: str  # active, confirmed, refuted, undetermined
    supporting_evidence: list[str] = field(default_factory=list)  # evidence_ids
    contradicting_evidence: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "claim": self.claim,
            "description": self.description,
            "confidence": self.confidence,
            "status": self.status,
            "supporting_evidence": self.supporting_evidence,
            "contradicting_evidence": self.contradicting_evidence,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }

    def net_confidence(self) -> float:
        """Compute net confidence considering supporting and contradicting evidence."""
        if not self.supporting_evidence and not self.contradicting_evidence:
            return self.confidence

        support = len(self.supporting_evidence)
        contradict = len(self.contradicting_evidence)
        total = support + contradict

        if total == 0:
            return self.confidence

        # Base confidence adjusted by evidence ratio
        evidence_ratio = support / total
        return self.confidence * (0.5 + 0.5 * evidence_ratio)


@dataclass
class ReasoningResult:
    """Result of evidence-based reasoning."""
    result_id: str
    claim: str
    conclusion: str  # supported, refuted, undetermined
    confidence: float
    reasoning_chain_id: str
    supporting_evidence: list[Evidence]
    contradicting_evidence: list[Evidence]
    hypothesis: Hypothesis | None
    reasoning_steps: list[dict[str, Any]]
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "result_id": self.result_id,
            "claim": self.claim,
            "conclusion": self.conclusion,
            "confidence": self.confidence,
            "reasoning_chain_id": self.reasoning_chain_id,
            "supporting_evidence": [e.to_dict() for e in self.supporting_evidence],
            "contradicting_evidence": [e.to_dict() for e in self.contradicting_evidence],
            "hypothesis": self.hypothesis.to_dict() if self.hypothesis else None,
            "reasoning_steps": self.reasoning_steps,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


class EvidenceBasedReasoning:
    """Evidence-Based Reasoning - M31.

    Integrates reasoning, evidence, memory, and world model to provide
    evidence-aware intelligent reasoning:

    - Evidence collection and tracking with provenance
    - Hypothesis generation and evaluation
    - Evidence-based confidence computation
    - Contradiction detection between evidence and hypotheses
    - Reasoning chain construction with evidence links
    - Hypothesis revision based on new evidence
    """

    def __init__(
        self,
        reasoning_engine: ReasoningEngine | None = None,
        world_model: WorldModel | None = None,
        persistent_memory: PersistentMemory | None = None,
        temporal_knowledge: TemporalKnowledge | None = None,
    ):
        self.reasoning_engine = reasoning_engine or ReasoningEngine()
        self.world_model = world_model
        self.pm = persistent_memory or PersistentMemory()
        self.tk = temporal_knowledge or TemporalKnowledge(
            persistent_memory=self.pm
        )

        # Evidence store
        self.evidence: dict[str, Evidence] = {}

        # Hypothesis store
        self.hypotheses: dict[str, Hypothesis] = {}

        # Reasoning results
        self.results: dict[str, ReasoningResult] = {}

        # Statistics
        self.stats = {
            "evidence_collected": 0,
            "hypotheses_generated": 0,
            "hypotheses_confirmed": 0,
            "hypotheses_refuted": 0,
            "reasoning_results": 0,
            "contradictions_detected": 0,
        }
        self.created_at = time.time()

    # -- Evidence Collection ---------------------------------------------

    def collect_evidence(
        self,
        claim: str,
        description: str,
        source: str,
        provenance: str = "observed",
        confidence: float = 0.5,
        related_entities: list[str] | None = None,
        related_memories: list[str] | None = None,
        related_events: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Collect a piece of evidence.

        Args:
            claim: The claim this evidence relates to
            description: Description of the evidence
            source: Source of the evidence
            provenance: Provenance (observed, inferred, told, hypothesis, system)
            confidence: Confidence in the evidence (0-1)
            related_entities: Related entity names
            related_memories: Related memory IDs
            related_events: Related event IDs
            metadata: Additional metadata

        Returns:
            Evidence ID
        """
        import hashlib
        evidence_id = f"ev-{hashlib.sha256(f'{claim}|{description}|{source}|{time.time()}'.encode()).hexdigest()[:12]}"

        evidence = Evidence(
            evidence_id=evidence_id,
            claim=claim,
            description=description,
            source=source,
            provenance=provenance,
            confidence=confidence,
            timestamp=time.time(),
            related_entities=related_entities or [],
            related_memories=related_memories or [],
            related_events=related_events or [],
            metadata=metadata or {},
        )

        self.evidence[evidence_id] = evidence

        # Also store in persistent memory
        self.pm.store(
            content=f"Evidence: {description} (claim: {claim})",
            tier="evidence",
            room="Evidence",
            kind="evidence",
            source=source,
            origin=provenance,
            confidence=confidence,
            related_entities=related_entities or [],
            metadata={
                "evidence_id": evidence_id,
                "claim": claim,
                "provenance": provenance,
            },
        )

        self.stats["evidence_collected"] += 1
        return evidence_id

    def get_evidence(self, evidence_id: str) -> Evidence | None:
        """Get evidence by ID."""
        return self.evidence.get(evidence_id)

    def get_evidence_for_claim(
        self,
        claim: str,
    ) -> list[Evidence]:
        """Get all evidence related to a claim."""
        return [
            e for e in self.evidence.values()
            if e.claim == claim
        ]

    # -- Hypothesis Management -------------------------------------------

    def generate_hypothesis(
        self,
        claim: str,
        description: str,
        initial_confidence: float = 0.5,
        supporting_evidence: list[str] | None = None,
        contradicting_evidence: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Generate a hypothesis about a claim.

        Args:
            claim: The claim this hypothesis addresses
            description: Description of the hypothesis
            initial_confidence: Initial confidence (0-1)
            supporting_evidence: Evidence IDs supporting this hypothesis
            contradicting_evidence: Evidence IDs contradicting this hypothesis
            metadata: Additional metadata

        Returns:
            Hypothesis ID
        """
        import hashlib
        hypothesis_id = f"hyp-{hashlib.sha256(f'{claim}|{description}|{time.time()}'.encode()).hexdigest()[:12]}"

        hypothesis = Hypothesis(
            hypothesis_id=hypothesis_id,
            claim=claim,
            description=description,
            confidence=initial_confidence,
            status="active",
            supporting_evidence=supporting_evidence or [],
            contradicting_evidence=contradicting_evidence or [],
            metadata=metadata or {},
        )

        self.hypotheses[hypothesis_id] = hypothesis
        self.stats["hypotheses_generated"] += 1
        return hypothesis_id

    def get_hypothesis(self, hypothesis_id: str) -> Hypothesis | None:
        """Get a hypothesis by ID."""
        return self.hypotheses.get(hypothesis_id)

    def get_hypotheses_for_claim(
        self,
        claim: str,
    ) -> list[Hypothesis]:
        """Get all hypotheses for a claim."""
        return [
            h for h in self.hypotheses.values()
            if h.claim == claim
        ]

    def update_hypothesis_confidence(
        self,
        hypothesis_id: str,
        confidence: float,
    ) -> bool:
        """Update a hypothesis confidence based on new evidence."""
        hypothesis = self.hypotheses.get(hypothesis_id)
        if not hypothesis:
            return False

        hypothesis.confidence = confidence
        hypothesis.updated_at = time.time()
        return True

    def add_evidence_to_hypothesis(
        self,
        hypothesis_id: str,
        evidence_id: str,
        supporting: bool = True,
    ) -> bool:
        """Add evidence to a hypothesis (supporting or contradicting)."""
        hypothesis = self.hypotheses.get(hypothesis_id)
        evidence = self.evidence.get(evidence_id)

        if not hypothesis or not evidence:
            return False

        if supporting:
            if evidence_id not in hypothesis.supporting_evidence:
                hypothesis.supporting_evidence.append(evidence_id)
        else:
            if evidence_id not in hypothesis.contradicting_evidence:
                hypothesis.contradicting_evidence.append(evidence_id)

        hypothesis.updated_at = time.time()
        return True

    # -- Evidence-Based Reasoning ----------------------------------------

    def reason_about_claim(
        self,
        claim: str,
        context: str | None = None,
    ) -> ReasoningResult:
        """Perform evidence-based reasoning about a claim.

        Args:
            claim: The claim to reason about
            context: Optional context for the reasoning

        Returns:
            ReasoningResult with conclusion and confidence
        """
        import time as _time
        start = _time.time()
        result_id = f"rr-{hashlib.sha256(f'{claim}|{start}'.encode()).hexdigest()[:12]}"

        # Collect evidence for this claim
        supporting_evidence = [
            e for e in self.evidence.values()
            if e.claim == claim
        ]

        # Find contradicting evidence (evidence for the negation)
        contradicting_evidence = [
            e for e in self.evidence.values()
            if e.claim == f"not {claim}" or e.claim == f"not {claim}"
        ]

        # Find or create hypothesis
        existing_hypotheses = self.get_hypotheses_for_claim(claim)
        if existing_hypotheses:
            hypothesis = existing_hypotheses[0]  # Use most recent
        else:
            hypothesis_id = self.generate_hypothesis(
                claim=claim,
                description=f"Hypothesis about: {claim}",
                initial_confidence=0.5,
            )
            hypothesis = self.hypotheses[hypothesis_id]

        # Update hypothesis with evidence
        for e in supporting_evidence:
            self.add_evidence_to_hypothesis(hypothesis.hypothesis_id, e.evidence_id, supporting=True)
        for e in contradicting_evidence:
            self.add_evidence_to_hypothesis(hypothesis.hypothesis_id, e.evidence_id, supporting=False)

        # Compute net confidence
        net_confidence = hypothesis.net_confidence()

        # Determine conclusion
        if net_confidence >= 0.7:
            conclusion = "supported"
        elif net_confidence <= 0.3:
            conclusion = "refuted"
        else:
            conclusion = "undetermined"

        # Build reasoning chain using the reasoning engine
        chain = self.reasoning_engine.create_chain(
            goal=f"Evaluate claim: {claim}"
        )

        # Add reasoning steps
        step1 = self.reasoning_engine.add_step(
            chain.chain_id,
            "observation",
            f"Claim: {claim}",
            confidence=1.0,
        )

        step2 = self.reasoning_engine.add_step(
            chain.chain_id,
            "evidence_collection",
            f"Found {len(supporting_evidence)} supporting evidence, {len(contradicting_evidence)} contradicting evidence",
            confidence=0.8,
            dependencies=[step1.step_id],
        )

        step3 = self.reasoning_engine.add_step(
            chain.chain_id,
            "inference",
            f"Net confidence: {net_confidence:.2f} based on evidence weighting",
            confidence=net_confidence,
            dependencies=[step2.step_id],
        )

        step4 = self.reasoning_engine.add_step(
            chain.chain_id,
            "conclusion",
            f"Conclusion: {conclusion}",
            confidence=net_confidence,
            dependencies=[step3.step_id],
        )

        # Build reasoning steps output
        reasoning_steps = [
            {
                "step_id": s.step_id,
                "step_type": s.step_type,
                "content": s.content,
                "confidence": s.confidence,
            }
            for s in chain.steps
        ]

        result = ReasoningResult(
            result_id=result_id,
            claim=claim,
            conclusion=conclusion,
            confidence=net_confidence,
            reasoning_chain_id=chain.chain_id,
            supporting_evidence=supporting_evidence,
            contradicting_evidence=contradicting_evidence,
            hypothesis=hypothesis,
            reasoning_steps=reasoning_steps,
            metadata={
                "context": context,
                "evidence_count": len(supporting_evidence) + len(contradicting_evidence),
                "supporting_count": len(supporting_evidence),
                "contradicting_count": len(contradicting_evidence),
            },
        )

        self.results[result_id] = result
        self.stats["reasoning_results"] += 1

        # Detect contradictions
        contradictions = self._detect_evidence_contradictions(claim)
        self.stats["contradictions_detected"] += len(contradictions)

        return result

    def reason_about_world_state(
        self,
        object_id: str,
        attribute: str,
        expected_value: str,
    ) -> ReasoningResult:
        """Reason about world model state using evidence.

        Args:
            object_id: Object to reason about
            attribute: Attribute to check
            expected_value: Expected value of the attribute

        Returns:
            ReasoningResult
        """
        claim = f"{object_id} {attribute} is {expected_value}"

        # Gather evidence from world model
        obj = self.world_model.get_object(object_id) if self.world_model else None
        if obj:
            actual_value = obj.properties.get(attribute, obj.state)
            evidence_confidence = obj.confidence
        else:
            actual_value = None
            evidence_confidence = 0.0

        # Collect evidence from world model
        if actual_value is not None:
            self.collect_evidence(
                claim=claim,
                description=f"World model reports {object_id} {attribute} is {actual_value}",
                source="world_model",
                provenance="observed",
                confidence=evidence_confidence,
                related_entities=[object_id],
            )

        # Now reason about the claim
        return self.reason_about_claim(claim)

    # -- Contradiction Detection -----------------------------------------

    def _detect_evidence_contradictions(
        self,
        claim: str,
    ) -> list[dict[str, Any]]:
        """Detect contradictions between evidence for and against a claim."""
        supporting = self.get_evidence_for_claim(claim)
        contradicting = self.get_evidence_for_claim(f"not {claim}")

        contradictions = []
        for s in supporting:
            for c in contradicting:
                if s.confidence > 0.5 and c.confidence > 0.5:
                    contradictions.append({
                        "claim": claim,
                        "supporting_evidence_id": s.evidence_id,
                        "supporting_confidence": s.confidence,
                        "contradicting_evidence_id": c.evidence_id,
                        "contradicting_confidence": c.confidence,
                        "confidence_difference": abs(s.confidence - c.confidence),
                    })

        return contradictions

    def get_contradictions_for_claim(
        self,
        claim: str,
    ) -> list[dict[str, Any]]:
        """Get contradictions for a claim."""
        return self._detect_evidence_contradictions(claim)

    # -- Hypothesis Testing ----------------------------------------------

    def test_hypothesis(
        self,
        hypothesis_id: str,
        new_evidence_id: str,
        supports: bool,
    ) -> dict[str, Any]:
        """Test a hypothesis with new evidence.

        Args:
            hypothesis_id: Hypothesis to test
            new_evidence_id: New evidence
            supports: Whether evidence supports or contradicts

        Returns:
            Test result with updated confidence
        """
        hypothesis = self.hypotheses.get(hypothesis_id)
        evidence = self.evidence.get(new_evidence_id)

        if not hypothesis or not evidence:
            return {"error": "Hypothesis or evidence not found"}

        old_confidence = hypothesis.confidence

        # Add evidence
        self.add_evidence_to_hypothesis(
            hypothesis_id, new_evidence_id, supporting=supports
        )

        # Compute new confidence
        new_confidence = hypothesis.net_confidence()
        hypothesis.confidence = new_confidence
        hypothesis.updated_at = time.time()

        # Update status based on new confidence
        if new_confidence >= 0.8:
            hypothesis.status = "confirmed"
            self.stats["hypotheses_confirmed"] += 1
        elif new_confidence <= 0.2:
            hypothesis.status = "refuted"
            self.stats["hypotheses_refuted"] += 1
        else:
            hypothesis.status = "active"

        return {
            "hypothesis_id": hypothesis_id,
            "old_confidence": old_confidence,
            "new_confidence": new_confidence,
            "status": hypothesis.status,
            "evidence_added": new_evidence_id,
            "supports": supports,
        }

    # -- Statistics ------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        """Get reasoning statistics."""
        return {
            "evidence_collected": self.stats["evidence_collected"],
            "hypotheses_generated": self.stats["hypotheses_generated"],
            "hypotheses_confirmed": self.stats["hypotheses_confirmed"],
            "hypotheses_refuted": self.stats["hypotheses_refuted"],
            "reasoning_results": self.stats["reasoning_results"],
            "contradictions_detected": self.stats["contradictions_detected"],
            "active_hypotheses": sum(
                1 for h in self.hypotheses.values()
                if h.status == "active"
            ),
            "confirmed_hypotheses": sum(
                1 for h in self.hypotheses.values()
                if h.status == "confirmed"
            ),
            "refuted_hypotheses": sum(
                1 for h in self.hypotheses.values()
                if h.status == "refuted"
            ),
            "total_evidence": len(self.evidence),
            "created_at": self.created_at,
        }


# Global instance
_evidence_based_reasoning: EvidenceBasedReasoning | None = None


def get_evidence_based_reasoning(
    reasoning_engine: ReasoningEngine | None = None,
    world_model: WorldModel | None = None,
    persistent_memory: PersistentMemory | None = None,
    temporal_knowledge: TemporalKnowledge | None = None,
) -> EvidenceBasedReasoning:
    """Get or create the global EvidenceBasedReasoning instance."""
    global _evidence_based_reasoning
    if _evidence_based_reasoning is None:
        _evidence_based_reasoning = EvidenceBasedReasoning(
            reasoning_engine=reasoning_engine,
            world_model=world_model,
            persistent_memory=persistent_memory,
            temporal_knowledge=temporal_knowledge,
        )
    return _evidence_based_reasoning


__all__ = [
    "Evidence",
    "Hypothesis",
    "ReasoningResult",
    "EvidenceBasedReasoning",
    "get_evidence_based_reasoning",
]
