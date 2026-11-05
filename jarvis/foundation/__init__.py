"""JARVIS Foundation Model Research Lab (M13).

Foundation Model Research Lab - builds the JARVIS family of foundation models.

Research targets (not yet implemented - research roadmap):

JARVIS-LLM   - General-purpose language model
JARVIS-REASONER - Advanced problem decomposition, inference, verification, reasoning
JARVIS-CODE  - Programming and software engineering model
JARVIS-VISION - Visual perception and image understanding model
JARVIS-AUDIO - Audio perception and speech understanding model
JARVIS-EMBEDDING - Semantic representation and retrieval model
JARVIS-RERANKER - Knowledge relevance ranking model
JARVIS-WORLD   - Environmental and temporal representations model
JARVIS-ACTION  - Structured action and tool-selection model

Architecture research targets:
- Decoder-only Transformers
- Encoder-only Transformers
- Encoder-decoder Transformers
- Vision Transformers
- Mixture of Experts
- State Space Models
- Hybrid neural architectures
- Multimodal architectures
- Retrieval-augmented architectures

Each experiment must record:
- Research hypothesis
- Architecture
- Dataset
- Training configuration
- Hardware
- Parameters
- Training duration
- Evaluation methodology
- Results
- Limitations
- Reproducibility information
"""

from .base_model import BaseModel, ModelConfig, ModelSpec, ModelTaskType, ModelType
from .model_registry import ModelRegistry, get_model_registry
from .training import TrainingEngine, TrainingConfig
from .evaluation import EvaluationEngine, get_evaluation_engine
from .router import ModelRouter, RoutingDecision, ModelCapability, RoutingStrategy, ProviderType

__all__ = [
    "BaseModel",
    "ModelConfig",
    "ModelSpec",
    "ModelTaskType",
    "ModelType",
    "ModelRegistry",
    "get_model_registry",
    "TrainingEngine",
    "TrainingConfig",
    "EvaluationEngine",
    "get_evaluation_engine",
    "ModelRouter",
    "RoutingDecision",
    "ModelCapability",
    "RoutingStrategy",
    "ProviderType",
]
