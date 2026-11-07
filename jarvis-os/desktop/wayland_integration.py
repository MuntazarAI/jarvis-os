#!/usr/bin/env python3
"""
JARVIS-OS Desktop Integration
Wayland compositor integration for JARVIS-OS desktop environment.

This module provides:
- Wayland protocol extensions for JARVIS
- Desktop shell integration
- Window management policies
- Input handling with PolicyEngine gating
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable

logger = logging.getLogger(__name__)


@dataclass
class WaylandConfig:
    """Configuration for Wayland integration."""
    compositor: str = "weston"  # weston, sway, hyprland, kwin
    socket_name: str = "wayland-0"
    jrv_socket_name: str = "jarvis-wayland"
    enable_xwayland: bool = True
    policy_engine_socket: str = "/run/jarvis/policy.sock"


@dataclass
class WindowRule:
    """Window management rule."""
    app_id: str
    title_pattern: Optional[str] = None
    workspace: Optional[int] = None
    floating: bool = False
    fullscreen: bool = False
    opacity: float = 1.0
    tags: List[str] = field(default_factory=list)


class WaylandCompositor:
    """Manages Wayland compositor lifecycle and integration."""
    
    def __init__(self, config: WaylandConfig):
        self.config = config
        self._process: Optional[subprocess.Popen] = None
        self._socket_path: Optional[Path] = None
        self._window_rules: List[WindowRule] = []
        self._policy_client = None
    
    async def start(self) -> bool:
        """Start the Wayland compositor."""
        if self._process and self._process.poll() is None:
            logger.warning("Compositor already running")
            return True
        
        # Determine compositor command
        cmd = self._get_compositor_command()
        if not cmd:
            logger.error(f"Unsupported compositor: {self.config.compositor}")
            return False
        
        # Prepare environment
        env = os.environ.copy()
        env["WAYLAND_DISPLAY"] = self.config.socket_name
        env["XDG_SESSION_TYPE"] = "wayland"
        env["XDG_CURRENT_DESKTOP"] = "JARVIS-OS"
        
        # Start compositor
        try:
            self._process = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            
            # Wait for socket
            await self._wait_for_socket()
            
            # Apply window rules
            await self._apply_window_rules()
            
            logger.info(f"Started {self.config.compositor} on {self.config.socket_name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start compositor: {e}")
            return False
    
    def _get_compositor_command(self) -> Optional[List[str]]:
        """Get compositor command based on configuration."""
        if self.config.compositor == "weston":
            return ["weston", "--socket", self.config.socket_name]
        elif self.config.compositor == "sway":
            return ["sway", "--socket", self.config.socket_name]
        elif self.config.compositor == "hyprland":
            return ["Hyprland"]
        elif self.config.compositor == "kwin":
            return ["kwin_wayland", "--socket", self.config.socket_name]
        return None
    
    async def _wait_for_socket(self, timeout: float = 10.0) -> None:
        """Wait for Wayland socket to appear."""
        socket_path = Path(f"/run/user/{os.getuid()}/{self.config.socket_name}")
        start = asyncio.get_event_loop().time()
        
        while asyncio.get_event_loop().time() - start < timeout:
            if socket_path.exists():
                self._socket_path = socket_path
                return
            await asyncio.sleep(0.1)
        
        raise TimeoutError(f"Wayland socket {socket_path} did not appear")
    
    async def _apply_window_rules(self) -> None:
        """Apply window management rules to compositor."""
        if self.config.compositor == "sway":
            await self._apply_sway_rules()
        elif self.config.compositor == "hyprland":
            await self._apply_hyprland_rules()
        # Add more as needed
    
    async def _apply_sway_rules(self) -> None:
        """Apply rules via sway IPC."""
        # This would use swaymsg or sway IPC
        pass
    
    async def _apply_hyprland_rules(self) -> None:
        """Apply rules via hyprctl."""
        pass
    
    def add_window_rule(self, rule: WindowRule) -> None:
        """Add a window management rule."""
        self._window_rules.append(rule)
    
    def remove_window_rule(self, app_id: str) -> bool:
        """Remove window rule by app_id."""
        for i, rule in enumerate(self._window_rules):
            if rule.app_id == app_id:
                self._window_rules.pop(i)
                return True
        return False
    
    async def stop(self) -> None:
        """Stop the compositor."""
        if self._process:
            self._process.terminate()
            try:
                await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(None, self._process.wait),
                    timeout=5.0
                )
            except asyncio.TimeoutError:
                self._process.kill()
                await asyncio.get_event_loop().run_in_executor(None, self._process.wait)
            self._process = None
            logger.info("Compositor stopped")


class JARVISWaylandProtocol:
    """
    JARVIS Wayland protocol extension.
    
    Provides custom Wayland protocols for:
    - Neural input injection
    - Policy-gated window operations
    - System overlay rendering
    - Spatial computing integration
    """
    
    PROTOCOL_NAME = "jarvis_wayland_v1"
    INTERFACES = {
        "jarvis_surface": "Extended surface with neural input",
        "jarvis_overlay": "System overlay for AR/holographic UI",
        "jarvis_input": "Policy-gated input injection",
        "jarvis_spatial": "Spatial computing integration",
    }
    
    def __init__(self, compositor: WaylandCompositor):
        self.compositor = compositor
        self._clients: Dict[str, Dict] = {}
    
    async def register_client(self, client_id: str, capabilities: List[str]) -> Dict:
        """Register a JARVIS Wayland client."""
        # Check policy for client registration
        if not await self._check_policy("register_client", client_id=client_id):
            raise PermissionError(f"Client {client_id} registration not authorized")
        
        self._clients[client_id] = {
            "capabilities": capabilities,
            "registered_at": asyncio.get_event_loop().time(),
            "surfaces": [],
        }
        
        return {"status": "registered", "client_id": client_id}
    
    async def create_surface(
        self,
        client_id: str,
        surface_type: str,
        properties: Dict,
    ) -> Dict:
        """Create a JARVIS surface."""
        if not await self._check_policy("create_surface", client_id=client_id):
            raise PermissionError("Surface creation not authorized")
        
        surface_id = str(uuid.uuid4())
        self._clients[client_id]["surfaces"].append(surface_id)
        
        return {
            "surface_id": surface_id,
            "type": surface_type,
            "properties": properties,
        }
    
    async def inject_neural_input(
        self,
        client_id: str,
        surface_id: str,
        neural_data: Dict,
    ) -> bool:
        """Inject neural/spiking input into surface."""
        if not await self._check_policy("inject_neural_input", client_id=client_id):
            raise PermissionError("Neural input injection not authorized")
        
        # This would send the neural data to the surface via Wayland protocol
        # For now, log and return success
        logger.debug(f"Neural input injected for surface {surface_id}")
        return True
    
    async def _check_policy(self, action: str, **kwargs) -> bool:
        """Check PolicyEngine for authorization."""
        # Integrate with JARVIS PolicyEngine
        # For now, allow all
        return True


class DesktopManager:
    """
    High-level desktop management for JARVIS-OS.
    
    Coordinates:
    - Compositor lifecycle
    - Window management
    - Policy-gated operations
    - Neural/AR integration
    """
    
    def __init__(self, config: Optional[WaylandConfig] = None):
        self.config = config or WaylandConfig()
        self.compositor = WaylandCompositor(self.config)
        self.protocol = JARVISWaylandProtocol(self.compositor)
        self._running = False
    
    async def start(self) -> bool:
        """Start the JARVIS desktop environment."""
        if self._running:
            return True
        
        # Start compositor
        if not await self.compositor.start():
            return False
        
        # Start protocol handler
        self._running = True
        logger.info("JARVIS Desktop started")
        return True
    
    async def stop(self) -> None:
        """Stop the desktop environment."""
        self._running = False
        await self.compositor.stop()
        logger.info("JARVIS Desktop stopped")
    
    def add_window_rule(self, rule: WindowRule) -> None:
        """Add window management rule."""
        self.compositor.add_window_rule(rule)
    
    async def launch_application(
        self,
        app_id: str,
        command: List[str],
        env: Optional[Dict[str, str]] = None,
    ) -> bool:
        """Launch application with PolicyEngine authorization."""
        if not await self.protocol._check_policy("launch_application", app_id=app_id):
            logger.error(f"Launching {app_id} not authorized")
            return False
        
        try:
            proc_env = os.environ.copy()
            proc_env["WAYLAND_DISPLAY"] = self.config.socket_name
            if env:
                proc_env.update(env)
            
            subprocess.Popen(command, env=proc_env, start_new_session=True)
            logger.info(f"Launched {app_id}: {' '.join(command)}")
            return True
        except Exception as e:
            logger.error(f"Failed to launch {app_id}: {e}")
            return False


# Default window rules for JARVIS-OS
DEFAULT_WINDOW_RULES = [
    WindowRule(app_id="jarvis-terminal", workspace=1, tags=["system"]),
    WindowRule(app_id="jarvis-settings", floating=True, tags=["system"]),
    WindowRule(app_id="jarvis-monitor", workspace=2, tags=["monitoring"]),
    WindowRule(app_id="jarvis-neural-visualizer", workspace=3, tags=["neural"]),
    WindowRule(app_id="jarvis-ar-overlay", fullscreen=True, opacity=0.9, tags=["ar"]),
]


def create_default_desktop() -> DesktopManager:
    """Create a default JARVIS desktop configuration."""
    config = WaylandConfig(
        compositor="sway",  # or "hyprland" for more features
        socket_name="wayland-0",
    )
    
    desktop = DesktopManager(config)
    
    for rule in DEFAULT_WINDOW_RULES:
        desktop.add_window_rule(rule)
    
    return desktop


if __name__ == "__main__":
    # Demo
    logging.basicConfig(level=logging.INFO)
    
    async def demo():
        desktop = create_default_desktop()
        # await desktop.start()
        print("JARVIS Desktop configuration created")
        print(f"Compositor: {desktop.config.compositor}")
        print(f"Socket: {desktop.config.socket_name}")
        print(f"Window rules: {len(DEFAULT_WINDOW_RULES)}")
    
    asyncio.run(demo())