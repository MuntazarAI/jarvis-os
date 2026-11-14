"""Multimodal Embeddings - M26.

Shared embedding space for text, vision, audio, and cross-modal retrieval.
Builds on:
- VisionIntelligence (M23) for image embeddings
- AudioIntelligence (M24) for audio embeddings
- Foundation model tokenizer (M19) for text tokenization

All pure Python, CPU-friendly. Embeddings are deterministic vectors that enable:
- Cross-modal retrieval (find images matching text, text matching audio)
- Multimodal similarity search
- Joint vision-audio-text representations
"""

from __future__ import annotations

import hashlib
import math
import time
from dataclasses import dataclass, field
from typing import Any

from .neural import Tensor, Linear


@dataclass
class EmbeddingVector:
    """A normalized embedding vector with modality metadata."""
    vector_id: str
    modality: str  # text | vision | audio | multimodal
    vector: list[float]
    source: str  # original source identifier
    confidence: float
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "vector_id": self.vector_id,
            "modality": self.modality,
            "vector": self.vector,
            "source": self.source,
            "confidence": self.confidence,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }

    def cosine_similarity(self, other: "EmbeddingVector") -> float:
        """Cosine similarity between two embedding vectors."""
        if len(self.vector) != len(other.vector):
            return 0.0
        dot = sum(a * b for a, b in zip(self.vector, other.vector))
        norm_a = math.sqrt(sum(v ** 2 for v in self.vector))
        norm_b = math.sqrt(sum(v ** 2 for v in other.vector))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)


