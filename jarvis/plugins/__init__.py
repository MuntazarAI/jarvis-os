"""
Plugin System — JARVIS-OS dynamic plugin loading.

Provides sandboxed plugin loading for extending JARVIS-OS functionality.
Plugins are loaded from manifests, run in restricted execution contexts,
and require PolicyEngine approval for activation.
"""

from .plugin_system import (
    PluginSystem,
    PluginManifest,
    PluginInstance,
    get_plugin_system,
)

__all__ = [
    "PluginSystem",
    "PluginManifest",
    "PluginInstance",
    "get_plugin_system",
]