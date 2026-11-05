"""Unified Inference API - M17 Model Registry and Router.

The Unified Inference API is the central integration point for all JARVIS
foundation models. It connects:

- Foundation models (decoder transformer, MoE transformer)
- Model Router (capability-based selection)
- Model Registry (model lifecycle)
- Benchmark Suite (evaluation)
- Cognitive Engine (reasoning, planning)
- World Model (state, causality, prediction)
- Policy Engine (security governance)

Provides a simple, model-independent interface:
- Local-first execution (default)
- Capability-based automatic routing
- Fallback chains for reliability
- Full audit trail via Policy Engine
- Resource-aware model selection for constrained hardware
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from .base_model import ModelTaskType
from .model_registry import ModelRegistry, get_model_registry
from .router import (
    ModelRouter,
    ModelCapability,
    RoutingStrategy,
    ProviderType,
    get_model_registry as _get_registry,
)
from .benchmarks import JARVISBenchmarkSuite, BenchmarkResult


@dataclass
class InferenceRequest:
    """Request for model inference."""
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    task_type: ModelTaskType = ModelTaskType.GENERAL_LANGUAGE
    input_text: str = ""
    input_ids: list[int] | None = None
    context_length: int = 0
    strategy: RoutingStrategy = RoutingStrategy.BALANCED
    prefer_local: bool = True
    max_latency_ms: float | None = None
    max_cost: float | None = None
    min_accuracy: float | None = None
    exclude_providers: list[ProviderType] | None = None
    temperature: float = 0.7
    top_p: float = 0.9
    max_new_tokens: int = 50
    seed: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class InferenceResponse:
    """Response from model inference."""
    request_id: str
    model_id: str
    model_name: str
    provider: ProviderType
    strategy: RoutingStrategy
    output_text: str
    output_ids: list[int]
    confidence: float
    routing_reasons: list[str]
    latency_ms: float
    estimated_cost: float
    success: bool = True
    error: str | None = None
    fallback_used: bool = False
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "model_id": self.model_id,
            "model_name": self.model_name,
            "provider": self.provider.value,
            "strategy": self.strategy.value,
            "output_text": self.output_text,
            "output_ids": self.output_ids,
            "confidence": self.confidence,
            "routing_reasons": self.routing_reasons,
            "latency_ms": self.latency_ms,
            "estimated_cost": self.estimated_cost,
            "success": self.success,
            "error": self.error,
            "fallback_used": self.fallback_used,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


class UnifiedInferenceAPI:
    """Unified inference API for JARVIS foundation models.

    The single entry point for all model inference in JARVIS-OS.
    Automatically routes requests to the best available model based on
    task type, capabilities, and routing strategy.

    Design principles:
    - Local-first: prefers local models by default
    - Model-independent: works with any registered model
    - Observable: full routing and performance audit trail
    - Resilient: fallback chains for reliability
    - Resource-aware: respects hardware constraints
    """

    def __init__(
        self,
        registry: ModelRegistry | None = None,
        router: ModelRouter | None = None,
        benchmark_suite: JARVISBenchmarkSuite | None = None,
        policy_engine=None,
        cognitive_engine=None,
        world_model=None,
    ):
        self.registry = registry or get_model_registry()
        self.router = router or ModelRouter(self.registry)
        self.benchmark_suite = benchmark_suite or JARVISBenchmarkSuite()
        self.policy_engine = policy_engine
        self.cognitive_engine = cognitive_engine
        self.world_model = world_model

        self.inference_history: list[InferenceResponse] = []
        self.model_wrappers: dict[str, Any] = {}  # model_id -> model wrapper
        self.local_only: bool = False
        self.created_at = time.time()

        # Performance tracking
        self.total_requests = 0
        self.successful_requests = 0
        self.fallback_requests = 0
        self.total_latency_ms = 0.0

    def register_model_wrapper(
        self,
        model_id: str,
        wrapper: Any,
        capability: ModelCapability,
    ) -> None:
        """Register a model wrapper with its capability profile.

        A model wrapper must provide:
        - generate(input_ids, max_new_tokens, temperature, top_p, seed) -> dict
        - encode(text) -> list[int]
        - decode(token_ids) -> str
        - get_parameter_count() -> int
        """
        self.model_wrappers[model_id] = wrapper
        self.router.register_capability(capability)

    def set_local_only(self, enabled: bool) -> None:
        """Enable/disable local-only execution policy."""
        self.local_only = enabled
        self.router.set_local_only(enabled)

    def set_strategy(self, strategy: RoutingStrategy) -> None:
        """Set default routing strategy."""
        self.router.set_strategy(strategy)

    def infer(
        self,
        request: InferenceRequest | None = None,
        **kwargs,
    ) -> InferenceResponse:
        """Run inference on a request.

        Args:
            request: InferenceRequest (or create from kwargs)
            **kwargs: Override request fields

        Returns:
            InferenceResponse with model output and routing info
        """
        if request is None:
            request = InferenceRequest(**kwargs)
        else:
            # Apply kwargs as overrides
            for key, value in kwargs.items():
                if hasattr(request, key):
                    setattr(request, key, value)

        start_time = time.time()
        self.total_requests += 1

        # Policy check (if policy engine available)
        if self.policy_engine:
            policy_allowed = self._check_policy(request)
            if not policy_allowed:
                return InferenceResponse(
                    request_id=request.request_id,
                    model_id="",
                    model_name="",
                    provider=ProviderType.LOCAL,
                    strategy=request.strategy,
                    output_text="",
                    output_ids=[],
                    confidence=0.0,
                    routing_reasons=["policy_engine: denied"],
                    latency_ms=(time.time() - start_time) * 1000,
                    estimated_cost=0.0,
                    success=False,
                    error="Policy engine denied inference request",
                )

        # Route to best model
        decision = self.router.route(
            task_type=request.task_type,
            context_length=request.context_length,
            strategy=request.strategy,
            prefer_local=request.prefer_local,
            max_latency_ms=request.max_latency_ms,
            max_cost=request.max_cost,
            min_accuracy=request.min_accuracy,
            exclude_providers=request.exclude_providers,
        )

        if decision is None:
            return InferenceResponse(
                request_id=request.request_id,
                model_id="",
                model_name="",
                provider=ProviderType.LOCAL,
                strategy=request.strategy,
                output_text="",
                output_ids=[],
                confidence=0.0,
                routing_reasons=["no_model_available"],
                latency_ms=(time.time() - start_time) * 1000,
                estimated_cost=0.0,
                success=False,
                error="No compatible model available for task",
            )

        # Get model wrapper
        wrapper = self.model_wrappers.get(decision.model_id)
        if wrapper is None:
            # Try fallback
            if decision.fallback_model_id:
                wrapper = self.model_wrappers.get(decision.fallback_model_id)
                if wrapper:
                    decision.model_id = decision.fallback_model_id
                    decision.fallback_used = True
                    self.fallback_requests += 1

        if wrapper is None:
            return InferenceResponse(
                request_id=request.request_id,
                model_id=decision.model_id,
                model_name=decision.model_name,
                provider=decision.provider,
                strategy=decision.strategy,
                output_text="",
                output_ids=[],
                confidence=decision.confidence,
                routing_reasons=decision.reasons + ["model_wrapper_not_found"],
                latency_ms=(time.time() - start_time) * 1000,
                estimated_cost=decision.estimated_cost,
                success=False,
                error="Model wrapper not found",
            )

        # Encode input
        if request.input_ids is not None:
            input_ids = request.input_ids
        else:
            input_ids = wrapper.encode(request.input_text)

        # Truncate to context length
        if request.context_length > 0:
            input_ids = input_ids[-request.context_length:]

        # Run inference
        try:
            result = wrapper.generate(
                input_ids,
                max_new_tokens=request.max_new_tokens,
                temperature=request.temperature,
                top_p=request.top_p,
                seed=request.seed,
            )

            output_ids = result.get("generated_ids", input_ids)
            output_text = result.get(
                "generated_text",
                wrapper.decode(output_ids[len(input_ids):])
            )

            latency_ms = (time.time() - start_time) * 1000
            self.total_latency_ms += latency_ms
            self.successful_requests += 1

            response = InferenceResponse(
                request_id=request.request_id,
                model_id=decision.model_id,
                model_name=decision.model_name,
                provider=decision.provider,
                strategy=decision.strategy,
                output_text=output_text,
                output_ids=output_ids,
                confidence=decision.confidence,
                routing_reasons=decision.reasons,
                latency_ms=round(latency_ms, 2),
                estimated_cost=decision.estimated_cost,
                success=True,
                fallback_used=decision.fallback_used,
                metadata=request.metadata,
            )

            # Record routing outcome
            self.router.record_routing(
                model_id=decision.model_id,
                task_type=request.task_type.value,
                strategy=request.strategy.value,
                actual_latency_ms=latency_ms,
                success=True,
            )

            # Record in history
            self.inference_history.append(response)

            # Update world model if available
            if self.world_model:
                self._update_world_model(request, response)

            return response

        except Exception as exc:  # noqa: BLE001
            latency_ms = (time.time() - start_time) * 1000
            self.router.record_routing(
                model_id=decision.model_id,
                task_type=request.task_type.value,
                strategy=request.strategy.value,
                actual_latency_ms=latency_ms,
                success=False,
                error=str(exc),
            )

            return InferenceResponse(
                request_id=request.request_id,
                model_id=decision.model_id,
                model_name=decision.model_name,
                provider=decision.provider,
                strategy=decision.strategy,
                output_text="",
                output_ids=[],
                confidence=decision.confidence,
                routing_reasons=decision.reasons + [f"error: {exc}"],
                latency_ms=round(latency_ms, 2),
                estimated_cost=decision.estimated_cost,
                success=False,
                error=str(exc),
                fallback_used=decision.fallback_used,
            )

    def infer_text(
        self,
        text: str,
        task_type: ModelTaskType = ModelTaskType.GENERAL_LANGUAGE,
        strategy: RoutingStrategy = RoutingStrategy.BALANCED,
        max_new_tokens: int = 50,
        temperature: float = 0.7,
        top_p: float = 0.9,
        prefer_local: bool = True,
        **kwargs,
    ) -> InferenceResponse:
        """Convenience method for text-to-text inference."""
        return self.infer(
            InferenceRequest(
                task_type=task_type,
                input_text=text,
                strategy=strategy,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                top_p=top_p,
                prefer_local=prefer_local,
                **kwargs,
            )
        )

    def _check_policy(self, request: InferenceRequest) -> bool:
        """Check if inference request is allowed by policy engine."""
        if self.policy_engine is None:
            return True
        try:
            return self.policy_engine.check_inference(request)
        except Exception:  # noqa: BLE001
            return False

    def _update_world_model(
        self,
        request: InferenceRequest,
        response: InferenceResponse,
    ) -> None:
        """Update world model with inference results."""
        if self.world_model is None:
            return
        try:
            # Record the inference as an event in the world model
            self.world_model.record_event(
                event_id=response.request_id,
                event_type="model_inference",
                description=f"Inference: {request.task_type.value} -> {response.model_name}",
                source="unified_inference_api",
                confidence=response.confidence,
            )
        except Exception:  # noqa: BLE001
            pass

    def get_stats(self) -> dict[str, Any]:
        """Get inference API statistics."""
        avg_latency = (
            self.total_latency_ms / self.successful_requests
            if self.successful_requests > 0
            else 0.0
        )
        return {
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "fallback_requests": self.fallback_requests,
            "success_rate": (
                self.successful_requests / self.total_requests
                if self.total_requests > 0 else 0.0
            ),
            "fallback_rate": (
                self.fallback_requests / self.total_requests
                if self.total_requests > 0 else 0.0
            ),
            "average_latency_ms": round(avg_latency, 2),
            "local_only": self.local_only,
            "registered_wrappers": list(self.model_wrappers.keys()),
            "router_stats": self.router.get_routing_stats(),
        }

    def get_history(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Get inference history."""
        history = self.inference_history[-limit:] if limit else self.inference_history
        return [r.to_dict() for r in history]

    def benchmark_model(
        self,
        model_id: str,
        language_preds: list[str],
        language_refs: list[str],
        reasoning_preds: list[str],
        reasoning_refs: list[str],
        coding_preds: list[str],
        coding_refs: list[str],
        hardware: dict[str, Any] | None = None,
    ) -> dict[str, BenchmarkResult]:
        """Run full benchmark suite on a model."""
        return self.benchmark_suite.run_all(
            model_id=model_id,
            language_preds=language_preds,
            language_refs=language_refs,
            reasoning_preds=reasoning_preds,
            reasoning_refs=reasoning_refs,
            coding_preds=coding_preds,
            coding_refs=coding_refs,
            memory_preds=[],
            memory_refs=[],
            planning_successes=[],
            planning_constraints=[],
            planning_efficiency=[],
            planning_steps=[],
            agent_coordination=[],
            agent_tools=[],
            agent_recovery=[],
            sec_permissions=[],
            sec_attacks=[],
            sec_audit=[],
            hardware=hardware,
        )

    def get_model_report(self, model_id: str) -> dict[str, Any]:
        """Get benchmark report for a model."""
        return self.benchmark_suite.get_model_report(model_id)


# Global inference API instance
_inference_api: UnifiedInferenceAPI | None = None


def get_inference_api(
    registry: ModelRegistry | None = None,
    router: ModelRouter | None = None,
    benchmark_suite: JARVISBenchmarkSuite | None = None,
) -> UnifiedInferenceAPI:
    """Get or create the global Unified Inference API."""
    global _inference_api
    if _inference_api is None:
        _inference_api = UnifiedInferenceAPI(
            registry=registry,
            router=router,
            benchmark_suite=benchmark_suite,
        )
    return _inference_api


__all__ = [
    "InferenceRequest",
    "InferenceResponse",
    "UnifiedInferenceAPI",
    "get_inference_api",
]
