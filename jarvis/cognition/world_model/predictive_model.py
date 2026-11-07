"""Predictive Model - M13 World Model Component.

Predictive model for forecasting future states based on current
observations and historical data. Supports probabilistic forecasting
and scenario generation.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Prediction:
    """Represents a prediction about future state."""
    prediction_id: str
    target_id: str  # ID of entity/event being predicted
    target_type: str  # "object" or "event"
    predicted_attribute: str  # Attribute being predicted
    predicted_value: Any
    confidence: float  # 0.0 to 1.0
    time_horizon: float  # Seconds into the future
    timestamp: float = field(default_factory=time.time)
    source: str = "model"
    supporting_evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "prediction_id": self.prediction_id,
            "target_id": self.target_id,
            "target_type": self.target_type,
            "predicted_attribute": self.predicted_attribute,
            "predicted_value": self.predicted_value,
            "confidence": self.confidence,
            "time_horizon": self.time_horizon,
            "timestamp": self.timestamp,
            "source": self.source,
            "supporting_evidence": self.supporting_evidence,
        }


class PredictiveModel:
    """Predictive model for forecasting future states.

    Uses current observations and historical data to predict future
    states of objects and events in the world.
    """

    def __init__(self) -> None:
        self.predictions: dict[str, Prediction] = {}
        self.created_at = time.time()

    def predict(self, target_id: str, target_type: str,
                attribute: str, predicted_value: Any,
                confidence: float, time_horizon: float,
                source: str = "model",
                evidence: list[str] | None = None) -> Prediction:
        """Make a prediction about a future state."""
        prediction = Prediction(
            prediction_id=f"pred-{len(self.predictions):06d}",
            target_id=target_id,
            target_type=target_type,
            predicted_attribute=attribute,
            predicted_value=predicted_value,
            confidence=confidence,
            time_horizon=time_horizon,
            source=source,
            supporting_evidence=evidence or [],
        )
        self.predictions[prediction.prediction_id] = prediction
        return prediction

    def get_prediction(self, prediction_id: str) -> Prediction | None:
        """Get a prediction by ID."""
        return self.predictions.get(prediction_id)

    def get_predictions_for_target(self, target_id: str) -> list[Prediction]:
        """Get all predictions for a specific target."""
        return [p for p in self.predictions.values()
                if p.target_id == target_id]

    def get_active_predictions(self, current_time: float | None = None) -> list[Prediction]:
        """Get all active (not yet expired) predictions."""
        if current_time is None:
            current_time = time.time()
        return [p for p in self.predictions.values()
                if p.timestamp + p.time_horizon > current_time]

    def evaluate_prediction(self, prediction_id: str,
                            actual_value: Any,
                            actual_time: float) -> dict[str, Any]:
        """Evaluate a prediction against actual outcome."""
        prediction = self.predictions.get(prediction_id)
        if prediction is None:
            return {"error": "prediction not found"}

        accuracy = 1.0 - abs(float(predicted_value) - float(actual_value)) / max(abs(float(predicted_value)), 1.0)
        accuracy = max(0.0, min(1.0, accuracy))

        return {
            "prediction_id": prediction_id,
            "predicted_value": prediction.predicted_value,
            "actual_value": actual_value,
            "accuracy": accuracy,
            "confidence": prediction.confidence,
            "time_horizon": prediction.time_horizon,
            "actual_time": actual_time,
            "predicted_time": prediction.timestamp + prediction.time_horizon,
        }

    def get_stats(self) -> dict[str, Any]:
        """Get prediction statistics."""
        return {
            "total_predictions": len(self.predictions),
            "active_predictions": len(self.get_active_predictions()),
            "by_target_type": {
                t: len([p for p in self.predictions.values()
                        if p.target_type == t])
                for t in set(p.target_type for p in self.predictions.values())
            },
        }


# Global predictive model instance
_predictive_model: PredictiveModel | None = None


def get_predictive_model() -> PredictiveModel:
    """Get or create the global predictive model."""
    global _predictive_model
    if _predictive_model is None:
        _predictive_model = PredictiveModel()
    return _predictive_model


__all__ = [
    "Prediction",
    "PredictiveModel",
    "get_predictive_model",
]
