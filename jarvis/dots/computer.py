"""Dot Computers — compute environments for individual Dots (OpenDots-inspired).

Each Dot can have its own computer, using OpenBot-style containers.
The computer provides an isolated environment where the Dot can execute
tools and actions, subject to PolicyEngine gating.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from ..core.types import now


@dataclass
class DotComputer:
    """A compute environment for a Dot.

    Each Dot can be assigned its own computer. The computer provides
    isolated execution environment with bounded tool access.
    """

    computer_id: str = field(default_factory=lambda: f"computer-{uuid4().hex[:12]}")
    dot_id: str = ""  # Dot this computer belongs to
    name: str = ""
    description: str = ""

    # Computer configuration
    os: str = "linux"  # linux, windows, macos
    arch: str = "x86_64"  # x86_64, arm64, riscv
    container_image: str = ""  # Container image to use
    container_registry: str = ""  # Container registry URL

    # Resource limits (Colibri-inspired: efficient resource usage)
    max_memory_mb: int = 2048  # 2 GB default
    max_cpu_cores: float = 2.0  # 2 CPU cores default
    max_disk_gb: int = 20  # 20 GB default
    max_runtime_s: float = 3600.0  # 1 hour max runtime

    # Network access (bounded, PolicyEngine-gated)
    network_enabled: bool = False
    allowed_domains: list[str] = field(default_factory=list)
    blocked_domains: list[str] = field(default_factory=list)

    # Tool access (bounded, PolicyEngine-gated)
    allowed_tools: list[str] = field(default_factory=list)
    blocked_tools: list[str] = field(default_factory=list)

    # Status
    status: str = "created"  # created, running, stopped, failed
    last_heartbeat: float = 0.0
    created_at: float = field(default_factory=now)
    updated_at: float = field(default_factory=now)

    # Metadata
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "computer_id": self.computer_id, "dot_id": self.dot_id,
            "name": self.name, "description": self.description,
            "os": self.os, "arch": self.arch,
            "container_image": self.container_image,
            "container_registry": self.container_registry,
            "max_memory_mb": self.max_memory_mb,
            "max_cpu_cores": self.max_cpu_cores,
            "max_disk_gb": self.max_disk_gb,
            "max_runtime_s": self.max_runtime_s,
            "network_enabled": self.network_enabled,
            "allowed_domains": list(self.allowed_domains),
            "blocked_domains": list(self.blocked_domains),
            "allowed_tools": list(self.allowed_tools),
            "blocked_tools": list(self.blocked_tools),
            "status": self.status,
            "last_heartbeat": self.last_heartbeat,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DotComputer":
        return cls(
            computer_id=data.get("computer_id", f"computer-{uuid4().hex[:12]}"),
            dot_id=data.get("dot_id", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            os=data.get("os", "linux"),
            arch=data.get("arch", "x86_64"),
            container_image=data.get("container_image", ""),
            container_registry=data.get("container_registry", ""),
            max_memory_mb=int(data.get("max_memory_mb", 2048)),
            max_cpu_cores=float(data.get("max_cpu_cores", 2.0)),
            max_disk_gb=int(data.get("max_disk_gb", 20)),
            max_runtime_s=float(data.get("max_runtime_s", 3600.0)),
            network_enabled=bool(data.get("network_enabled", False)),
            allowed_domains=list(data.get("allowed_domains", [])),
            blocked_domains=list(data.get("blocked_domains", [])),
            allowed_tools=list(data.get("allowed_tools", [])),
            blocked_tools=list(data.get("blocked_tools", [])),
            status=data.get("status", "created"),
            last_heartbeat=float(data.get("last_heartbeat", 0.0)),
            created_at=data.get("created_at", now()),
            updated_at=data.get("updated_at", now()),
            metadata=dict(data.get("metadata", {})),
        )