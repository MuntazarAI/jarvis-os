"""Dataset Governance - M18.

Data engineering pipeline for JARVIS foundation model training:
- Source ingestion with license validation
- Data provenance tracking
- Quality assessment and deduplication
- Privacy filtering
- Tokenization
- Dataset versioning and statistics

All operations are local-first and auditable. No external data is
automatically collected - all datasets must be explicitly provisioned.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import statistics
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any


class LicenseType(str, Enum):
    """Data license categories."""
    PERMISSIVE = "permissive"      # MIT, Apache, BSD, CC0, CC-BY
    COPYLEFT = "copyleft"          # GPL, AGPL, CC-BY-SA
    RESTRICTED = "restricted"      # Non-commercial, NoDerivs
    UNKNOWN = "unknown"            # License not identified
    PROPRIETARY = "proprietary"    # All rights reserved


class DataQuality(str, Enum):
    """Data quality tiers."""
    HIGH = "high"       # Verified, deduplicated, privacy-filtered
    MEDIUM = "medium"   # Basic validation, some cleaning
    LOW = "low"         # Raw, minimal processing
    UNREVIEWED = "unreviewed"


@dataclass
class DataSource:
    """A data source with provenance metadata."""
    source_id: str
    name: str
    url: str | None
    license: LicenseType
    license_text: str | None
    access_date: float
    size_bytes: int
    record_count: int
    quality: DataQuality
    description: str = ""
    tags: list[str] = field(default_factory=list)
    sha256: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DatasetVersion:
    """A versioned dataset snapshot."""
    version_id: str
    dataset_name: str
    version: str  # semver-like
    sources: list[str]  # source_ids
    total_records: int
    total_tokens: int
    size_bytes: int
    checksum: str
    created_at: float
    quality: DataQuality
    privacy_filtered: bool
    deduplicated: bool
    license_summary: dict[str, int]  # license_type -> count

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DataRecord:
    """A single data record in the pipeline."""
    record_id: str
    source_id: str
    content: str
    content_type: str  # "text", "code", "markdown", etc.
    language: str | None
    quality_score: float  # 0-1
    privacy_risk: float  # 0-1, higher = more risk
    license: LicenseType
    timestamp: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DatasetGovernance:
    """Dataset governance pipeline.

    Manages the complete data lifecycle from ingestion to versioned
    dataset release, with full provenance, license validation,
    quality assessment, deduplication, and privacy filtering.
    """

    def __init__(self, data_dir: str | Path | None = None):
        self.data_dir = Path(data_dir) if data_dir else Path("./data/datasets")
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.sources: dict[str, DataSource] = {}
        self.versions: dict[str, DatasetVersion] = {}
        self.records: dict[str, DataRecord] = {}
        self.ingestion_log: list[dict[str, Any]] = []

        # Statistics
        self.stats = {
            "total_records_ingested": 0,
            "total_records_filtered": 0,
            "total_duplicates_removed": 0,
            "total_privacy_removed": 0,
        }

        self.created_at = time.time()

    def register_source(
        self,
        name: str,
        license: LicenseType,
        quality: DataQuality = DataQuality.UNREVIEWED,
        url: str | None = None,
        license_text: str | None = None,
        size_bytes: int = 0,
        record_count: int = 0,
        description: str = "",
        tags: list[str] | None = None,
    ) -> str:
        """Register a data source and return its source_id."""
        source_id = f"src-{hashlib.sha256((name + str(time.time())).encode()).hexdigest()[:12]}"
        sha256 = self._compute_sha256(license_text or "")

        source = DataSource(
            source_id=source_id,
            name=name,
            url=url,
            license=license,
            license_text=license_text,
            access_date=time.time(),
            size_bytes=size_bytes,
            record_count=record_count,
            quality=quality,
            description=description,
            tags=tags or [],
            sha256=sha256,
        )
        self.sources[source_id] = source

        self.ingestion_log.append({
            "action": "register_source",
            "source_id": source_id,
            "name": name,
            "license": license.value,
            "timestamp": time.time(),
        })

        return source_id

    def ingest_record(
        self,
        source_id: str,
        content: str,
        content_type: str = "text",
        language: str | None = None,
        quality_score: float = 0.5,
        privacy_risk: float = 0.0,
        license: LicenseType = LicenseType.UNKNOWN,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Ingest a single data record."""
        record_id = f"rec-{hashlib.sha256((content + str(time.time())).encode()).hexdigest()[:12]}"

        record = DataRecord(
            record_id=record_id,
            source_id=source_id,
            content=content,
            content_type=content_type,
            language=language,
            quality_score=quality_score,
            privacy_risk=privacy_risk,
            license=license,
            timestamp=time.time(),
            metadata=metadata or {},
        )
        self.records[record_id] = record

        # Update source stats
        if source_id in self.sources:
            self.sources[source_id].record_count += 1

        self.stats["total_records_ingested"] += 1

        self.ingestion_log.append({
            "action": "ingest_record",
            "record_id": record_id,
            "source_id": source_id,
            "content_type": content_type,
            "timestamp": time.time(),
        })

        return record_id

    def deduplicate(self, similarity_threshold: float = 0.95) -> int:
        """Remove duplicate records based on content similarity."""
        records = list(self.records.values())
        removed = 0
        seen_hashes: set[str] = set()

        to_remove: set[str] = set()
        for record in records:
            content_hash = hashlib.sha256(record.content.strip().lower().encode()).hexdigest()
            if content_hash in seen_hashes:
                to_remove.add(record.record_id)
                removed += 1
            else:
                seen_hashes.add(content_hash)

        for record_id in to_remove:
            del self.records[record_id]

        self.stats["total_duplicates_removed"] += removed

        self.ingestion_log.append({
            "action": "deduplicate",
            "removed": removed,
            "threshold": similarity_threshold,
            "timestamp": time.time(),
        })

        return removed

    def privacy_filter(
        self,
        max_privacy_risk: float = 0.3,
        patterns: list[str] | None = None,
    ) -> int:
        """Filter records with high privacy risk or matching PII patterns."""
        patterns = patterns or [
            r"\b\d{3}-\d{2}-\d{4}\b",  # SSN
            r"\b\d{4}[\s-]\d{4}[\s-]\d{4}[\s-]\d{4}\b",  # Credit card
            r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",  # Email (basic)
        ]

        to_remove: set[str] = set()
        for record in self.records.values():
            if record.privacy_risk > max_privacy_risk:
                to_remove.add(record.record_id)
                continue
            for pattern in patterns:
                if re.search(pattern, record.content):
                    to_remove.add(record.record_id)
                    break

        for record_id in to_remove:
            del self.records[record_id]

        removed = len(to_remove)
        self.stats["total_privacy_removed"] += removed

        self.ingestion_log.append({
            "action": "privacy_filter",
            "removed": removed,
            "max_risk": max_privacy_risk,
            "timestamp": time.time(),
        })

        return removed

    def quality_filter(self, min_quality: float = 0.3) -> int:
        """Filter records below minimum quality score."""
        to_remove: set[str] = set()
        for record in self.records.values():
            if record.quality_score < min_quality:
                to_remove.add(record.record_id)

        for record_id in to_remove:
            del self.records[record_id]

        removed = len(to_remove)
        self.stats["total_records_filtered"] += removed

        self.ingestion_log.append({
            "action": "quality_filter",
            "removed": removed,
            "min_quality": min_quality,
            "timestamp": time.time(),
        })

        return removed

    def create_version(
        self,
        dataset_name: str,
        version: str,
        source_ids: list[str] | None = None,
        privacy_filtered: bool = False,
        deduplicated: bool = False,
    ) -> str:
        """Create a versioned dataset snapshot."""
        version_id = f"ver-{hashlib.sha256((dataset_name + version + str(time.time())).encode()).hexdigest()[:12]}"

        # Select records from specified sources (or all if none specified)
        if source_ids:
            records = [r for r in self.records.values() if r.source_id in source_ids]
        else:
            records = list(self.records.values())

        total_tokens = sum(len(r.content.split()) for r in records)
        size_bytes = sum(len(r.content.encode("utf-8")) for r in records)

        # Compute checksum
        content = "".join(r.content for r in sorted(records, key=lambda r: r.record_id))
        checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()

        # License summary
        license_summary: dict[str, int] = {}
        for r in records:
            lt = r.license.value
            license_summary[lt] = license_summary.get(lt, 0) + 1

        # Overall quality
        if records:
            avg_quality = statistics.mean(r.quality_score for r in records)
            quality = DataQuality.HIGH if avg_quality >= 0.7 else (
                DataQuality.MEDIUM if avg_quality >= 0.4 else DataQuality.LOW
            )
        else:
            quality = DataQuality.UNREVIEWED

        dataset_version = DatasetVersion(
            version_id=version_id,
            dataset_name=dataset_name,
            version=version,
            sources=source_ids or [],
            total_records=len(records),
            total_tokens=total_tokens,
            size_bytes=size_bytes,
            checksum=checksum,
            created_at=time.time(),
            quality=quality,
            privacy_filtered=privacy_filtered,
            deduplicated=deduplicated,
            license_summary=license_summary,
        )
        self.versions[version_id] = dataset_version

        self.ingestion_log.append({
            "action": "create_version",
            "version_id": version_id,
            "dataset_name": dataset_name,
            "version": version,
            "total_records": len(records),
            "timestamp": time.time(),
        })

        return version_id

    def export_version(self, version_id: str, path: str | Path) -> str:
        """Export a dataset version to JSONL format."""
        version = self.versions.get(version_id)
        if version is None:
            raise ValueError(f"Version {version_id} not found")

        # Collect records
        if version.sources:
            records = [r for r in self.records.values() if r.source_id in version.sources]
        else:
            records = list(self.records.values())

        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")

        return str(output_path)

    def get_stats(self) -> dict[str, Any]:
        """Get governance statistics."""
        license_counts: dict[str, int] = {}
        quality_counts: dict[str, int] = {}
        for record in self.records.values():
            license_counts[record.license.value] = license_counts.get(record.license.value, 0) + 1
            q = record.quality_score
            q_tier = "high" if q >= 0.7 else ("medium" if q >= 0.4 else "low")
            quality_counts[q_tier] = quality_counts.get(q_tier, 0) + 1

        return {
            "total_sources": len(self.sources),
            "total_records": len(self.records),
            "total_versions": len(self.versions),
            "license_distribution": license_counts,
            "quality_distribution": quality_counts,
            "stats": dict(self.stats),
            "created_at": self.created_at,
        }

    def _compute_sha256(self, content: str | None) -> str | None:
        if content is None:
            return None
        return hashlib.sha256(content.encode("utf-8")).hexdigest()


# Global governance instance
_governance: DatasetGovernance | None = None


def get_dataset_governance(data_dir: str | Path | None = None) -> DatasetGovernance:
    """Get or create the global dataset governance instance."""
    global _governance
    if _governance is None:
        _governance = DatasetGovernance(data_dir)
    return _governance


__all__ = [
    "LicenseType",
    "DataQuality",
    "DataSource",
    "DatasetVersion",
    "DataRecord",
    "DatasetGovernance",
    "get_dataset_governance",
]
