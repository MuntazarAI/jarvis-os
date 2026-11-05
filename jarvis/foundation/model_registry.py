"""Model Registry - manages all JARVIS foundation models.

Registry tracks all model instances, their configurations, training state,
and provides lookup by task type or model ID.
"""

from __future__ import annotations

import time
from typing import Any

from .base_model import BaseModel, ModelConfig, ModelSpec, ModelTaskType


class ModelRegistry:
    """Central registry for all JARVIS foundation models.

    Manages model lifecycle: creation, registration, retrieval by ID or task type,
    and tracking of training/evaluation state across all models.
    """

    def __init__(self) -> None:
        self._models: dict[str, BaseModel] = {}
        self._by_task_type: dict[str, list[str]] = {}  # task_type -> [model_id]
        self.created_at = time.time()

    def register(self, model: BaseModel) -> str:
        """Register a model in the registry."""
        self._models[model.spec.model_id] = model
        task_type = model.spec.task_type.value
        if task_type not in self._by_task_type:
            self._by_task_type[task_type] = []
        if model.spec.model_id not in self._by_task_type[task_type]:
            self._by_task_type[task_type].append(model.spec.model_id)
        return model.spec.model_id

    def get(self, model_id: str) -> BaseModel | None:
        """Get a model by ID."""
        return self._models.get(model_id)

    def get_by_task_type(self, task_type: ModelTaskType) -> list[BaseModel]:
        """Get all models of a given task type."""
        ids = self._by_task_type.get(task_type.value, [])
        return [self._models[mid] for mid in ids if mid in self._models]

    def list_models(self) -> list[dict[str, Any]]:
        """List all registered models with basic info."""
        result = []
        for m in self._models.values():
            mt = m.spec.model_type
            tt = m.spec.task_type
            # Handle both Enum and string values
            mt_val = mt.value if hasattr(mt, 'value') else mt
            tt_val = tt.value if hasattr(tt, 'value') else tt
            result.append({
                "model_id": m.spec.model_id,
                "name": m.spec.name,
                "model_type": mt_val,
                "task_type": tt_val,
                "is_trained": m.is_trained,
                "is_deployed": m.is_deployed,
                "parameter_count": m.get_parameter_count(),
                "max_sequence_length": m.spec.max_sequence_length,
                "vocab_size": m.spec.vocab_size,
            })
        return result

    def stats(self) -> dict[str, Any]:
        """Get registry statistics."""
        return {
            "total_models": len(self._models),
            "by_task_type": {
                task_type: len(models) for task_type, models in self._by_task_type.items()
            },
            "total_parameters": sum(m.get_parameter_count() for m in self._models.values()),
            "created_at": self.created_at,
        }

    def find_best_for_task(self, task_type: ModelTaskType) -> BaseModel | None:
        """Get the best-performing model for a task type (based on evaluation)."""
        models = self.get_by_task_type(task_type)
        if not models:
            return None
        # Return the one with highest confidence/accuracy from evaluation
        best = None
        best_confidence = -1.0
        for m in models:
            eval_results = m.evaluation_results
            for eval_name, eval_data in eval_results.items():
                conf = eval_data.get("confidence", eval_data.get("accuracy", 0.0))
                if conf > best_confidence:
                    best_confidence = conf
                    best = m
        return best or models[0]


# Global registry instance
_global_registry: ModelRegistry | None = None


def get_model_registry() -> ModelRegistry:
    """Get or create the global model registry."""
    global _global_registry
    if _global_registry is None:
        _global_registry = ModelRegistry()
    return _global_registry


__all__ = [
    "ModelRegistry",
    "get_model_registry",
]
