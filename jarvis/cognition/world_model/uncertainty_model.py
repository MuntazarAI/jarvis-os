"""Uncertainty Model - M13 World Model Component.

Manages uncertainty quantification for beliefs, predictions, and
observations in the world model. Supports multiple uncertainty
types: epistemic (model uncertainty), aleatoric (data uncertainty),
and ambiguity (representation uncertainty).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class UncertaintyEstimate:
    """Represents uncertainty about a belief or prediction."""
    estimate_id: str
    target_id: str
    target_type: str  # "object", "event", "belief", "prediction"
    uncertainty_type: str  # "epistemic", "aleatoric", "ambiguity"
    value: float  # 0.0 (certain) to 1.0 (completely uncertain)
    confidence: float = 0.5  # Confidence in the uncertainty estimate
    timestamp: float = field(default_factory=time.time)
    source: str = "model"
    reasoning: str = ""
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "estimate_id": self.estimate_id,
            "target_id": self.target_id,
            "target_type": self.target_type,
            "uncertainty_type": self.uncertainty_type,
            "value": self.value,
            "confidence": self.confidence,
            "timestamp": self.timestamp,
            "source": self.source,
            "reasoning": self.reasoning,
            "context": self.context,
        }


class UncertaintyModel:
    """Manages uncertainty estimates for beliefs, predictions, and
    observations in the world model.

    Supports multiple types of uncertainty:
    - Epistemic: Uncertainty due to lack of knowledge
    - Aleatoric: Uncertainty due to inherent randomness
    - Ambiguity: Uncertainty due to ambiguous or conflicting evidence
    """

    def __init__(self) -> None:
        self.uncertainties: dict[str, UncertaintyEstimate] = {}
        self.created_at = time.time()

    def add_uncertainty(self, estimate: UncertaintyEstimate) -> None:
        """Add or update an uncertainty estimate."""
        self.uncertainties[estimate.estimate_id] = estimate

    def get_uncertainty(self, estimate_id: str) -> UncertaintyEstimate | None:
        """Get an uncertainty estimate by ID."""
        return self.uncertainties.get(estimate_id)

    def get_uncertainties_for_target(self, target_id: str) -> list[UncertaintyEstimate]:
        """Get all uncertainty estimates for a target."""
        return [e for e in self.uncertainties.values()
                if e.target_id == target_id]

    def get_high_uncertainty(self, threshold: float = 0.7) -> list[UncertaintyEstimate]:
        """Get all estimates with uncertainty above threshold."""
        return [e for e in self.uncertainties.values()
                if e.value >= threshold]

    def update_uncertainty(self, target_id: str, target_type: str,
                           value: float,
                           uncertainty_type: str = "epistemic",
                           confidence: float = 0.5,
                           source: str = "model",
                           reasoning: str = "",
                           context: dict[str, Any] | None = None) -> UncertaintyEstimate:
        """Create or update an uncertainty estimate."""
        estimate_id = f"unc-{len(self.uncertainties):06d}"
        estimate = UncertaintyEstimate(
            estimate_id=estimate_id,
            target_id=target_id,
            target_type=target_type,
            uncertainty_type=uncertainty_type,
            value=value,
            confidence=confidence,
            source=source,
            reasoning=reasoning,
            context=context or {},
        )
        self.uncertainties[estimate_id] = estimate
        return estimate

    def aggregate_uncertainty(self, target_id: str) -> dict[str, Any]:
        """Aggregate all uncertainty estimates for a target."""
        estimates = self.get_uncertainties_for_target(target_id)
        if not estimates:
            return {
                "target_id": target_id,
                "overall_uncertainty": 0.0,
                "max_uncertainty": 0.0,
                "min_uncertainty": 0.0,
                "average_uncertainty": 0.0,
                "count": 0,
                "by_type": {},
            }

        values = [e.value for e in estimates]
        by_type: dict[str, list[float]] = {}
        for e in estimates:
            by_type.setdefault(e.uncertainty_type, []).append(e.value)

        return {
            "target_id": target_id,
            "overall_uncertainty": max(values),  # Conservative: take max
            "max_uncertainty": max(values),
            "min_uncertainty": min(values),
            "average_uncertainty": sum(values) / len(values),
            "count": len(values),
            "by_type": {
                t: sum(vs) / len(vs) for t, vs in by_type.items()
            },
        }

    def get_stats(self) -> dict[str, Any]:
        """Get statistics about uncertainty estimates."""
        if not self.uncertainties:
            return {
                "total_estimates": 0,
                "by_type": {},
                "average_uncertainty": 0.0,
                "max_uncertainty": 0.0,
                "high_uncertainty_count": 0,
            }

        values = [e.value for e in self.uncertainties.values()]
        by_type: dict[str, list[float]] = {}
        for e in self.uncertainties.values():
            by_type.setdefault(e.uncertainty_type, []).append(e.value)

        return {
            "total_estimates": len(self.uncertainties),
            "by_type": {
                t: {
                    "count": len(vs),
                    "average": sum(vs) / len(vs),
                    "max": max(vs),
                }
                for t, vs in by_type.items()
            },
            "average_uncertainty": sum(values) / len(values),
            "max_uncertainty": max(values),
            "high_uncertainty_count": sum(1 for v in values if v > 0.7),
        }


# Global uncertainty model instance
_uncertainty_model: UncertaintyModel | None = None


def get_uncertainty_model() -> UncertaintyModel:
    """Get or create the global uncertainty model."""
    global _uncertainty_model
    if _uncertainty_model is None:
        _uncertainty_model = UncertaintyModel()
    return _uncertainty_model


__all__ = [
    "UncertaintyEstimate",
    "UncertaintyModel",
    "get_uncertainty_model",
]
