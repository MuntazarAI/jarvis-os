"""Sensor Fusion - M27.

Multimodal sensor fusion combining vision, audio, and other sensor inputs
into a unified understanding. Builds on:
- VisionIntelligence (M23) for visual perception
- AudioIntelligence (M24) for audio perception
- MultimodalEmbedder (M26) for shared embedding space

Provides:
- Late fusion: combine independent modality predictions
- Early fusion: combine embeddings before classification
- Sensor confidence weighting
- Temporal fusion across time steps
- Conflict resolution between modalities
"""

from __future__ import annotations

import hashlib
import math
import time
from dataclasses import dataclass, field
from typing import Any

from .multimodal import (
    EmbeddingVector,
    MultimodalEmbedder,
    MultimodalRetrieval,
    get_multimodal_embedder,
)
from ...vision.intelligence import VisionIntelligence, VisionResult
from ...voice.intelligence import AudioIntelligence, AudioResult


@dataclass
class SensorReading:
    """A single sensor reading."""
    sensor_id: str
    modality: str  # vision | audio | text | lidar | imu | gps | etc.
    timestamp: float
    data: Any
    confidence: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sensor_id": self.sensor_id,
            "modality": self.modality,
            "timestamp": self.timestamp,
            "data": self.data,
            "confidence": self.confidence,
            "metadata": self.metadata,
        }


@dataclass
class FusedResult:
    """Result of sensor fusion."""
    fusion_id: str
    timestamp: float
    modalities: list[str]
    primary_modality: str
    combined_confidence: float
    predictions: list[dict[str, Any]]
    embedding: list[float] | None
    modality_confidences: dict[str, float]
    conflicts: list[dict[str, Any]]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fusion_id": self.fusion_id,
            "timestamp": self.timestamp,
            "modalities": self.modalities,
            "primary_modality": self.primary_modality,
            "combined_confidence": self.combined_confidence,
            "predictions": self.predictions,
            "embedding": self.embedding,
            "modality_confidences": self.modality_confidences,
            "conflicts": self.conflicts,
            "metadata": self.metadata,
        }


