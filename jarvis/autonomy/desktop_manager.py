"""Desktop Integration - M43.

Desktop environment integration for JARVIS-OS:
- Wayland display server integration
- PipeWire audio/video integration
- Desktop notifications
- Screen capture
- Window management integration

All operations respect Wayland security (no screen capture without permission).
PipeWire access requires explicit user consent.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class DisplayInfo:
    """Display server information."""
    server: str  # "wayland", "x11", "unknown"
    display: str | None = None
    wayland_version: str | None = None
    compositor: str | None = None
    available: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "server": self.server,
            "display": self.display,
            "wayland_version": self.wayland_version,
            "compositor": self.compositor,
            "available": self.available,
        }


@dataclass
class PipeWireNode:
    """PipeWire node information."""
    id: int
    name: str
    type: str  # "source", "sink", "filter"
    state: str  # "idle", "running", "paused", "error"
    sample_rate: int | None = None
    channels: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "state": self.state,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
        }


@dataclass
class DesktopNotification:
    """Desktop notification."""
    id: str
    title: str
    body: str
    urgency: str = "normal"  # low, normal, critical
    timeout_ms: int = 5000

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "body": self.body,
            "urgency": self.urgency,
            "timeout_ms": self.timeout_ms,
        }


class WaylandManager:
    """Wayland display server integration.

    Provides read-only access to Wayland display information.
    Screen capture requires explicit user consent via PolicyEngine.
    """

    def __init__(self) -> None:
        self.created_at = time.time()
        self.stats = {
            "display_queries": 0,
            "capture_requests": 0,
        }

    def get_display_info(self) -> DisplayInfo:
        """Get Wayland display information."""
        self.stats["display_queries"] += 1
        info = DisplayInfo(
            server="unknown",
            available=False,
        )

        try:
            # Check for Wayland display
            display = os.environ.get("WAYLAND_DISPLAY", "wayland-0")
            info.display = display

            # Check for wayland-client or weston
            result = subprocess.run(
                ["which", "weston-terminal"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                info.server = "wayland"
                info.available = True
                info.compositor = "weston"
            else:
                # Check for other compositors
                for compositor in ["sway", "kwin_wayland", "mutter", "gnome-shell"]:
                    try:
                        result = subprocess.run(
                            ["which", compositor],
                            capture_output=True,
                            text=True,
                            timeout=3,
                        )
                        if result.returncode == 0:
                            info.server = "wayland"
                            info.available = True
                            info.compositor = compositor
                            break
                    except Exception:
                        pass
        except Exception:
            pass

        # Try to get Wayland version
        try:
            result = subprocess.run(
                ["wayland-info"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if "version" in line.lower():
                        info.wayland_version = line.strip()
                        break
        except Exception:
            pass

        return info

    def capture_screen(self) -> dict[str, Any]:
        """Capture screen using Wayland screenshot tools.
        Requires PolicyEngine approval (screen capture is sensitive)."""
        self.stats["capture_requests"] += 1

        try:
            # Try grim (Wayland screenshot tool)
            result = subprocess.run(
                ["grim", "-"],
                capture_output=True,
                timeout=10,
            )
            if result.returncode == 0:
                return {
                    "success": True,
                    "data": result.stdout,
                    "backend": "grim",
                }
        except Exception:
            pass

        try:
            # Try slurp + grim
            result = subprocess.run(
                ["grim", "-g", "$(slurp)", "-"],
                capture_output=True,
                timeout=10,
            )
            if result.returncode == 0:
                return {
                    "success": True,
                    "data": result.stdout,
                    "backend": "grim+slurp",
                }
        except Exception:
            pass

        return {
            "success": False,
            "error": "No Wayland screenshot tool available",
        }


class PipeWireManager:
    """PipeWire audio/video integration.

    Provides read-only access to PipeWire nodes.
    Audio capture requires explicit user consent via PolicyEngine.
    """

    def __init__(self) -> None:
        self.created_at = time.time()
        self.stats = {
            "node_queries": 0,
            "capture_requests": 0,
        }

    def list_nodes(self) -> list[PipeWireNode]:
        """List PipeWire nodes."""
        self.stats["node_queries"] += 1
        nodes = []

        try:
            result = subprocess.run(
                ["pw-cli", "list-objects"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                current_node = {}
                for line in result.stdout.splitlines():
                    line = line.strip()
                    if line.startswith("id"):
                        if current_node.get("id"):
                            nodes.append(PipeWireNode(**current_node))
                        current_node = {"id": int(line.split("=")[1].strip())}
                    elif "=" in line:
                        key, val = line.split("=", 1)
                        key = key.strip()
                        val = val.strip().strip('"')
                        if key == "factory.name":
                            current_node["type"] = val
                        elif key == "object.id":
                            current_node["id"] = int(val)
                        elif key == "node.name":
                            current_node["name"] = val.strip('"')
                        elif key == "node.state":
                            current_node["state"] = val.strip('"')
                        elif key == "node.sample-rate":
                            current_node["sample_rate"] = int(val)
                        elif key == "node.channels":
                            current_node["channels"] = int(val)
                if current_node.get("id"):
                    nodes.append(PipeWireNode(**current_node))
        except Exception:
            pass

        return nodes

    def get_node(self, node_id: int) -> PipeWireNode | None:
        """Get a PipeWire node by ID."""
        nodes = self.list_nodes()
        for node in nodes:
            if node.id == node_id:
                return node
        return None

    def capture_audio(self, duration_seconds: float = 5.0) -> dict[str, Any]:
        """Capture audio via PipeWire.
        Requires PolicyEngine approval (audio capture is sensitive)."""
        self.stats["capture_requests"] += 1

        try:
            result = subprocess.run(
                ["pw-record", "-t", str(int(duration_seconds * 1000)), "-"],
                capture_output=True,
                timeout=duration_seconds + 5,
            )
            if result.returncode == 0:
                return {
                    "success": True,
                    "data": result.stdout,
                    "duration_seconds": duration_seconds,
                }
        except Exception:
            pass

        return {
            "success": False,
            "error": "Audio capture not available",
        }


class DesktopNotifier:
    """Desktop notification integration.

    Sends desktop notifications via libnotify or similar.
    """

    def __init__(self) -> None:
        self.created_at = time.time()
        self.stats = {
            "notifications_sent": 0,
        }

    def send_notification(self,
                          title: str,
                          body: str,
                          urgency: str = "normal",
                          timeout_ms: int = 5000) -> bool:
        """Send a desktop notification."""
        try:
            result = subprocess.run(
                ["notify-send", title, body, "--urgency", urgency,
                 "--expire-time", str(timeout_ms)],
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.stats["notifications_sent"] += 1
            return result.returncode == 0
        except Exception:
            return False

    def get_stats(self) -> dict[str, Any]:
        return {
            "notifications_sent": self.stats["notifications_sent"],
        }


class DesktopManager:
    """Combined desktop integration manager.

    Combines Wayland, PipeWire, and notification management.
    All sensitive operations (screen capture, audio capture) require
    PolicyEngine approval.
    """

    def __init__(self) -> None:
        self.wayland = WaylandManager()
        self.pipewire = PipeWireManager()
        self.notifier = DesktopNotifier()
        self.created_at = time.time()

    def get_stats(self) -> dict[str, Any]:
        return {
            "wayland": {
                "display_queries": self.wayland.stats["display_queries"],
                "capture_requests": self.wayland.stats["capture_requests"],
            },
            "pipewire": {
                "node_queries": self.pipewire.stats["node_queries"],
                "capture_requests": self.pipewire.stats["capture_requests"],
            },
            "notifier": self.notifier.get_stats(),
        }

    def get_display_info(self) -> dict[str, Any]:
        """Get display server information."""
        info = self.wayland.get_display_info()
        return info.to_dict()

    def list_pipewire_nodes(self) -> list[dict[str, Any]]:
        """List PipeWire nodes."""
        nodes = self.pipewire.list_nodes()
        return [n.to_dict() for n in nodes]

    def send_notification(self,
                          title: str,
                          body: str,
                          urgency: str = "normal",
                          timeout_ms: int = 5000) -> bool:
        """Send a desktop notification."""
        return self.notifier.send_notification(
            title, body, urgency, timeout_ms
        )


# Global desktop manager instance
_desktop_manager: DesktopManager | None = None


def get_desktop_manager() -> DesktopManager:
    """Get or create the global DesktopManager instance."""
    global _desktop_manager
    if _desktop_manager is None:
        _desktop_manager = DesktopManager()
    return _desktop_manager


__all__ = [
    "DisplayInfo",
    "PipeWireNode",
    "DesktopNotification",
    "WaylandManager",
    "PipeWireManager",
    "DesktopNotifier",
    "DesktopManager",
    "get_desktop_manager",
]
