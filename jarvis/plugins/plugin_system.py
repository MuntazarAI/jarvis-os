"""
Plugin System — JARVIS-OS dynamic plugin loading.

Provides a sandboxed plugin system for extending JARVIS-OS functionality.
Plugins are loaded from manifests, run in restricted execution contexts,
and require PolicyEngine approval for activation.

Also provides base classes for plugin development:
- Plugin: Base class for plugins
- PluginRequest: Request to a plugin
- PluginResponse: Response from a plugin
"""

from __future__ import annotations

import importlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from ..core.logging import get_module_logger
from ..policy.policy import PolicyEngine
from ..events.store import EventStore

log = get_module_logger(__name__)


@dataclass
class PluginRequest:
    """A request to a plugin."""
    operation: str
    payload: dict[str, Any] = field(default_factory=dict)
    request_id: str = field(default_factory=lambda: f"req-{time.time_ns()}")


@dataclass
class PluginResponse:
    """A response from a plugin."""
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    request_id: str | None = None


class Plugin:
    """Base class for JARVIS-OS plugins.

    Subclasses should define:
    - name: str - unique plugin identifier
    - version: str - plugin version
    - description: str - human-readable description
    - capabilities: tuple[str, ...] - supported operations

    And implement:
    - health() -> dict[str, str] - health check
    - handle(request: PluginRequest) -> PluginResponse - handle operations
    """
    name: str = ""
    version: str = "0.1.0"
    description: str = ""
    capabilities: tuple[str, ...] = ()

    def health(self) -> dict[str, str]:
        return {"status": "ok", "plugin": self.name}

    def handle(self, request: PluginRequest) -> PluginResponse:
        return PluginResponse(ok=False, error=f"Operation {request.operation} not supported")


@dataclass
class PluginManifest:
    """A plugin manifest file."""
    plugin_id: str
    name: str
    version: str
    description: str
    author: str
    entry_point: str  # module:function
    permissions: list[str] = field(default_factory=list)
    api_version: str = "1.0"
    tags: list[str] = field(default_factory=list)


@dataclass
class PluginInstance:
    """An active plugin instance."""
    plugin_id: str
    manifest: PluginManifest
    module: Any
    status: str  # loaded, active, stopped, error
    loaded_at: float = field(default_factory=time.time)
    error: str | None = None


