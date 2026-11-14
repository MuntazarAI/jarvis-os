"""Training Data Curation - M38.

Builds on:
- Foundation Model Lab (jarvis/foundation/models.py) for model definitions
- Dataset Governance (jarvis/foundation/data/governance.py) for data lifecycle
- Tokenizer Research (jarvis/foundation/data/tokenizer.py) for tokenization
- Memory Palace (jarvis/memory/palace.py) for training data sources

Provides:
- Training data source management and curation
- Data quality scoring and filtering
- Training/validation/test split management
- Data versioning and lineage tracking
- Data governance policy enforcement
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any

from ..memory.palace import MemoryPalace
from ..foundation.data.governance import (
    DatasetGovernance,
    DataSource,
    LicenseType,
    DataQuality,
    get_dataset_governance,
)
from ..foundation.data.tokenizer import (
    TokenizerRegistry,
    get_tokenizer_registry,
)


@dataclass
class TrainingDataSource:
    """A data source for model training."""
    source_id: str
    name: str
    description: str
    data_type: str  # "text", "code", "multimodal", "audio", "vision"
    license: LicenseType
    quality_score: float  # 0-1
    size_tokens: int
    license_compliant: bool
    privacy_reviewed: bool
    deduplicated: bool
    created_at: float = field(default_factory=time.time)
    last_updated: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "name": self.name,
            "description": self.description,
            "data_type": self.data_type,
            "license": self.license.value,
            "quality_score": self.quality_score,
            "size_tokens": self.size_tokens,
            "license_compliant": self.license_compliant,
            "privacy_reviewed": self.privacy_reviewed,
            "deduplicated": self.deduplicated,
            "created_at": self.created_at,
            "last_updated": self.last_updated,
            "metadata": self.metadata,
        }


@dataclass
class DataCuratedSet:
    """A curated dataset ready for training."""
    set_id: str
    name: str
    description: str
    source_ids: list[str]  # References to TrainingDataSource
    total_tokens: int
    total_size_bytes: int
    quality_score: float  # 0-1
    license_compliant: bool
    privacy_reviewed: bool
    deduplicated: bool
    tokenizer_id: str | None = None
    split: dict[str, int] = field(default_factory=dict)  # train/val/test token counts
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "set_id": self.set_id,
            "name": self.name,
            "description": self.description,
            "source_ids": self.source_ids,
            "total_tokens": self.total_tokens,
            "total_size_bytes": self.total_size_bytes,
            "quality_score": self.quality_score,
            "license_compliant": self.license_compliant,
            "privacy_reviewed": self.privacy_reviewed,
            "deduplicated": self.deduplicated,
            "tokenizer_id": self.tokenizer_id,
            "split": self.split,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }


class DataCurator:
    """Curates training data for foundation model training.

    Manages:
    - Source registration and license validation
    - Quality assessment and scoring
    - Deduplication and privacy filtering
    - Dataset versioning and export
    - Training/validation/test splitting
    """

    def __init__(self,
                 governance: DatasetGovernance | None = None,
                 tokenizer_registry: TokenizerRegistry | None = None,
                 memory_palace: MemoryPalace | None = None):
        self.governance = governance or PersistentMemory()  # type: ignore
        self.tokenizer_registry = tokenizer_registry or TokenizerRegistry()
        self.memory_palace = memory_palace

        self.data_sources: dict[str, TrainingDataSource] = {}
        self.data_curated_sets: dict[str, DataCuratedSet] = {}
        self.created_at = time.time()
        self.stats = {
            "sources_registered": 0,
            "sets_created": 0,
            "total_tokens_curated": 0,
            "license_compliant_sets": 0,
            "privacy_reviewed_sets": 0,
        }

    def register_data_source(self,
                             name: str,
                             data_type: str,
                             license: LicenseType,
                             size_tokens: int,
                             quality_score: float = 0.5,
                             source_path: str | None = None,
                             privacy_reviewed: bool = False,
                             deduplicated: bool = False,
                             metadata: dict[str, Any] | None = None) -> str:
        """Register a new data source for training."""
        source_id = f"ds-{hashlib.sha256(f'{name}|{time.time()}'.encode()).hexdigest()[:12]}"

        source = TrainingDataSource(
            source_id=source_id,
            name=name,
            description=source_path or name,
            data_type=data_type,
            license=license,
            quality_score=max(0.0, min(1.0, quality_score)),
            size_tokens=size_tokens,
            license_compliant=license in (LicenseType.PERMISSIVE, LicenseType.COPYLEFT),
            privacy_reviewed=privacy_reviewed,
            deduplicated=deduplicated,
            metadata=metadata or {},
        )
        self.data_sources[source_id] = source
        self.stats["sources_registered"] += 1
        return source_id

    def get_source(self, source_id: str) -> TrainingDataSource | None:
        return self.data_sources.get(source_id)

    def list_sources(self) -> list[TrainingDataSource]:
        return list(self.data_sources.values())

    def create_curated_set(self,
                           name: str,
                           source_ids: list[str],
                           description: str = "",
                           tokenizer_id: str | None = None,
                           train_split: float = 0.8,
                           val_split: float = 0.1,
                           test_split: float = 0.1,
                           min_quality: float = 0.0,
                           require_license_compliant: bool = True,
                           require_privacy_reviewed: bool = False) -> str:
        """Create a curated dataset from selected sources."""
        set_id = f"ds-set-{hashlib.sha256(f'{name}|{time.time()}'.encode()).hexdigest()[:12]}"

        # Filter sources
        selected_sources = []
        total_tokens = 0
        total_size = 0
        quality_scores = []

        for sid in source_ids:
            source = self.data_sources.get(sid)
            if source is None:
                continue
            if require_license_compliant and not source.license_compliant:
                continue
            if require_privacy_reviewed and not source.privacy_reviewed:
                continue
            if source.quality_score < min_quality:
                continue

            selected_sources.append(source)
            total_tokens += source.size_tokens
            quality_scores.append(source.quality_score)

        if not selected_sources:
            raise ValueError("No sources passed filtering criteria")

        # Calculate quality score
        avg_quality = sum(quality_scores) / len(quality_scores)

        # Create set
        data_set = DataCuratedSet(
            set_id=set_id,
            name=name,
            description=description,
            source_ids=[s.source_id for s in selected_sources],
            total_tokens=total_tokens,
            total_size_bytes=total_size,
            quality_score=avg_quality,
            license_compliant=all(s.license_compliant for s in selected_sources),
            privacy_reviewed=all(s.privacy_reviewed for s in selected_sources),
            deduplicated=all(s.deduplicated for s in selected_sources),
            tokenizer_id=tokenizer_id,
            split={
                "train": int(total_tokens * train_split),
                "validation": int(total_tokens * val_split),
                "test": int(total_tokens * test_split),
            },
        )
        self.data_curated_sets[set_id] = data_set
        self.stats["sets_created"] += 1
        self.stats["total_tokens_curated"] += total_tokens
        if data_set.license_compliant:
            self.stats["license_compliant_sets"] += 1
        if data_set.privacy_reviewed:
            self.stats["privacy_reviewed_sets"] += 1

        return set_id

    def get_curated_set(self, set_id: str) -> DataCuratedSet | None:
        return self.data_curated_sets.get(set_id)

    def list_curated_sets(self) -> list[DataCuratedSet]:
        return list(self.data_curated_sets.values())

    def get_stats(self) -> dict[str, Any]:
        return {
            "sources_registered": self.stats["sources_registered"],
            "sets_created": self.stats["sets_created"],
            "total_tokens_curated": self.stats["total_tokens_curated"],
            "license_compliant_sets": self.stats["license_compliant_sets"],
            "privacy_reviewed_sets": self.stats["privacy_reviewed_sets"],
        }


# Global data curator instance
_data_curator: DataCurator | None = None


def get_data_curator(
    governance: DatasetGovernance | None = None,
    tokenizer_registry: TokenizerRegistry | None = None,
    memory_palace: MemoryPalace | None = None,
) -> DataCurator:
    """Get or create the global DataCurator instance."""
    global _data_curator
    if _data_curator is None:
        _data_curator = DataCurator(
            governance=governance,
            tokenizer_registry=tokenizer_registry,
            memory_palace=memory_palace,
        )
    return _data_curator


__all__ = [
    "TrainingDataSource",
    "DataCuratedSet",
    "DataCurator",
    "get_data_curator",
]
