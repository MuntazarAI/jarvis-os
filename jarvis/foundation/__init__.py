"""JARVIS Foundation Model Research Lab (M13-M22).

Foundation Model Research Lab - builds the JARVIS family of foundation models.

Research targets:
JARVIS-LLM, JARVIS-REASONER, JARVIS-CODE, JARVIS-VISION, JARVIS-AUDIO,
JARVIS-EMBEDDING, JARVIS-RERANKER, JARVIS-WORLD, JARVIS-ACTION

Architecture research:
Decoder-only Transformers, Encoder-only Transformers, Encoder-decoder
Transformers, Vision Transformers, Mixture of Experts, State Space Models,
Hybrid neural architectures, Multimodal architectures, Retrieval-augmented
architectures.
"""

from .base_model import BaseModel, ModelConfig, ModelSpec, ModelTaskType, ModelType
from .model_registry import ModelRegistry, get_model_registry
from .evaluation import EvaluationEngine, get_evaluation_engine
from .router import ModelRouter, RoutingDecision, ModelCapability, RoutingStrategy, ProviderType
from .inference import UnifiedInferenceAPI, InferenceRequest, InferenceResponse, get_inference_api
from .benchmarks import (
    JARVISBenchmarkSuite,
    BenchmarkSuite,
    BenchmarkResult,
    LanguageBenchmark,
    ReasoningBenchmark,
    CodingBenchmark,
    MemoryBenchmark,
    PlanningBenchmark,
    AgentSystemBenchmark,
    SecurityBenchmark,
)
from .data import (
    LicenseType,
    DataQuality,
    DataSource,
    DatasetVersion,
    DataRecord,
    DatasetGovernance,
    get_dataset_governance,
    TokenizerSpec,
    BaseTokenizer,
    CharacterTokenizer,
    WordTokenizer,
    BytePairTokenizer,
    TokenizerRegistry,
    get_tokenizer_registry,
)
from .training import (
    PretrainingConfig,
    TrainingStepResult,
    Checkpoint,
    SimpleOptimizer,
    LearningRateScheduler,
    PretrainingTrainer,
    create_pretraining_config,
    FineTuningMethod,
    LoRAConfig,
    FineTuningConfig,
    FineTuningResult,
    LoRALayer,
    FineTuningEngine,
)

__all__ = [
    # Core
    "BaseModel",
    "ModelConfig",
    "ModelSpec",
    "ModelTaskType",
    "ModelType",
    "ModelRegistry",
    "get_model_registry",
    "EvaluationEngine",
    "get_evaluation_engine",
    # Router
    "ModelRouter",
    "RoutingDecision",
    "ModelCapability",
    "RoutingStrategy",
    "ProviderType",
    # Inference API (M17)
    "UnifiedInferenceAPI",
    "InferenceRequest",
    "InferenceResponse",
    "get_inference_api",
    # Benchmarks (M16)
    "JARVISBenchmarkSuite",
    "BenchmarkSuite",
    "BenchmarkResult",
    "LanguageBenchmark",
    "ReasoningBenchmark",
    "CodingBenchmark",
    "MemoryBenchmark",
    "PlanningBenchmark",
    "AgentSystemBenchmark",
    "SecurityBenchmark",
    # Data (M18-M19)
    "LicenseType",
    "DataQuality",
    "DataSource",
    "DatasetVersion",
    "DataRecord",
    "DatasetGovernance",
    "get_dataset_governance",
    "TokenizerSpec",
    "BaseTokenizer",
    "CharacterTokenizer",
    "WordTokenizer",
    "BytePairTokenizer",
    "TokenizerRegistry",
    "get_tokenizer_registry",
    # Training (M21-M22)
    "PretrainingConfig",
    "TrainingStepResult",
    "Checkpoint",
    "SimpleOptimizer",
    "LearningRateScheduler",
    "PretrainingTrainer",
    "create_pretraining_config",
    "FineTuningMethod",
    "LoRAConfig",
    "FineTuningConfig",
    "FineTuningResult",
    "LoRALayer",
    "FineTuningEngine",
]