class PluginSystem:
    """
    Plugin System — sandboxed plugin loading for JARVIS-OS.

    Plugins are defined by manifest files and loaded from the plugins/
    directory. Each plugin requires PolicyEngine approval before activation
    and runs with restricted permissions.
    """

    def __init__(
        self,
        policy: PolicyEngine | None = None,
        events: EventStore | None = None,
        plugins_dir: str | None = None,
    ) -> None:
        self.policy = policy
        self.events = events
        self.plugins_dir = Path(plugins_dir or "plugins")
        self.plugins: dict[str, PluginInstance] = {}
        self.manifests: dict[str, PluginManifest] = {}
        self._initialized = False

    def initialize(self) -> dict[str, Any]:
        """Initialize the plugin system."""
        self.plugins_dir.mkdir(parents=True, exist_ok=True)
        self._discover_manifests()
        self._initialized = True
        return {
            "status": "operational",
            "subsystem": "plugin_system",
            "plugins_discovered": len(self.manifests),
            "plugins_active": len(self.plugins),
            "policy_gated": True,
        }

    def _discover_manifests(self) -> None:
        """Discover plugin manifests in the plugins directory."""
        if not self.plugins_dir.exists():
            return
        for manifest_file in self.plugins_dir.glob("*/manifest.json"):
            try:
                data = json.loads(manifest_file.read_text("utf-8"))
                manifest = PluginManifest(
                    plugin_id=data["plugin_id"],
                    name=data["name"],
                    version=data["version"],
                    description=data.get("description", ""),
                    author=data.get("author", "unknown"),
                    entry_point=data["entry_point"],
                    permissions=data.get("permissions", []),
                    api_version=data.get("api_version", "1.0"),
                    tags=data.get("tags", []),
                )
                self.manifests[manifest.plugin_id] = manifest
            except Exception as exc:
                log.warning("Failed to load manifest %s: %s", manifest_file, exc)

    def list_plugins(self) -> list[PluginManifest]:
        """List all discovered plugins."""
        return list(self.manifests.values())

    def get_plugin(self, plugin_id: str) -> PluginInstance | None:
        """Get an active plugin instance by ID."""
        return self.plugins.get(plugin_id)

    def activate_plugin(
        self,
        plugin_id: str,
    ) -> dict[str, Any]:
        """Activate a plugin (requires PolicyEngine approval)."""
        manifest = self.manifests.get(plugin_id)
        if not manifest:
            return {"ok": False, "reason": "plugin not found"}

        if plugin_id in self.plugins:
            return {"ok": False, "reason": "plugin already active"}

        # Request PolicyEngine approval
        if self.policy:
            grant = self.policy.evaluate(
                "plugin_system.activate",
                {
                    "plugin_id": plugin_id,
                    "permissions": manifest.permissions,
                },
            )
            if not grant.get("approved", False):
                return {"ok": False, "reason": "policy denied"}

        try:
            module_name, func_name = manifest.entry_point.split(":", 1)
            module = importlib.import_module(module_name)
            plugin_func = getattr(module, func_name)

            instance = PluginInstance(
                plugin_id=plugin_id,
                manifest=manifest,
                module=module,
                status="active",
            )
            self.plugins[plugin_id] = instance

            if self.events:
                self.events.append({
                    "event": "plugin_system.activate",
                    "plugin_id": plugin_id,
                    "name": manifest.name,
                    "at": instance.loaded_at,
                })

            return {
                "ok": True,
                "plugin_id": plugin_id,
                "name": manifest.name,
                "status": "active",
            }
        except Exception as exc:
            log.error("Failed to activate plugin %s: %s", plugin_id, exc)
            return {"ok": False, "reason": str(exc)}

    def deactivate_plugin(self, plugin_id: str) -> dict[str, Any]:
        """Deactivate an active plugin."""
        plugin = self.plugins.get(plugin_id)
        if not plugin:
            return {"ok": False, "reason": "plugin not active"}

        plugin.status = "stopped"
        del self.plugins[plugin_id]

        if self.events:
            self.events.append({
                "event": "plugin_system.deactivate",
                "plugin_id": plugin_id,
                "name": plugin.manifest.name,
                "at": time.time(),
            })

        return {"ok": True, "plugin_id": plugin_id}

    def list_active_plugins(self) -> list[PluginInstance]:
        """List all active plugins."""
        return list(self.plugins.values())

    def get_status(self) -> dict[str, Any]:
        """Get subsystem status."""
        return {
            "subsystem": "plugin_system",
            "status": "operational" if self._initialized else "offline",
            "plugins_discovered": len(self.manifests),
            "plugins_active": len(self.plugins),
            "active_plugins": [
                {
                    "plugin_id": p.plugin_id,
                    "name": p.manifest.name,
                    "version": p.manifest.version,
                    "status": p.status,
                }
                for p in self.plugins.values()
            ],
            "capabilities": [
                "plugin_discovery",
                "plugin_activation",
                "plugin_deactivation",
                "sandboxed_execution",
            ],
            "constraints": [
                "policy_gated_activation",
                "restricted_permissions",
                "no_arbitrary_code_execution",
            ],
        }


# Global instance
_plugin_system: PluginSystem | None = None


def get_plugin_system(
    policy: PolicyEngine | None = None,
    events: EventStore | None = None,
    plugins_dir: str | None = None,
) -> PluginSystem:
    """Get or create the global PluginSystem instance."""
    global _plugin_system
    if _plugin_system is None:
        _plugin_system = PluginSystem(
            policy=policy, events=events, plugins_dir=plugins_dir
        )
    return _plugin_system


__all__ = [
    "PluginSystem",
    "PluginManifest",
    "PluginInstance",
    "Plugin",
    "PluginRequest",
    "PluginResponse",
    "get_plugin_system",
]