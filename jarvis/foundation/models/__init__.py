"""JARVIS Foundation Model Architectures (M14 - Unified Model Runtime).

Neural network implementations in pure Python for CPU-friendly inference.
Supports decoder-only Transformers, Mixture of Experts, and hybrid architectures.

All implementations are research-grade reference implementations suitable for
small-scale experiments on CPU hardware. No GPU dependencies required.
"""

from .neural import (
    Tensor,
    Linear,
    ReLU,
    GELU,
    Softmax,
    LayerNorm,
    Embedding,
    MultiHeadAttention,
    TransformerBlock,
    Sequential,
    dropout,
    zeros,
    ones,
    randn,
    xavier_init,
    he_init,
)

from .decoder import DecoderOnlyTransformer, JARVIS_LLM_Model
from .moe import MoELayer, MoETransformerBlock, MoETransformer

from .multimodal import (
    EmbeddingVector,
    MultimodalEmbedder,
    MultimodalRetrieval,
    get_multimodal_embedder,
    get_multimodal_retrieval,
)
from .sensor_fusion import (
    SensorReading,
    FusedResult,
    SensorFusion,
    get_sensor_fusion,
)

__all__ = [
    # Neural
    "Tensor",
    "Linear",
    "ReLU",
    "GELU",
    "Softmax",
    "LayerNorm",
    "Embedding",
    "MultiHeadAttention",
    "TransformerBlock",
    "Sequential",
    "dropout",
    "zeros",
    "ones",
    "randn",
    "xavier_init",
    "he_init",
    # Decoder
    "DecoderOnlyTransformer",
    "JARVIS_LLM_Model",
    # MoE
    "MoELayer",
    "MoETransformerBlock",
    "MoETransformer",
    # Multimodal (M26)
    "EmbeddingVector",
    "MultimodalEmbedder",
    "MultimodalRetrieval",
    "get_multimodal_embedder",
    "get_multimodal_retrieval",
    # Sensor Fusion (M27)
    "SensorReading",
    "FusedResult",
    "SensorFusion",
    "get_sensor_fusion",
]
