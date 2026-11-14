"""Model Router - M15 Model Registry and Router.

Capability-based routing engine for selecting the best model for each task.
Evaluates models using task compatibility, accuracy, latency, memory,
hardware requirements, context length, privacy, cost, and reliability.

Supports local models, remote providers, fallback providers, and offline
execution. Implements local-only execution policy.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..foundation.base_model import ModelTaskType, ModelType
from ..foundation.model_registry import ModelRegistry, get_model_registry


class ProviderType(str, Enum):
    """Model provider types."""
    LOCAL = "local"
    REMOTE = "remote"
    FALLBACK = "fallback"


class RoutingStrategy(str, Enum):
    """Routing strategy options."""
    BEST_ACCURACY = "best_accuracy"
    LOWEST_LATENCY = "lowest_latency"
    LOWEST_COST = "lowest_cost"
    PRIVACY_FIRST = "privacy_first"
    LOCAL_ONLY = "local_only"
    BALANCED = "balanced"


@dataclass
class ModelCapability:
    """Model capability profile for routing decisions."""
    model_id: str
    task_types: list[ModelTaskType]
    accuracy: float = 0.5  # 0-1, higher is better
    latency_ms: float = 100.0  # average inference latency
    memory_mb: float = 512.0  # memory footprint
    context_length: int = 2048  # max context tokens
    privacy_local: bool = True  # whether inference stays local
    cost_per_token: float = 0.0  # cost per token (0 = free/local)
    reliability: float = 0.95  # 0-1, higher is more reliable
    provider_type: ProviderType = ProviderType.LOCAL
    provider_name: str = "local"
    hardware_required: list[str] | None = None  # e.g. ["cuda", "avx2"]
    offline_capable: bool = True

    def __post_init__(self):
        if self.hardware_required is None:
            self.hardware_required = []


@dataclass
class RoutingDecision:
    """Result of model routing."""
    model_id: str
    model_name: str
    provider: ProviderType
    strategy: RoutingStrategy
    confidence: float  # confidence in the routing decision
    reasons: list[str]  # human-readable reasons
    fallback_model_id: str | None = None
    estimated_latency_ms: float = 0.0
    estimated_cost: float = 0.0
    fallback_used: bool = False


@dataclass
class RoutingRecord:
    """Record of a routing decision for performance tracking."""
    timestamp: float
    model_id: str
    task_type: str
    strategy: str
    actual_latency_ms: float
    actual_accuracy: float | None
    success: bool
    error: str | None = None


class ModelRouter:
    """Capability-based model routing engine.

    Selects the best model for each task based on:
    - Task compatibility (model supports the task type)
    - Accuracy (historical and estimated)
    - Latency (inference speed)
    - Memory (hardware constraints)
    - Context length (input size requirements)
    - Privacy (local vs remote inference)
    - Cost (per-token pricing)
    - Reliability (historical success rate)

    Supports local-only execution policy and fallback chains.
    """

    def __init__(self, registry: ModelRegistry | None = None):
        self.registry = registry or get_model_registry()
        self.capabilities: dict[str, ModelCapability] = {}
        self.routing_history: list[RoutingRecord] = []
        self.strategy: RoutingStrategy = RoutingStrategy.BALANCED
        self.local_only: bool = False  # local-only execution policy
        self.created_at = time.time()

        # Performance tracking per model per task type
        self._performance: dict[str, dict[str, list[float]]] = {}  # model_id -> task_type -> [latencies]

    def register_capability(self, capability: ModelCapability) -> None:
        """Register a model's capability profile."""
        self.capabilities[capability.model_id] = capability

    def get_capability(self, model_id: str) -> ModelCapability | None:
        """Get capability profile for a model."""
        return self.capabilities.get(model_id)

    def set_strategy(self, strategy: RoutingStrategy) -> None:
        """Set the default routing strategy."""
        self.strategy = strategy

    def set_local_only(self, enabled: bool) -> None:
        """Enable/disable local-only execution policy."""
        self.local_only = enabled

    def route(
        self,
        task_type: ModelTaskType,
        context_length: int = 0,
        strategy: RoutingStrategy | None = None,
        prefer_local: bool = True,
        max_latency_ms: float | None = None,
        max_cost: float | None = None,
        min_accuracy: float | None = None,
        exclude_providers: list[ProviderType] | None = None,
    ) -> RoutingDecision | None:
        """Route a task to the best available model.

        Args:
            task_type: Type of task to route
            context_length: Required context length in tokens
            strategy: Routing strategy (overrides default)
            prefer_local: Prefer local models when scores are close
            max_latency_ms: Maximum acceptable latency
            max_cost: Maximum acceptable cost
            min_accuracy: Minimum acceptable accuracy
            exclude_providers: Provider types to exclude

        Returns:
            RoutingDecision with selected model and reasoning
        """
        strategy = strategy or self.strategy
        exclude_providers = exclude_providers or []

        # Get all models that support this task type
        compatible_models = self.registry.get_by_task_type(task_type)

        # Filter by capability profile
        candidates = []
        for model in compatible_models:
            cap = self.capabilities.get(model.spec.model_id)
            if cap is None:
                # Create default capability for unregistered models
                cap = ModelCapability(
                    model_id=model.spec.model_id,
                    task_types=[task_type],
                )
                self.register_capability(cap)

            # Apply filters
            if cap.provider_type in exclude_providers:
                continue
            if self.local_only and cap.provider_type != ProviderType.LOCAL:
                continue
            if cap.context_length < context_length:
                continue
            if max_latency_ms is not None and cap.latency_ms > max_latency_ms:
                continue
            if max_cost is not None and cap.cost_per_token > max_cost:
                continue
            if min_accuracy is not None and cap.accuracy < min_accuracy:
                continue

            candidates.append((model, cap))

        if not candidates:
            return None

        # Score each candidate
        scored = []
        for model, cap in candidates:
            score, reasons = self._score_model(
                model, cap, task_type, strategy, context_length, prefer_local
            )
            scored.append((score, model, cap, reasons))

        # Sort by score (higher is better)
        scored.sort(key=lambda x: x[0], reverse=True)

        best_score, best_model, best_cap, best_reasons = scored[0]

        # Determine fallback
        fallback_id = None
        if len(scored) > 1:
            fallback_id = scored[1][1].spec.model_id

        # Record routing decision
        decision = RoutingDecision(
            model_id=best_model.spec.model_id,
            model_name=best_model.spec.name,
            provider=best_cap.provider_type,
            strategy=strategy,
            confidence=min(best_score, 1.0),
            reasons=best_reasons,
            fallback_model_id=fallback_id,
            estimated_latency_ms=best_cap.latency_ms,
            estimated_cost=best_cap.cost_per_token,
        )

        return decision

    def _score_model(
        self,
        model,
        cap: ModelCapability,
        task_type: ModelTaskType,
        strategy: RoutingStrategy,
        context_length: int,
        prefer_local: bool = True,
    ) -> tuple[float, list[str]]:
        """Score a model for a task. Returns (score, reasons)."""
        reasons = []
        score = 0.0

        # Task compatibility (base score)
        if task_type in cap.task_types:
            score += 30.0
            reasons.append(f"supports {task_type.value}")
        else:
            score += 5.0
            reasons.append(f"partial support for {task_type.value}")

        # Accuracy
        accuracy_score = cap.accuracy * 25.0
        score += accuracy_score
        reasons.append(f"accuracy={cap.accuracy:.2f}")

        # Latency (inverse - lower is better)
        latency_score = max(0, 20.0 - (cap.latency_ms / 10.0))
        score += latency_score
        reasons.append(f"latency={cap.latency_ms:.0f}ms")

        # Memory (inverse - lower is better for constrained hardware)
        memory_score = max(0, 15.0 - (cap.memory_mb / 100.0))
        score += memory_score
        reasons.append(f"memory={cap.memory_mb:.0f}MB")

        # Context length
        context_score = min(10.0, cap.context_length / 100.0)
        score += context_score
        reasons.append(f"context={cap.context_length}")

        # Privacy (local preferred)
        if cap.privacy_local:
            score += 15.0
            reasons.append("local inference")
        else:
            score += 5.0
            reasons.append("remote inference")

        # Cost (inverse - lower is better)
        cost_score = max(0, 10.0 - (cap.cost_per_token * 1000.0))
        score += cost_score
        reasons.append(f"cost={cap.cost_per_token:.6f}/token")

        # Reliability
        reliability_score = cap.reliability * 10.0
        score += reliability_score
        reasons.append(f"reliability={cap.reliability:.2f}")

        # Strategy adjustments
        if strategy == RoutingStrategy.LOCAL_ONLY and cap.provider_type == ProviderType.LOCAL:
            score += 50.0
            reasons.append("local-only preference")
        elif strategy == RoutingStrategy.PRIVACY_FIRST and cap.privacy_local:
            score += 30.0
            reasons.append("privacy-first")
        elif strategy == RoutingStrategy.LOWEST_LATENCY:
            score += (20.0 - latency_score)  # bonus for low latency
            reasons.append("latency-optimized")
        elif strategy == RoutingStrategy.LOWEST_COST:
            score += (10.0 - cost_score)  # bonus for low cost
            reasons.append("cost-optimized")
        elif strategy == RoutingStrategy.BEST_ACCURACY:
            score += (25.0 - accuracy_score)  # bonus for high accuracy
            reasons.append("accuracy-optimized")

        # Historical performance adjustment
        hist_score = self._get_historical_score(model.spec.model_id, task_type.value)
        score += hist_score
        if hist_score > 0:
            reasons.append(f"historical_performance=+{hist_score:.1f}")

        # Local preference tiebreaker
        if prefer_local and cap.privacy_local:
            score += 5.0

        return score, reasons

    def _get_historical_score(self, model_id: str, task_type: str) -> float:
        """Get historical performance bonus for a model on a task type."""
        if model_id not in self._performance:
            return 0.0
        task_perf = self._performance[model_id].get(task_type, [])
        if not task_perf:
            return 0.0
        # Average latency as a bonus (lower latency = higher score)
        avg_latency = sum(task_perf) / len(task_perf)
        return max(0, 5.0 - (avg_latency / 50.0))

    def record_routing(
        self,
        model_id: str,
        task_type: str,
        strategy: str,
        actual_latency_ms: float,
        actual_accuracy: float | None = None,
        success: bool = True,
        error: str | None = None,
    ) -> None:
        """Record the outcome of a routed inference for performance tracking."""
        record = RoutingRecord(
            timestamp=time.time(),
            model_id=model_id,
            task_type=task_type,
            strategy=strategy,
            actual_latency_ms=actual_latency_ms,
            actual_accuracy=actual_accuracy,
            success=success,
            error=error,
        )
        self.routing_history.append(record)

        # Update performance tracking
        if model_id not in self._performance:
            self._performance[model_id] = {}
        if task_type not in self._performance[model_id]:
            self._performance[model_id][task_type] = []
        self._performance[model_id][task_type].append(actual_latency_ms)

        # Keep only last 100 entries per model/task
        if len(self._performance[model_id][task_type]) > 100:
            self._performance[model_id][task_type] = self._performance[model_id][task_type][-100:]

    def get_routing_stats(self) -> dict[str, Any]:
        """Get routing statistics."""
        total = len(self.routing_history)
        if total == 0:
            return {"total_routings": 0}

        successful = sum(1 for r in self.routing_history if r.success)
        by_model = {}
        by_strategy = {}
        for r in self.routing_history:
            by_model[r.model_id] = by_model.get(r.model_id, 0) + 1
            by_strategy[r.strategy] = by_strategy.get(r.strategy, 0) + 1

        avg_latency = sum(r.actual_latency_ms for r in self.routing_history) / total

        return {
            "total_routings": total,
            "successful_routings": successful,
            "success_rate": successful / total,
            "average_latency_ms": avg_latency,
            "by_model": by_model,
            "by_strategy": by_strategy,
            "local_only": self.local_only,
            "current_strategy": self.strategy.value,
        }

    def get_fallback_chain(
        self,
        task_type: ModelTaskType,
        context_length: int = 0,
    ) -> list[RoutingDecision]:
        """Get a ranked fallback chain of models for a task."""
        strategy = self.strategy
        compatible_models = self.registry.get_by_task_type(task_type)

        candidates = []
        for model in compatible_models:
            cap = self.capabilities.get(model.spec.model_id)
            if cap is None:
                cap = ModelCapability(
                    model_id=model.spec.model_id,
                    task_types=[task_type],
                )
                self.register_capability(cap)

            if self.local_only and cap.provider_type != ProviderType.LOCAL:
                continue
            if cap.context_length < context_length:
                continue

            candidates.append((model, cap))

        # Score and sort
        scored = []
        for model, cap in candidates:
            score, reasons = self._score_model(
                model, cap, task_type, strategy, context_length, prefer_local=True
            )
            scored.append((score, model, cap, reasons))

        scored.sort(key=lambda x: x[0], reverse=True)

        chain = []
        for score, model, cap, reasons in scored:
            chain.append(RoutingDecision(
                model_id=model.spec.model_id,
                model_name=model.spec.name,
                provider=cap.provider_type,
                strategy=strategy,
                confidence=min(score, 1.0),
                reasons=reasons,
                estimated_latency_ms=cap.latency_ms,
                estimated_cost=cap.cost_per_token,
            ))

        return chain