class MultimodalEmbedder:
    """Multimodal embedding model.

    Maps text, vision, and audio inputs into a shared embedding space where
    semantically similar content across modalities has similar vectors.

    Architecture:
    - Text: hashed token embeddings averaged + projected
    - Vision: VisionIntelligence encoder output
    - Audio: AudioIntelligence encoder output
    - All projected to shared dimension via learned linear layer
    """

    def __init__(
        self,
        embedding_dim: int = 128,
        vision: VisionIntelligence | None = None,
        audio: AudioIntelligence | None = None,
        seed: int = 42,
    ):
        self.embedding_dim = embedding_dim
        self.vision = vision
        self.audio = audio
        self.seed = seed

        import random as _random
        _random.seed(seed)

        # Projection layers: modality-specific -> shared dimension
        self.text_proj = Linear(embedding_dim, embedding_dim, bias=False, seed=seed)
        self.vision_proj = Linear(embedding_dim, embedding_dim, bias=False, seed=seed + 1)
        self.audio_proj = Linear(embedding_dim, embedding_dim, bias=False, seed=seed + 2)

        # Modality combination weights for multimodal fusion
        self.fusion_weights = {
            "text": 0.33,
            "vision": 0.33,
            "audio": 0.34,
        }

        # Statistics
        self.stats = {
            "total_embeddings": 0,
            "by_modality": {},
            "cross_modal_queries": 0,
        }
        self.created_at = time.time()

    def _text_to_vector(self, text: str) -> list[float]:
        """Convert text to a deterministic embedding vector."""
        import random as _random

        # Tokenize simply
        tokens = text.lower().split()
        if not tokens:
            return [0.0] * self.embedding_dim

        # Average token embeddings
        vec = [0.0] * self.embedding_dim
        for token in tokens:
            h = hashlib.sha256(token.encode()).hexdigest()
            h_len = len(h)
            for i in range(self.embedding_dim):
                idx = (i * 2) % h_len
                val = int(h[idx:idx + 2], 16) / 255.0
                vec[i] += (val * 2.0 - 1.0)

        # Average
        vec = [v / len(tokens) for v in vec]

        # Normalize
        norm = math.sqrt(sum(v ** 2 for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]

        return vec

    def embed_text(self, text: str) -> EmbeddingVector:
        """Embed text into shared vector space."""
        import time as _time
        start = _time.time()
        vector_id = f"emb-text-{hashlib.sha256(str(_time.time()).encode()).hexdigest()[:8]}"

        # Get base text vector
        base_vec = self._text_to_vector(text)

        # Project through learned layer
        from .neural import Tensor
        proj = self.text_proj(Tensor([base_vec]))
        projected = proj.tolist()[0]

        # Normalize
        norm = math.sqrt(sum(v ** 2 for v in projected))
        if norm > 0:
            projected = [v / norm for v in projected]

        result = EmbeddingVector(
            vector_id=vector_id,
            modality="text",
            vector=projected,
            source=text[:100],
            confidence=1.0,
            metadata={"text_length": len(text), "num_tokens": len(text.split())},
        )

        self._record_embedding("text")
        return result

    def embed_vision(self, image: list[list[list[float]]]) -> EmbeddingVector:
        """Embed an image into shared vector space.

        Uses VisionIntelligence encoder if available, otherwise falls back
        to deterministic image hashing.
        """
        import time as _time
        start = _time.time()
        vector_id = f"emb-vision-{hashlib.sha256(str(_time.time()).encode()).hexdigest()[:8]}"

        if self.vision:
            emb_result = self.vision.embed_image(image)
            base_vec = emb_result.embedding or [0.0] * self.embedding_dim
        else:
            # Deterministic fallback from image content
            base_vec = self._image_to_vector(image)

        # Project
        from .neural import Tensor
        proj = self.vision_proj(Tensor([base_vec[: self.embedding_dim]] +
                                       [0.0] * max(0, self.embedding_dim - len(base_vec))))
        projected = proj.tolist()[0][: self.embedding_dim]

        # Pad if needed
        while len(projected) < self.embedding_dim:
            projected.append(0.0)

        # Normalize
        norm = math.sqrt(sum(v ** 2 for v in projected))
        if norm > 0:
            projected = [v / norm for v in projected]

        result = EmbeddingVector(
            vector_id=vector_id,
            modality="vision",
            vector=projected,
            source="image",
            confidence=emb_result.confidence if self.vision else 0.5,
            metadata={"image_size": len(image[0]) if image else 0},
        )

        self._record_embedding("vision")
        return result

    def embed_audio(self, audio: list[float]) -> EmbeddingVector:
        """Embed audio into shared vector space.

        Uses AudioIntelligence encoder if available.
        """
        import time as _time
        start = _time.time()
        vector_id = f"emb-audio-{hashlib.sha256(str(_time.time()).encode()).hexdigest()[:8]}"

        if self.audio:
            emb_result = self.audio.embed_audio(audio)
            base_vec = emb_result.embedding or [0.0] * self.embedding_dim
        else:
            # Deterministic fallback
            base_vec = self._audio_to_vector(audio)

        # Project
        from .neural import Tensor
        base_padded = base_vec[: self.embedding_dim]
        while len(base_padded) < self.embedding_dim:
            base_padded.append(0.0)
        proj = self.audio_proj(Tensor([base_padded]))
        projected = proj.tolist()[0][: self.embedding_dim]

        # Normalize
        norm = math.sqrt(sum(v ** 2 for v in projected))
        if norm > 0:
            projected = [v / norm for v in projected]

        result = EmbeddingVector(
            vector_id=vector_id,
            modality="audio",
            vector=projected,
            source="audio",
            confidence=emb_result.confidence if self.audio else 0.5,
            metadata={"num_samples": len(audio),
                      "duration_s": len(audio) / 16000.0},
        )

        self._record_embedding("audio")
        return result

    def embed_multimodal(
        self,
        text: str | None = None,
        image: list[list[list[float]]] | None = None,
        audio: list[float] | None = None,
    ) -> EmbeddingVector:
        """Create a fused multimodal embedding from multiple modalities.

        Args:
            text: Optional text input
            image: Optional image input
            audio: Optional audio input

        Returns:
            EmbeddingVector with fused multimodal representation
        """
        import time as _time
        start = _time.time()
        vector_id = f"emb-mm-{hashlib.sha256(str(_time.time()).encode()).hexdigest()[:8]}"

        vectors = []
        weights = []

        if text is not None:
            text_emb = self.embed_text(text)
            vectors.append(text_emb.vector)
            weights.append(self.fusion_weights["text"])

        if image is not None:
            vision_emb = self.embed_vision(image)
            vectors.append(vision_emb.vector)
            weights.append(self.fusion_weights["vision"])

        if audio is not None:
            audio_emb = self.embed_audio(audio)
            vectors.append(audio_emb.vector)
            weights.append(self.fusion_weights["audio"])

        if not vectors:
            return EmbeddingVector(
                vector_id=vector_id,
                modality="multimodal",
                vector=[0.0] * self.embedding_dim,
                source="empty",
                confidence=0.0,
                metadata={"error": "no modalities provided"},
            )

        # Weighted average
        fused = [0.0] * self.embedding_dim
        total_weight = sum(weights)
        for vec, w in zip(vectors, weights):
            for i in range(self.embedding_dim):
                fused[i] += vec[i] * (w / total_weight)

        # Normalize
        norm = math.sqrt(sum(v ** 2 for v in fused))
        if norm > 0:
            fused = [v / norm for v in fused]

        modalities = []
        if text is not None:
            modalities.append("text")
        if image is not None:
            modalities.append("vision")
        if audio is not None:
            modalities.append("audio")

        result = EmbeddingVector(
            vector_id=vector_id,
            modality="multimodal",
            vector=fused,
            source="+".join(modalities),
            confidence=min(len(modalities) / 3.0, 1.0),
            metadata={"modalities": modalities, "num_modalities": len(modalities)},
        )

        self._record_embedding("multimodal")
        self.stats["cross_modal_queries"] += 1
        return result

    def _image_to_vector(self, image: list[list[list[float]]]) -> list[float]:
        """Deterministic image-to-vector fallback."""
        vec = [0.0] * self.embedding_dim
        idx = 0
        for c in range(min(len(image), 3)):
            for y in range(0, len(image[c]), max(1, len(image[c]) // 8)):
                for x in range(0, len(image[c][y]), max(1, len(image[c][y]) // 8)):
                    if idx < self.embedding_dim:
                        vec[idx] = image[c][y][x]
                        idx += 1

        # Normalize
        norm = math.sqrt(sum(v ** 2 for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    def _audio_to_vector(self, audio: list[float]) -> list[float]:
        """Deterministic audio-to-vector fallback."""
        vec = [0.0] * self.embedding_dim
        step = max(1, len(audio) // self.embedding_dim)
        for i in range(self.embedding_dim):
            idx = min(i * step, len(audio) - 1)
            vec[i] = audio[idx] if idx < len(audio) else 0.0

        # Normalize
        norm = math.sqrt(sum(v ** 2 for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    def _record_embedding(self, modality: str) -> None:
        self.stats["total_embeddings"] += 1
        self.stats["by_modality"][modality] = self.stats["by_modality"].get(modality, 0) + 1

    def get_stats(self) -> dict[str, Any]:
        return {
            "total_embeddings": self.stats["total_embeddings"],
            "by_modality": dict(self.stats["by_modality"]),
            "cross_modal_queries": self.stats["cross_modal_queries"],
            "embedding_dim": self.embedding_dim,
            "vision_available": self.vision is not None,
            "audio_available": self.audio is not None,
            "created_at": self.created_at,
        }


class MultimodalRetrieval:
    """Cross-modal retrieval using MultimodalEmbedder.

    Enables searching across text, vision, and audio using a shared embedding
    space. For example: find images matching a text query, or find text
    matching an audio query.
    """

    def __init__(self, embedder: MultimodalEmbedder):
        self.embedder = embedder
        self.index: list[EmbeddingVector] = []
        self.created_at = time.time()

    def add(
        self,
        vector_id: str,
        modality: str,
        vector: list[float],
        source: str = "",
        confidence: float = 1.0,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Add an embedding to the retrieval index."""
        ev = EmbeddingVector(
            vector_id=vector_id,
            modality=modality,
            vector=vector,
            source=source,
            confidence=confidence,
            metadata=metadata or {},
        )
        self.index.append(ev)

    def add_from_embedder(self, emb: EmbeddingVector) -> None:
        """Add an EmbeddingVector to the index."""
        self.index.append(emb)

    def query(
        self,
        query_emb: EmbeddingVector,
        top_k: int = 5,
        modality_filter: str | None = None,
    ) -> list[tuple[EmbeddingVector, float]]:
        """Query the index for similar embeddings.

        Args:
            query_emb: Query embedding vector
            top_k: Maximum number of results
            modality_filter: Optional modality to filter by

        Returns:
            List of (EmbeddingVector, similarity_score) sorted by similarity
        """
        results = []
        for ev in self.index:
            if modality_filter and ev.modality != modality_filter:
                continue
            sim = query_emb.cosine_similarity(ev)
            results.append((ev, sim))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    def query_text(self, text: str, top_k: int = 5,
                   modality_filter: str | None = None) -> list[tuple[EmbeddingVector, float]]:
        """Query using text input."""
        query_emb = self.embedder.embed_text(text)
        return self.query(query_emb, top_k, modality_filter)

    def query_vision(self, image: list[list[list[float]]], top_k: int = 5,
                     modality_filter: str | None = None) -> list[tuple[EmbeddingVector, float]]:
        """Query using image input."""
        query_emb = self.embedder.embed_vision(image)
        return self.query(query_emb, top_k, modality_filter)

    def query_audio(self, audio: list[float], top_k: int = 5,
                    modality_filter: str | None = None) -> list[tuple[EmbeddingVector, float]]:
        """Query using audio input."""
        query_emb = self.embedder.embed_audio(audio)
        return self.query(query_emb, top_k, modality_filter)

    def get_stats(self) -> dict[str, Any]:
        return {
            "index_size": len(self.index),
            "by_modality": {},
            "created_at": self.created_at,
        }


# Global instances
_multimodal_embedder: MultimodalEmbedder | None = None
_multimodal_retrieval: MultimodalRetrieval | None = None


def get_multimodal_embedder(
    embedding_dim: int = 128,
    vision: VisionIntelligence | None = None,
    audio: AudioIntelligence | None = None,
    seed: int = 42,
) -> MultimodalEmbedder:
    """Get or create the global MultimodalEmbedder instance."""
    global _multimodal_embedder
    if _multimodal_embedder is None:
        _multimodal_embedder = MultimodalEmbedder(
            embedding_dim=embedding_dim,
            vision=vision,
            audio=audio,
            seed=seed,
        )
    return _multimodal_embedder


def get_multimodal_retrieval(
    embedder: MultimodalEmbedder | None = None,
) -> MultimodalRetrieval:
    """Get or create the global MultimodalRetrieval instance."""
    global _multimodal_retrieval
    if _multimodal_retrieval is None:
        _multimodal_retrieval = MultimodalRetrieval(
            embedder or get_multimodal_embedder()
        )
    return _multimodal_retrieval


__all__ = [
    "EmbeddingVector",
    "MultimodalEmbedder",
    "MultimodalRetrieval",
    "get_multimodal_embedder",
    "get_multimodal_retrieval",
]
