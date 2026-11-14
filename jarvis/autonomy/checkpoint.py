"""
Checkpoint Management - Serialization and Recovery

Provides checkpoint serialization, validation, and recovery utilities
for the autonomous agent loop.
"""

from __future__ import annotations

import json
import hashlib
import gzip
import shutil
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, TypeVar, Generic
from threading import Lock

from .agent_loop import LoopCheckpoint, LoopTask, TaskQueue, TaskStatus, TaskPriority


@dataclass
class CheckpointMetadata:
    """Metadata for a checkpoint file."""
    checkpoint_id: str
    iteration: int
    timestamp: float
    size_bytes: int
    compressed: bool
    checksum: str
    version: int = 1
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CheckpointMetadata":
        return cls(**data)


class CheckpointManager:
    """Manages checkpoint storage, validation, and recovery."""

    def __init__(self, checkpoint_dir: str = "checkpoints", compress: bool = True):
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(exist_ok=True)
        self.compress = compress
        self._lock = Lock()
        self._metadata_file = self.checkpoint_dir / "metadata.json"
        self._metadata: Dict[str, CheckpointMetadata] = {}
        self._load_metadata()

    def _load_metadata(self):
        if self._metadata_file.exists():
            try:
                data = json.loads(self._metadata_file.read_text())
                self._metadata = {
                    k: CheckpointMetadata.from_dict(v) for k, v in data.items()
                }
            except Exception:
                self._metadata = {}

    def _save_metadata(self):
        data = {k: v.to_dict() for k, v in self._metadata.items()}
        self._metadata_file.write_text(json.dumps(data, indent=2))

    def _compute_checksum(self, data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()[:16]

    def save(self, checkpoint: LoopCheckpoint, tags: List[str] = None) -> str:
        """Save checkpoint to disk with metadata."""
        with self._lock:
            # Serialize
            json_data = checkpoint.to_json().encode()
            original_size = len(json_data)

            # Compress if enabled
            if self.compress:
                json_data = gzip.compress(json_data)

            # Compute checksum
            checksum = self._compute_checksum(json_data)

            # Generate filename
            filename = f"checkpoint_{checkpoint.iteration}_{int(checkpoint.timestamp)}_{checksum}.json{'z' if self.compress else ''}"
            filepath = self.checkpoint_dir / filename

            # Write
            filepath.write_bytes(json_data)

            # Metadata
            meta = CheckpointMetadata(
                checkpoint_id=checkpoint.checkpoint_id,
                iteration=checkpoint.iteration,
                timestamp=checkpoint.timestamp,
                size_bytes=len(json_data),
                compressed=self.compress,
                checksum=checksum,
                tags=tags or []
            )
            self._metadata[filename] = meta
            self._save_metadata()

            # Cleanup old (keep last 20)
            self._cleanup(keep=20)

            return str(filepath)

    def _cleanup(self, keep: int = 20):
        """Remove old checkpoints, keep most recent."""
        checkpoints = sorted(
            [(m.timestamp, f) for f, m in self._metadata.items()],
            reverse=True
        )
        for _, filename in checkpoints[keep:]:
            filepath = self.checkpoint_dir / filename
            if filepath.exists():
                filepath.unlink()
            del self._metadata[filename]
        self._save_metadata()

    def load(self, filename: str) -> Optional[LoopCheckpoint]:
        """Load checkpoint from file."""
        filepath = self.checkpoint_dir / filename
        if not filepath.exists():
            return None

        try:
            data = filepath.read_bytes()
            if self.compress and filename.endswith(".jsonz"):
                data = gzip.decompress(data)
            return LoopCheckpoint.from_json(data.decode())
        except Exception as e:
            print(f"Failed to load checkpoint {filename}: {e}")
            return None

    def load_latest(self) -> Optional[LoopCheckpoint]:
        """Load most recent valid checkpoint."""
        checkpoints = sorted(
            [(m.timestamp, f) for f, m in self._metadata.items()],
            reverse=True
        )
        for _, filename in checkpoints:
            cp = self.load(filename)
            if cp:
                return cp
        return None

    def load_by_iteration(self, iteration: int) -> Optional[LoopCheckpoint]:
        """Load checkpoint for specific iteration."""
        for filename, meta in self._metadata.items():
            if meta.iteration == iteration:
                return self.load(filename)
        return None

    def list_checkpoints(self) -> List[CheckpointMetadata]:
        """List all checkpoints sorted by timestamp (newest first)."""
        return sorted(self._metadata.values(), key=lambda m: m.timestamp, reverse=True)

    def validate_checkpoint(self, filename: str) -> bool:
        """Validate checkpoint integrity."""
        filepath = self.checkpoint_dir / filename
        if not filepath.exists():
            return False

        meta = self._metadata.get(filename)
        if not meta:
            return False

        try:
            data = filepath.read_bytes()
            checksum = self._compute_checksum(data)
            return checksum == meta.checksum
        except Exception:
            return False

    def get_recovery_info(self) -> Dict[str, Any]:
        """Get information for recovery UI."""
        latest = self.load_latest()
        return {
            "total_checkpoints": len(self._metadata),
            "latest_iteration": latest.iteration if latest else 0,
            "latest_timestamp": latest.timestamp if latest else 0,
            "checkpoints": [m.to_dict() for m in self.list_checkpoints()],
            "storage_size_bytes": sum(m.size_bytes for m in self._metadata.values()),
        }


class LoopRecovery:
    """Handles crash recovery for the autonomous loop."""

    def __init__(self, task_queue: TaskQueue, checkpoint_manager: CheckpointManager):
        self.task_queue = task_queue
        self.checkpoint_manager = checkpoint_manager

    def recover(self) -> Dict[str, Any]:
        """Recover from latest checkpoint."""
        checkpoint = self.checkpoint_manager.load_latest()
        if not checkpoint:
            return {"recovered": False, "reason": "No checkpoint found"}

        # Restore pending tasks
        restored = 0
        for task_data in checkpoint.pending_tasks:
            task = LoopTask.from_dict(task_data)
            # Reset running tasks to pending
            if task.status == TaskStatus.RUNNING:
                task.status = TaskStatus.PENDING
                task.started_at = None
            self.task_queue.enqueue(task)
            restored += 1

        # Restore completed/failed counts
        # (These are informational, actual tasks are in queue)

        return {
            "recovered": True,
            "checkpoint_id": checkpoint.checkpoint_id,
            "iteration": checkpoint.iteration,
            "timestamp": checkpoint.timestamp,
            "restored_tasks": restored,
            "completed_count": checkpoint.completed_count,
            "failed_count": checkpoint.failed_count,
        }

    def can_recover(self) -> bool:
        """Check if recovery is possible."""
        return self.checkpoint_manager.load_latest() is not None


def create_checkpoint_manager(checkpoint_dir: str = "checkpoints",
                               compress: bool = True) -> CheckpointManager:
    """Factory for checkpoint manager."""
    return CheckpointManager(checkpoint_dir, compress)


def create_loop_recovery(task_queue: TaskQueue,
                         checkpoint_dir: str = "checkpoints") -> LoopRecovery:
    """Factory for loop recovery."""
    manager = CheckpointManager(checkpoint_dir)
    return LoopRecovery(task_queue, manager)