class SensorFusion:
    """Sensor fusion layer for JARVIS-OS.

    Combines readings from multiple sensors (vision, audio, text, etc.)
    into a unified understanding using:

    1. Late fusion: combine predictions from each modality, weighted by
       confidence
    2. Early fusion: combine embeddings into a shared representation
    3. Conflict detection: identify when modalities disagree
    4. Temporal smoothing: fuse across time steps
    """

    def __init__(
        self,
        embedder: MultimodalEmbedder | None = None,
        vision: VisionIntelligence | None = None,
        audio: AudioIntelligence | None = None,
        seed: int = 42,
    ):
        self.embedder = embedder or get_multimodal_embedder(
            vision=vision, audio=audio, seed=seed
        )
        self.vision = vision
        self.audio = audio
        self.seed = seed

        # Modality weights (can be learned/adapted)
        self.modality_weights = {
            "vision": 0.4,
            "audio": 0.3,
            "text": 0.3,
        }

        # Conflict threshold: modalities conflict if confidence difference > this
        self.conflict_threshold = 0.3

        # Temporal history for smoothing
        self.history: list[FusedResult] = []
        self.max_history = 100

        # Statistics
        self.stats = {
            "total_fusions": 0,
            "conflicts_detected": 0,
            "by_primary_modality": {},
        }
        self.created_at = time.time()

    def fuse(
        self,
        readings: list[SensorReading],
        timestamp: float | None = None,
    ) -> FusedResult:
        """Fuse multiple sensor readings into a unified result.

        Args:
            readings: List of sensor readings from different modalities
            timestamp: Optional timestamp (uses latest reading time if None)

        Returns:
            FusedResult with combined understanding
        """
        import time as _time
        start = _time.time()
        timestamp = timestamp or max((r.timestamp for r in readings),
                                     default=_time.time())
        fusion_id = f"fus-{hashlib.sha256(str(_time.time()).encode()).hexdigest()[:8]}"

        # Group readings by modality
        modality_readings: dict[str, list[SensorReading]] = {}
        for r in readings:
            modality_readings.setdefault(r.modality, []).append(r)

        # Get embedding-based representation for each modality
        modality_embeddings: dict[str, EmbeddingVector] = {}
        modality_confidences: dict[str, float] = {}
        all_predictions: list[dict[str, Any]] = []

        for modality, mods in modality_readings.items():
            # Use the highest-confidence reading per modality
            best = max(mods, key=lambda r: r.confidence)
            modality_confidences[modality] = best.confidence

            # Generate embedding based on modality
            if modality == "vision" and isinstance(best.data, list):
                emb = self.embedder.embed_vision(best.data)
                modality_embeddings[modality] = emb
                all_predictions.extend(best.data if isinstance(best.data, list) else [])
            elif modality == "audio" and isinstance(best.data, list):
                emb = self.embedder.embed_audio(best.data)
                modality_embeddings[modality] = emb
            elif modality == "text" and isinstance(best.data, str):
                emb = self.embedder.embed_text(best.data)
                modality_embeddings[modality] = emb
                all_predictions.append({
                    "label": "text",
                    "confidence": best.confidence,
                    "text": best.data,
                })
            else:
                # Generic embedding from data hash
                emb = self._generic_embedding(best.data)
                modality_embeddings[modality] = emb

        # Early fusion: weighted average of embeddings
        combined_embedding = self._weighted_embedding_fusion(
            modality_embeddings, self.modality_weights
        )

        # Late fusion: combine predictions
        combined_predictions = self._late_fusion_predictions(
            modality_readings, modality_confidences
        )

        # Detect conflicts between modalities
        conflicts = self._detect_conflicts(
            modality_readings, modality_confidences
        )

        # Determine primary modality (highest confidence)
        primary_modality = max(
            modality_confidences, key=modality_confidences.get
        ) if modality_confidences else "unknown"

        # Combined confidence
        combined_confidence = self._compute_combined_confidence(
            modality_confidences, conflicts
        )

        result = FusedResult(
            fusion_id=fusion_id,
            timestamp=timestamp,
            modalities=list(modality_readings.keys()),
            primary_modality=primary_modality,
            combined_confidence=combined_confidence,
            predictions=combined_predictions,
            embedding=combined_embedding,
            modality_confidences=modality_confidences,
            conflicts=conflicts,
            metadata={
                "num_readings": len(readings),
                "num_modalities": len(modality_readings),
            },
        )

        # Temporal smoothing
        self._add_to_history(result)

        # Update stats
        self.stats["total_fusions"] += 1
        if conflicts:
            self.stats["conflicts_detected"] += 1
        self.stats["by_primary_modality"][primary_modality] = (
            self.stats["by_primary_modality"].get(primary_modality, 0) + 1
        )

        return result

    def fuse_vision_audio(
        self,
        vision_result: VisionResult,
        audio_result: AudioResult | None = None,
        timestamp: float | None = None,
    ) -> FusedResult:
        """Convenience: fuse vision and audio results.

        Args:
            vision_result: Vision inference result
            audio_result: Optional audio inference result
            timestamp: Optional timestamp

        Returns:
            FusedResult combining vision and audio
        """
        readings = [
            SensorReading(
                sensor_id="vision",
                modality="vision",
                timestamp=vision_result.timestamp,
                data=vision_result.predictions,
                confidence=vision_result.confidence,
                metadata={"source": vision_result.source},
            )
        ]

        if audio_result:
            readings.append(
                SensorReading(
                    sensor_id="audio",
                    modality="audio",
                    timestamp=audio_result.timestamp,
                    data=audio_result.predictions,
                    confidence=audio_result.confidence,
                    metadata={"source": audio_result.source},
                )
            )

        return self.fuse(readings, timestamp=timestamp)

    def fuse_text_vision(
        self,
        text: str,
        image: list[list[list[float]]] | None = None,
        timestamp: float | None = None,
    ) -> FusedResult:
        """Convenience: fuse text and vision.

        Args:
            text: Text input
            image: Optional image input
            timestamp: Optional timestamp

        Returns:
            FusedResult combining text and vision
        """
        readings = [
            SensorReading(
                sensor_id="text",
                modality="text",
                timestamp=timestamp or time.time(),
                data=text,
                confidence=1.0,
            )
        ]

        if image is not None:
            readings.append(
                SensorReading(
                    sensor_id="vision",
                    modality="vision",
                    timestamp=timestamp or time.time(),
                    data=image,
                    confidence=1.0,
                )
            )

        return self.fuse(readings, timestamp=timestamp)

    def _weighted_embedding_fusion(
        self,
        embeddings: dict[str, EmbeddingVector],
        weights: dict[str, float],
    ) -> list[float] | None:
        """Weighted average of modality embeddings (early fusion)."""
        if not embeddings:
            return None

        dim = self.embedder.embedding_dim
        fused = [0.0] * dim
        total_weight = 0.0

        for modality, emb in embeddings.items():
            w = weights.get(modality, 0.1)
            total_weight += w
            for i in range(dim):
                fused[i] += emb.vector[i] * w

        if total_weight > 0:
            fused = [v / total_weight for v in fused]

        # Normalize
        norm = math.sqrt(sum(v ** 2 for v in fused))
        if norm > 0:
            fused = [v / norm for v in fused]

        return fused

    def _late_fusion_predictions(
        self,
        modality_readings: dict[str, list[SensorReading]],
        modality_confidences: dict[str, float],
    ) -> list[dict[str, Any]]:
        """Late fusion: combine predictions weighted by modality confidence."""
        combined: dict[str, dict[str, Any]] = {}

        for modality, readings in modality_readings.items():
            w = modality_confidences.get(modality, 0.5)
            for r in readings:
                if isinstance(r.data, dict):
                    label = r.data.get("label", "unknown")
                    conf = r.data.get("confidence", 0.5)
                    weighted_conf = conf * w

                    if label not in combined:
                        combined[label] = {
                            "label": label,
                            "confidence": 0.0,
                            "modalities": [],
                            "sources": [],
                        }
                        combined[label]["confidence"] += weighted_conf
                        combined[label]["modalities"].append(modality)
                        combined[label]["sources"].append(r.sensor_id)

                elif isinstance(r.data, str):
                    label = r.data[:50]
                    weighted_conf = r.confidence * w

                    if label not in combined:
                        combined[label] = {
                            "label": label,
                            "confidence": 0.0,
                            "modalities": [],
                            "sources": [],
                        }
                    combined[label]["confidence"] += weighted_conf
                    combined[label]["modalities"].append(modality)
                    combined[label]["sources"].append(r.sensor_id)

                # Raw list data (e.g., image/audio arrays) has no explicit
                # predictions to fuse at the prediction level; it is handled
                # by embedding-based early fusion instead.

        # Normalize confidences and sort
        results = list(combined.values())
        for r in results:
            r["confidence"] = round(min(r["confidence"], 1.0), 4)
            r["modalities"] = list(set(r["modalities"]))
            r["sources"] = list(set(r["sources"]))

        results.sort(key=lambda x: x["confidence"], reverse=True)
        return results[:10]

    def _detect_conflicts(
        self,
        modality_readings: dict[str, list[SensorReading]],
        modality_confidences: dict[str, float],
    ) -> list[dict[str, Any]]:
        """Detect conflicts between modalities.

        A conflict occurs when two modalities have high confidence but
        disagree on the primary prediction.
        """
        conflicts = []

        modalities = list(modality_readings.keys())
        for i in range(len(modalities)):
            for j in range(i + 1, len(modalities)):
                m1, m2 = modalities[i], modalities[j]
                c1, c2 = modality_confidences.get(m1, 0), modality_confidences.get(m2, 0)

                # Only flag if both are reasonably confident
                if c1 > 0.5 and c2 > 0.5:
                    conf_diff = abs(c1 - c2)
                    if conf_diff > self.conflict_threshold:
                        conflicts.append({
                            "modality_1": m1,
                            "modality_2": m2,
                            "confidence_1": c1,
                            "confidence_2": c2,
                            "confidence_difference": round(conf_diff, 4),
                            "type": "confidence_conflict",
                        })

        return conflicts

    def _compute_combined_confidence(
        self,
        modality_confidences: dict[str, float],
        conflicts: list[dict[str, Any]],
    ) -> float:
        """Compute overall combined confidence."""
        if not modality_confidences:
            return 0.0

        # Weighted average of modality confidences
        total_conf = 0.0
        total_weight = 0.0
        for modality, conf in modality_confidences.items():
            w = self.modality_weights.get(modality, 0.1)
            total_conf += conf * w
            total_weight += w

        base_conf = total_conf / total_weight if total_weight > 0 else 0.0

        # Reduce confidence if conflicts exist
        if conflicts:
            max_conflict = max(
                c["confidence_difference"] for c in conflicts
            )
            base_conf *= (1.0 - max_conflict * 0.5)

        return round(max(0.0, min(1.0, base_conf)), 4)

    def _add_to_history(self, result: FusedResult) -> None:
        """Add result to temporal history for smoothing."""
        self.history.append(result)
        if len(self.history) > self.max_history:
            self.history = self.history[-self.max_history:]

    def temporal_smooth(
        self,
        window: int = 5,
    ) -> FusedResult | None:
        """Apply temporal smoothing over recent fused results.

        Args:
            window: Number of recent results to smooth over

        Returns:
            Smoothed FusedResult or None if no history
        """
        if not self.history:
            return None

        recent = self.history[-window:]

        # Average confidences
        avg_conf = sum(r.combined_confidence for r in recent) / len(recent)

        # Aggregate predictions
        pred_scores: dict[str, float] = {}
        for r in recent:
            for p in r.predictions:
                label = p["label"]
                pred_scores[label] = pred_scores.get(label, 0.0) + p["confidence"]

        # Normalize
        total = sum(pred_scores.values())
        if total > 0:
            pred_scores = {k: v / total for k, v in pred_scores.items()}

        # Top predictions
        sorted_preds = sorted(pred_scores.items(), key=lambda x: x[1], reverse=True)
        predictions = [
            {"label": k, "confidence": round(v, 4)}
            for k, v in sorted_preds[:10]
        ]

        # Most common primary modality
        primary_counts: dict[str, int] = {}
        for r in recent:
            primary_counts[r.primary_modality] = (
                primary_counts.get(r.primary_modality, 0) + 1
            )
        primary_modality = max(primary_counts, key=primary_counts.get)

        # Average embedding
        embeddings = [r.embedding for r in recent if r.embedding]
        combined_embedding = None
        if embeddings:
            dim = len(embeddings[0])
            combined_embedding = [
                sum(e[i] for e in embeddings) / len(embeddings)
                for i in range(dim)
            ]
            norm = math.sqrt(sum(v ** 2 for v in combined_embedding))
            if norm > 0:
                combined_embedding = [v / norm for v in combined_embedding]

        # Aggregate all modalities
        all_modalities: set[str] = set()
        for r in recent:
            all_modalities.update(r.modalities)

        # Aggregate conflicts
        all_conflicts: list[dict[str, Any]] = []
        for r in recent:
            all_conflicts.extend(r.conflicts)

        return FusedResult(
            fusion_id=f"smooth-{int(time.time())}",
            timestamp=recent[-1].timestamp,
            modalities=list(all_modalities),
            primary_modality=primary_modality,
            combined_confidence=round(avg_conf, 4),
            predictions=predictions,
            embedding=combined_embedding,
            modality_confidences={},
            conflicts=all_conflicts[-10:],
            metadata={"smoothed": True, "window": window},
        )

    def get_stats(self) -> dict[str, Any]:
        return {
            "total_fusions": self.stats["total_fusions"],
            "conflicts_detected": self.stats["conflicts_detected"],
            "conflict_rate": (
                self.stats["conflicts_detected"] / max(self.stats["total_fusions"], 1)
            ),
            "by_primary_modality": dict(self.stats["by_primary_modality"]),
            "history_size": len(self.history),
            "modalities": list(self.modality_weights.keys()),
            "created_at": self.created_at,
        }


# Global instance
_sensor_fusion: SensorFusion | None = None


def get_sensor_fusion(
    embedder: MultimodalEmbedder | None = None,
    vision: VisionIntelligence | None = None,
    audio: AudioIntelligence | None = None,
    seed: int = 42,
) -> SensorFusion:
    """Get or create the global SensorFusion instance."""
    global _sensor_fusion
    if _sensor_fusion is None:
        _sensor_fusion = SensorFusion(
            embedder=embedder,
            vision=vision,
            audio=audio,
            seed=seed,
        )
    return _sensor_fusion


__all__ = [
    "SensorReading",
    "FusedResult",
    "SensorFusion",
    "get_sensor_fusion",
]
