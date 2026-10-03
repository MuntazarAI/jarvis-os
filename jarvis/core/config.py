"""JARVIS configuration with layered overrides and validation."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, fields, asdict
from pathlib import Path
from typing import Any


DEFAULT_HOME = Path(os.environ.get("JARVIS_HOME", Path.home() / ".jarvis-os"))


@dataclass
class PathsConfig:
    home: Path = DEFAULT_HOME
    db: str = "jarvis.db"
    events: str = "events.db"
    logs: str = "logs"
    screenshots: str = "screenshots"
    captures: str = "captures"
    exports: str = "exports"

    def resolve(self, name: str) -> Path:
        base = Path(self.home)
        target = base / getattr(self, name)
        return target


@dataclass
class CognitiveConfig:
    """Controls the Master Cognitive Loop."""

    max_cycles: int = 1000
    max_cycle_seconds: float = 30.0
    reasoning_budget: int = 8000
    time_budget_seconds: float = 30.0
    memory_budget: int = 64
    tool_budget: int = 24
    attention_budget: float = 1.0
    hypothesis_limit: int = 5
    evidence_limit: int = 200
    timeline_gap_tolerance_seconds: float = 1.0
    simple_task_threshold: int = 3
    complex_task_threshold: int = 10
    confidence_threshold_auto: float = 0.85
    auto_approve_risk_below: float = 0.3


@dataclass
class MemoryConfig:
    working_capacity: int = 40
    short_term_hours: int = 24
    decay_half_life_days: float = 30.0
    archive_after_days: float = 90.0
    expire_after_days: float = 365.0
    consolidate_every_cycles: int = 50
    dedup_similarity: float = 0.82
    rooms: list[str] = field(
        default_factory=lambda: [
            "Home",
            "Central Hall",
            "Current Situation Room",
            "Observation Room",
            "Study Room",
            "Projects Room",
            "Project Lab",
            "People Room",
            "People Wing",
            "Knowledge Library",
            "Skills Workshop",
            "Procedure Library",
            "Hypothesis Room",
            "Evidence Archive",
            "Idea Laboratory",
            "Experiences",
            "Events Archive",
            "Future Plans",
            "Archive",
            "Trash",
        ]
    )


@dataclass
class PolicyConfig:
    require_approval_above_risk: float = 0.5
    block_high_risk_paths: list[str] = field(
        default_factory=lambda: ["/etc/shadow", "/etc/sudoers", "~/.ssh/id_rsa"]
    )
    local_only: bool = True
    record_audit: bool = True
    emergency_stop_file: str = "EMERGENCY_STOP"
    proactivity: str = "assisted"
    quiet_hours: list[int] = field(default_factory=lambda: list(range(23, 7)))


@dataclass
class ModelConfig:
    planner_model: str = "local-planner"
    reasoning_model: str = "local-reasoning"
    fast_model: str = "local-fast"
    vision_model: str = "local-vision"
    embedding_dim: int = 64
    cloud_enabled: bool = False
    fallback_enabled: bool = True
    ollama_enabled: bool = True
    ollama_host: str = "http://localhost:11434"
    llm_timeout: float = 120.0
    llm_max_tokens: int = 512


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8765


@dataclass
class DeviceFabricConfig:
    enabled: bool = True
    state_path: str = "device-fabric.json"
    heartbeat_timeout_s: float = 120.0
    max_devices: int = 64


@dataclass
class DeviceTransportConfig:
    """Real network transport for the device fabric (3.10).

    Backwards compatible: everything defaults to off/loopback. No
    credentials live here — device secrets stay in 0600 device-keys.json.
    """

    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 0  # 0 = pick an ephemeral port at serve time
    timeout_s: float = 15.0
    max_connections: int = 16
    max_frame_bytes: int = 262144
    reconnect_initial_s: float = 1.0
    reconnect_max_s: float = 60.0
    heartbeat_interval_s: float = 60.0
    keys_path: str = "device-keys.json"


@dataclass
class JarvisConfig:
    paths: PathsConfig = field(default_factory=PathsConfig)
    cognitive: CognitiveConfig = field(default_factory=CognitiveConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    policy: PolicyConfig = field(default_factory=PolicyConfig)
    models: ModelConfig = field(default_factory=ModelConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    device_fabric: DeviceFabricConfig = field(default_factory=DeviceFabricConfig)
    device_transport: DeviceTransportConfig = field(default_factory=DeviceTransportConfig)
    personality: dict[str, Any] = field(
        default_factory=lambda: {
            "formality": "professional",
            "humor": "dry",
            "length": "concise",
        }
    )
    version: int = 1

    # -- serialization ---------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        raw = asdict(self)
        raw["paths"]["home"] = str(self.paths.home)
        return raw

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "JarvisConfig":
        cfg = cls()
        for f in fields(cls):
            if f.name not in data:
                continue
            value = data[f.name]
            current = getattr(cfg, f.name)
            if hasattr(current, "__dataclass_fields__") and isinstance(value, dict):
                for sub in fields(current):
                    if sub.name in value:
                        setattr(current, sub.name, value[sub.name])
                if f.name == "paths" and "home" in value:
                    current.home = Path(value["home"])
            else:
                setattr(cfg, f.name, value)
        return cfg

    # -- persistence -----------------------------------------------------
    @property
    def config_file(self) -> Path:
        return Path(self.paths.home) / "config.json"

    def save(self) -> Path:
        target = self.config_file
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.to_dict(), indent=2))
        return target

    @classmethod
    def load(cls) -> "JarvisConfig":
        cfg = cls()
        path = cfg.config_file
        if path.exists():
            try:
                cfg = cls.from_dict(json.loads(path.read_text()))
            except (json.JSONDecodeError, OSError):
                pass
        cfg.apply_env_overrides()
        cfg.validate()
        return cfg

    # -- env / validation ------------------------------------------------
    def apply_env_overrides(self) -> None:
        home = os.environ.get("JARVIS_HOME")
        if home:
            self.paths.home = Path(home)
        port = os.environ.get("JARVIS_PORT")
        if port and port.isdigit():
            self.server.port = int(port)
        local_only = os.environ.get("JARVIS_LOCAL_ONLY")
        if local_only is not None:
            self.policy.local_only = local_only.lower() in ("1", "true", "yes")
        cloud = os.environ.get("JARVIS_CLOUD")
        if cloud is not None:
            self.models.cloud_enabled = cloud.lower() in ("1", "true", "yes")

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.cognitive.max_cycle_seconds <= 0:
            errors.append("cognitive.max_cycle_seconds must be > 0")
        if self.cognitive.tool_budget < 1:
            errors.append("cognitive.tool_budget must be >= 1")
        if not 0.0 <= self.policy.require_approval_above_risk <= 1.0:
            errors.append("policy.require_approval_above_risk must be 0..1")
        if self.policy.proactivity not in ("passive", "suggestive", "assisted", "automated"):
            errors.append("policy.proactivity must be passive|suggestive|assisted|automated")
        if self.memory.decay_half_life_days <= 0:
            errors.append("memory.decay_half_life_days must be > 0")
        if self.models.embedding_dim < 8:
            errors.append("models.embedding_dim must be >= 8")
        if self.server.port < 1 or self.server.port > 65535:
            errors.append("server.port out of range")
        if errors:
            raise ValueError("; ".join(errors))
        return errors

    def ensure_dirs(self) -> None:
        for name in ("home", "logs", "screenshots", "captures", "exports"):
            self.paths.resolve(name).mkdir(parents=True, exist_ok=True)
