"""
Plugin System — JARVIS-OS dynamic plugin loading.

Provides sandboxed plugin loading for extending JARVIS-OS functionality.
Plugins are loaded from manifests, run in restricted execution contexts,
and require PolicyEngine approval for activation.

Also provides base classes for plugin development:
- Plugin: Base class for plugins
- PluginRequest: Request to a plugin
- PluginResponse: Response from a plugin
"""

from .plugin_system import (
    PluginSystem,
    PluginManifest,
    PluginInstance,
    Plugin,
    PluginRequest,
    PluginResponse,
    get_plugin_system,
)

__all__ = [
    "PluginSystem",
    "PluginManifest",
    "PluginInstance",
    "Plugin",
    "PluginRequest",
    "PluginResponse",
    "get_plugin_system",
]