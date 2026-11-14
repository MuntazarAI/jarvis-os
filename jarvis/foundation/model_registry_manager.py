"""Model Registry - M39.

Model versioning, lineage tracking, deployment management, and rollback.
Builds on foundation model registry (jarvis/foundation/model_registry.py)
and foundation models (jarvis/foundation/models.py).
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any

from ..foundation.base_model import BaseModel, ModelConfig, ModelSpec, ModelTaskType


@dataclass
class ModelVersion:
    """A versioned model."""
    version_id: str
    model_id: str
    version: str  # semver-like: "1.0.0"
    spec: ModelSpec
    config: ModelConfig
    training_run_id: str | None = None
    checkpoint_path: str | None = None
    checksum: str | None = None
    performance_metrics: dict[str, float] = field(default_factory=dict)
    deployment_status: str = "created"  # created, staging, deployed, deprecated, retired
    created_at: float = field(default_factory=time.time)
    deployed_at: float | None = None
    retired_at: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version_id": self.version_id,
            "model_id": self.model_id,
            "version": self.version,
            "spec": self.spec.__dict__,
            "config": self.config.__dict__,
            "training_run_id": self.training_run_id,
            "checkpoint_path": self.checkpoint_path,
            "checksum": self.checksum,
            "performance_metrics": self.performance_metrics,
            "deployment_status": self.deployment_status,
            "created_at": self.created_at,
            "deployed_at": self.deployed_at,
            "retired_at": self.retired_at,
            "metadata": self.metadata,
        }


@dataclass
class ModelRelease:
    """A release of one or more model versions."""
    release_id: str
    model_id: str
    version_id: str
    release_name: str
    release_notes: str
    status: str = "proposed"  # proposed, approved, deployed, deprecated, rolled_back
    approval_required: bool = True
    approved_by: str | None = None
    approved_at: float | None = None
    deployed_at: float | None = None
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "release_id": self.release_id,
            "model_id": self.model_id,
            "version_id": self.version_id,
            "release_name": self.release_name,
            "release_notes": self.release_notes,
            "status": self.status,
            "approval_required": self.approval_required,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "deployed_at": self.deployed_at,
            "created_at": self.created_at,
        }


class ModelRegistryManager:
    """Manages model versions, deployments, and rollbacks.

    Provides:
    - Model versioning and lineage tracking
    - Model deployment and rollback
    - Model performance tracking
    - Model release management
    - Model deprecation and retirement
    """

    def __init__(self) -> None:
        self.models: dict[str, ModelSpec] = {}
        self.versions: dict[str, ModelVersion] = {}
        self.releases: dict[str, ModelRelease] = {}
        self.model_versions: dict[str, list[str]] = {}  # model_id -> [version_ids]
        self.deployed_versions: dict[str, str] = {}  # model_id -> version_id
        self.created_at = time.time()
        self.stats = {
            "models_registered": 0,
            "versions_created": 0,
            "releases_created": 0,
            "deployments": 0,
            "rollbacks": 0,
        }

    def register_model(self,
                       model_id: str,
                       name: str,
                       model_type: str,
                       task_type: str,
                       num_layers: int = 12,
                       hidden_size: int = 768,
                       num_attention_heads: int = 12,
                       intermediate_size: int = 3072,
                       max_position_embeddings: int = 2048,
                       vocab_size: int = 50257,
                       max_sequence_length: int = 2048,
                       dropout: float = 0.1,
                       **kwargs) -> str:
        """Register a new model version."""
        spec = ModelSpec(
            model_id=model_id,
            name=name,
            model_type=model_type,
            task_type=task_type,
            num_layers=num_layers,
            hidden_size=hidden_size,
            num_attention_heads=num_attention_heads,
            intermediate_size=intermediate_size,
            max_position_embeddings=max_position_embeddings,
            vocab_size=vocab_size,
            max_sequence_length=max_sequence_length,
            dropout=dropout,
            **kwargs,
        )
        self.models[model_id] = spec
        self.model_versions[model_id] = []
        self.stats["models_registered"] += 1
        return model_id

    def create_version(self,
                       model_id: str,
                       version: str,
                       spec_overrides: dict[str, Any] | None = None,
                       training_run_id: str | None = None,
                       checkpoint_path: str | None = None,
                       performance_metrics: dict[str, float] | None = None) -> str:
        """Create a new version of a model."""
        if model_id not in self.models:
            raise ValueError(f"Model {model_id} not registered")

        base_spec = self.models[model_id]
        if spec_overrides:
            spec = ModelSpec(
                model_id=model_id,
                name=base_spec.name,
                model_type=base_spec.model_type,
                task_type=base_spec.task_type,
                num_layers=spec_overrides.get("num_layers", base_spec.num_layers),
                hidden_size=spec_overrides.get("hidden_size", base_spec.hidden_size),
                num_attention_heads=spec_overrides.get("num_attention_heads", base_spec.num_attention_heads),
                intermediate_size=spec_overrides.get("intermediate_size", base_spec.intermediate_size),
                max_position_embeddings=spec_overrides.get("max_position_embeddings", base_spec.max_position_embeddings),
                vocab_size=spec_overrides.get("vocab_size", base_spec.vocab_size),
                max_sequence_length=spec_overrides.get("max_sequence_length", base_spec.max_sequence_length),
                dropout=spec_overrides.get("dropout", base_spec.dropout),
            )
        else:
            spec = base_spec

        version_id = f"ver-{hashlib.sha256(f'{model_id}|{version}|{time.time()}'.encode()).hexdigest()[:12]}"

        version = ModelVersion(
            version_id=version_id,
            model_id=model_id,
            version=version,
            spec=spec,
            config=ModelConfig(spec=spec),
            training_run_id=training_run_id,
            performance_metrics=performance_metrics or {},
        )
        self.versions[version_id] = version
        self.model_versions[model_id].append(version_id)
        self.stats["versions_created"] += 1
        return version_id

    def get_version(self, version_id: str) -> ModelVersion | None:
        return self.versions.get(version_id)

    def get_model_versions(self, model_id: str) -> list[ModelVersion]:
        return [self.versions[vid] for vid in self.model_versions.get(model_id, []) if vid in self.versions]

    def deploy_version(self,
                       version_id: str,
                       release_name: str | None = None,
                       release_notes: str = "",
                       approval_required: bool = True) -> str:
        """Deploy a model version as a release."""
        version = self.versions.get(version_id)
        if version is None:
            raise ValueError(f"Version {version_id} not found")

        release_id = f"rel-{hashlib.sha256(f'{version_id}|{time.time()}'.encode()).hexdigest()[:12]}"
        release_name = release_name or f"release-{version.version}"

        release = ModelRelease(
            release_id=release_id,
            model_id=version.model_id,
            version_id=version_id,
            release_name=release_name,
            release_notes=release_notes,
            approval_required=approval_required,
            status="approved" if not approval_required else "proposed",
        )
        self.releases[release_id] = release
        self.stats["releases_created"] += 1

        if not approval_required:
            self._deploy_release(release_id)

        return release_id

    def approve_release(self, release_id: str, approved_by: str) -> bool:
        """Approve a release for deployment."""
        release = self.releases.get(release_id)
        if release is None or release.status != "proposed":
            return False

        release.approved_by = approved_by
        release.approved_at = time.time()
        release.status = "approved"
        return self._deploy_release(release_id)

    def _deploy_release(self, release_id: str) -> bool:
        """Deploy a release (make it the active version)."""
        release = self.releases.get(release_id)
        if release is None:
            return False

        version = self.versions.get(release.version_id)
        if version is None:
            return False

        # Deploy the version
        self.deployed_versions[version.model_id] = version.version_id
        version.deployed_at = time.time()
        version.deployment_status = "deployed"
        release.deployed_at = time.time()
        release.status = "deployed"

        self.stats["deployments"] += 1
        return True

    def rollback(self,
                 model_id: str,
                 previous_version_id: str) -> str:
        """Rollback to a previous version."""
        version = self.versions.get(previous_version_id)
        if version is None or version.model_id != model_id:
            raise ValueError(f"Version {previous_version_id} not found for model {model_id}")

        # Deploy the previous version
        release_id = f"rel-{hashlib.sha256(f'rollback-{model_id}|{time.time()}'.encode()).hexdigest()[:12]}"
        release = ModelRelease(
            release_id=release_id,
            model_id=model_id,
            version_id=previous_version_id,
            release_name=f"rollback-{version.version}",
            release_notes=f"Rollback to version {version.version}",
            approval_required=False,
            status="approved",
        )
        self.releases[release_id] = release
        self._deploy_release(release_id)
        self.stats["rollbacks"] += 1
        return release_id

    def retire_version(self, version_id: str) -> bool:
        """Retire a model version."""
        version = self.versions.get(version_id)
        if version is None:
            return False

        version.deployment_status = "retired"
        version.retired_at = time.time()

        # If this was the deployed version, undeploy it
        model_id = version.model_id
        if self.deployed_versions.get(model_id) == version_id:
            del self.deployed_versions[model_id]

        return True

    def get_deployed_version(self, model_id: str) -> ModelVersion | None:
        """Get the currently deployed version of a model."""
        version_id = self.deployed_versions.get(model_id)
        if version_id is None:
            return None
        return self.versions.get(version_id)

    def get_stats(self) -> dict[str, Any]:
        return {
            "models_registered": self.stats["models_registered"],
            "versions_created": self.stats["versions_created"],
            "releases_created": self.stats["releases_created"],
            "deployments": self.stats["deployments"],
            "rollbacks": self.stats["rollbacks"],
            "models": len(self.models),
            "versions": len(self.versions),
            "releases": len(self.releases),
            "deployed_versions": len(self.deployed_versions),
        }


# Global model registry manager instance
_model_registry_manager: ModelRegistryManager | None = None


def get_model_registry_manager() -> ModelRegistryManager:
    """Get or create the global ModelRegistryManager instance."""
    global _model_registry_manager
    if _model_registry_manager is None:
        _model_registry_manager = ModelRegistryManager()
    return _model_registry_manager


__all__ = [
    "ModelVersion",
    "ModelRelease",
    "ModelRegistryManager",
    "get_model_registry_manager",
]
