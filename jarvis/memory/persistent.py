"""Persistent Memory - M28.

Enhanced Memory Palace with vector-based semantic search, embedding
integration, and advanced retrieval. Builds on the existing Memory Palace
(jarvis/memory/palace.py).

Features:
- Semantic search using embeddings from MultimodalEmbedder (M26)
- Persistent storage with SQLite (existing)
- Vector similarity search with FAISS-like pure Python fallback
- Temporal queries (valid_from/valid_until windows)
- Provenance-aware retrieval
- Memory consolidation integration
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any

from ..memory.palace import MemoryPalace, Memory, cosine, tokenize
from ..foundation.models.multimodal import MultimodalEmbedder, EmbeddingVector


@dataclass
class MemorySearchResult:
    """Result of a semantic memory search."""
    memory: Memory
    similarity: float
    match_reason: str  # "semantic", "keyword", "entity", "temporal"


@dataclass
class PersistentMemoryStats:
    total_memories: int
    by_tier: dict[str, int]
    by_room: dict[str, int]
    by_modality: dict[str, int]
    with_embeddings: int
    total_embedding_dim: int
    created_at: float


class PersistentMemory:
    """Persistent memory layer with semantic search.

    Wraps MemoryPalace and adds:
    - Vector-based semantic search using embeddings
    - Embedding storage and retrieval
    - Temporal memory queries
    - Provenance-aware filtering
    - Cross-modal memory retrieval (text, vision, audio)
    """

    def __init__(
        self,
        palace: MemoryPalace | None = None,
        embedder: MultimodalEmbedder | None = None,
        embedding_dim: int = 128,
    ):
        self.palace = palace or MemoryPalace()
        self.embedder = embedder
        self.embedding_dim = embedding_dim

        # In-memory embedding index: memory_id -> embedding vector
        self._embeddings: dict[str, list[float]] = {}

        # Statistics
        self.stats = {
            "semantic_searches": 0,
            "embedding_stores": 0,
            "temporal_queries": 0,
        }
        self.created_at = time.time()

    def store(
        self,
        content: str,
        tier: str = "short_term",
        room: str = "Home",
        kind: str = "note",
        source: str = "",
        origin: str = "",
        modality: str = "text",
        confidence: float = 0.6,
        importance: float = 0.5,
        sensitivity: str = "normal",
        privacy: str = "private",
        provenance: str = "",
        related_entities: list[str] | None = None,
        related_memories: list[str] | None = None,
        related_events: list[str] | None = None,
        valid_from: float | None = None,
        valid_until: float | None = None,
        generate_embedding: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Store a persistent memory with optional embedding.

        Args:
            content: Memory content text
            tier: Memory tier (working, short_term, long_term, episodic, etc.)
            room: Logical room/location
            kind: Memory kind (note, fact, observation, hypothesis, etc.)
            source: Source of the memory
            origin: Provenance origin (told, inferred, observed, hypothesis, system)
            modality: Input modality (text, vision, audio, multimodal)
            confidence: Confidence score (0-1)
            importance: Importance score (0-1)
            sensitivity: Sensitivity classification
            privacy: Privacy classification
            provenance: Provenance description
            related_entities: Related entity names
            related_memories: Related memory IDs
            related_events: Related event IDs
            valid_from: Valid from timestamp
            valid_until: Valid until timestamp
            generate_embedding: Whether to generate an embedding
            metadata: Additional metadata

        Returns:
            Memory ID
        """
        # Store in palace using remember()
        mem_id = self.palace.remember(
            content=content,
            tier=tier,
            room=room,
            kind=kind,
            source=source,
            origin=origin,
            modality=modality,
            confidence=confidence,
            importance=importance,
            sensitivity=sensitivity,
            privacy=privacy,
            provenance=provenance,
            related_entities=related_entities or [],
            related_memories=related_memories or [],
            related_events=related_events or [],
            valid_from=valid_from or time.time(),
            valid_until=valid_until,
            metadata=metadata or {},
        )

        # Generate embedding if requested and embedder available
        if generate_embedding and self.embedder:
            if modality == "text":
                emb = self.embedder.embed_text(content)
            elif modality == "vision":
                emb = self.embedder.embed_vision(content) if isinstance(content, list) else self.embedder.embed_text(str(content))
            elif modality == "audio":
                emb = self.embedder.embed_audio(content) if isinstance(content, list) else self.embedder.embed_text(str(content))
            else:
                emb = self.embedder.embed_text(content)

            self._embeddings[mem_id] = emb.vector
            self.stats["embedding_stores"] += 1

        return mem_id

    def get(self, memory_id: str) -> Memory | None:
        """Get a memory by ID."""
        return self.palace.get(memory_id)

    def semantic_search(
        self,
        query: str,
        top_k: int = 10,
        tier: str | None = None,
        room: str | None = None,
        min_similarity: float = 0.3,
        modality_filter: str | None = None,
    ) -> list[MemorySearchResult]:
        """Search memories by semantic similarity.

        Uses embeddings for semantic similarity when available, falling
        back to keyword matching.

        Args:
            query: Search query text
            top_k: Maximum results
            tier: Filter by memory tier
            room: Filter by room
            min_similarity: Minimum similarity score
            modality_filter: Filter by modality

        Returns:
            List of MemorySearchResult sorted by similarity
        """
        self.stats["semantic_searches"] += 1

        # Generate query embedding
        query_emb = self.embedder.embed_text(query) if self.embedder else None
        query_vector = query_emb.vector if query_emb else None

        # Get candidate memories
        candidates = self.palace.all(tier=tier, room=room, limit=5000)

        results = []
        for mem in candidates:
            if modality_filter and mem.modality != modality_filter:
                continue

            similarity = 0.0
            match_reason = "none"

            # Semantic similarity via embedding
            if query_vector and mem.vector and len(mem.vector) == len(query_vector):
                sim = cosine(query_vector, mem.vector)
                if sim >= min_similarity:
                    similarity = sim
                    match_reason = "semantic"

            # Keyword fallback
            if similarity < min_similarity:
                kw_sim = self._keyword_similarity(query, mem.content)
                if kw_sim >= min_similarity:
                    similarity = kw_sim
                    match_reason = "keyword"

            # Entity overlap
            if similarity < min_similarity and mem.related_entities:
                query_tokens = set(tokenize(query))
                entity_overlap = len(query_tokens & set(mem.related_entities))
                if entity_overlap > 0:
                    sim = min(0.8, entity_overlap / max(len(query_tokens), 1))
                    if sim >= min_similarity:
                        similarity = sim
                        match_reason = "entity"

            if similarity >= min_similarity:
                results.append(MemorySearchResult(
                    memory=mem,
                    similarity=round(similarity, 4),
                    match_reason=match_reason,
                ))

        # Sort by similarity descending
        results.sort(key=lambda r: r.similarity, reverse=True)
        return results[:top_k]

    def temporal_query(
        self,
        valid_from: float | None = None,
        valid_until: float | None = None,
        tier: str | None = None,
        room: str | None = None,
        limit: int = 100,
    ) -> list[Memory]:
        """Query memories by temporal validity window.

        Args:
            valid_from: Query memories valid from this time
            valid_until: Query memories valid until this time
            tier: Filter by tier
            room: Filter by room
            limit: Maximum results

        Returns:
            List of Memory objects
        """
        self.stats["temporal_queries"] += 1

        candidates = self.palace.all(tier=tier, room=room, limit=limit * 3)
        results = []

        for mem in candidates:
            m_from = mem.valid_from or 0
            m_until = mem.valid_until or float("inf")

            if valid_from is not None and m_until < valid_from:
                continue
            if valid_until is not None and m_from > valid_until:
                continue

            results.append(mem)
            if len(results) >= limit:
                break

        return results

    def keyword_search(
        self,
        query: str,
        top_k: int = 10,
        tier: str | None = None,
        room: str | None = None,
    ) -> list[MemorySearchResult]:
        """Search memories by keyword/token overlap."""
        self.stats["semantic_searches"] += 1

        query_tokens = set(tokenize(query))
        candidates = self.palace.all(tier=tier, room=room, limit=5000)

        results = []
        for mem in candidates:
            mem_tokens = set(tokenize(mem.content))
            if not mem_tokens:
                continue
            overlap = len(query_tokens & mem_tokens)
            if overlap == 0:
                continue
            sim = overlap / max(len(query_tokens), 1)

            results.append(MemorySearchResult(
                memory=mem,
                similarity=round(sim, 4),
                match_reason="keyword",
            ))

        results.sort(key=lambda r: r.similarity, reverse=True)
        return results[:top_k]

    def entity_search(
        self,
        entity: str,
        top_k: int = 10,
        tier: str | None = None,
        room: str | None = None,
    ) -> list[MemorySearchResult]:
        """Search memories by related entity."""
        candidates = self.palace.all(tier=tier, room=room, limit=5000)
        entity_lower = entity.lower()

        results = []
        for mem in candidates:
            if entity_lower in [e.lower() for e in mem.related_entities]:
                results.append(MemorySearchResult(
                    memory=mem,
                    similarity=1.0,
                    match_reason="entity",
                ))
                if len(results) >= top_k:
                    break

        return results

    def get_embedding(self, memory_id: str) -> list[float] | None:
        """Get the embedding vector for a memory."""
        return self._embeddings.get(memory_id)

    def set_embedding(self, memory_id: str, vector: list[float]) -> None:
        """Set/update the embedding vector for a memory."""
        self._embeddings[memory_id] = vector

    def get_stats(self) -> PersistentMemoryStats:
        """Get memory statistics."""
        all_mems = self.palace.all(limit=10000)

        by_tier: dict[str, int] = {}
        by_room: dict[str, int] = {}
        by_modality: dict[str, int] = {}
        with_embeddings = 0

        for mem in all_mems:
            by_tier[mem.tier] = by_tier.get(mem.tier, 0) + 1
            by_room[mem.room] = by_room.get(mem.room, 0) + 1
            by_modality[mem.modality] = by_modality.get(mem.modality, 0) + 1
            if mem.vector:
                with_embeddings += 1

        return PersistentMemoryStats(
            total_memories=len(all_mems),
            by_tier=by_tier,
            by_room=by_room,
            by_modality=by_modality,
            with_embeddings=with_embeddings,
            total_embedding_dim=self.embedding_dim,
            created_at=self.created_at,
        )

    def _keyword_similarity(self, query: str, content: str) -> float:
        """Compute keyword overlap similarity."""
        query_tokens = set(tokenize(query))
        content_tokens = set(tokenize(content))
        if not query_tokens:
            return 0.0
        overlap = len(query_tokens & content_tokens)
        return overlap / len(query_tokens)


# Global instance
_persistent_memory: PersistentMemory | None = None


def get_persistent_memory(
    palace: MemoryPalace | None = None,
    embedder: MultimodalEmbedder | None = None,
    embedding_dim: int = 128,
) -> PersistentMemory:
    """Get or create the global PersistentMemory instance."""
    global _persistent_memory
    if _persistent_memory is None:
        _persistent_memory = PersistentMemory(
            palace=palace,
            embedder=embedder,
            embedding_dim=embedding_dim,
        )
    return _persistent_memory


__all__ = [
    "MemorySearchResult",
    "PersistentMemory",
    "PersistentMemoryStats",
    "get_persistent_memory",
]
