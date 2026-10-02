"""Small, dependency-free plugin contract for JARVIS-OS."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PluginRequest:
    operation: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PluginResponse:
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class Plugin:
    """Base contract for bounded JARVIS plugins."""

    name = "unnamed"
    version = "0.0.0"
    description = ""
    capabilities: tuple[str, ...] = ()

    def health(self) -> dict[str, str]:
        return {"status": "ok", "plugin": self.name}

    def handle(self, request: PluginRequest) -> PluginResponse:
        raise NotImplementedError
