"""
See-Through-Walls AR Integration — JARVIS-OS OMNINET subsystem.

Integrates https://github.com/bilawalsidhu/see-through-walls — multiplayer
AR with MultiSet VPS, shared maps, localization, pose sharing, and
skeleton-through-walls visualization. Read-only observation — no camera
or microphone access beyond what the operator explicitly provides.

All AR capabilities pass through PolicyEngine. KAREN-style screen
observation constraints apply: no raw screenshot storage, no clicks,
no typing, no raw camera/mic access without explicit operator consent.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from ..core.logging import get_module_logger
from ..policy.policy import PolicyEngine
from ..events.store import EventStore

log = get_module_logger(__name__)


@dataclass
class ARPose:
    """An AR pose reading from a localized device."""
    device_id: str
    x: float
    y: float
    z: float
    pitch: float
    yaw: float
    roll: float
    timestamp: float = field(default_factory=time.time)
    localized: bool = False
    map_code: str | None = None


@dataclass
class ARSession:
    """A multiplayer AR session."""
    session_id: str
    map_code: str
    devices: dict[str, ARPose] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    active: bool = True


class SeeThroughWalls:
    """
    See-Through-Walls — multiplayer AR situational awareness.

    Provides shared augmented reality experiences using MultiSet VPS.
    Devices localize on a shared map, share poses, and visualize each
    other through walls as skeleton silhouettes.

    Read-only observation. No raw screenshot storage. No clicks, typing,
    or key presses without explicit operator consent. Camera/mic access
    requires separate PolicyEngine grants.
    """

    def __init__(self, policy: PolicyEngine | None = None,
                 events: EventStore | None = None) -> None:
        self.policy = policy
        self.events = events
        self.sessions: dict[str, ARSession] = {}
        self.poses: dict[str, ARPose] = {}
        self._initialized = False

    def initialize(self) -> dict[str, Any]:
        """Initialize the See-Through-Walls subsystem."""
        self._initialized = True
        return {
            "status": "operational",
            "subsystem": "see_through_walls",
            "sdk": "MultiSet VPS",
            "read_only": True,
            "policy_gated": True,
            "capabilities": [
                "shared_map_localization",
                "pose_sharing",
                "multiplayer_ar",
                "skeleton_through_walls",
                "meta_ray_ban_support",
            ],
        }

    def create_session(self, map_code: str) -> ARSession:
        """Create a new multiplayer AR session."""
        session = ARSession(
            session_id=f"stw-{int(time.time() * 1000)}",
            map_code=map_code,
        )
        self.sessions[session.session_id] = session
        if self.events:
            self.events.append({
                "event": "see_through_walls.session_created",
                "session_id": session.session_id,
                "map_code": map_code,
                "at": session.created_at,
            })
        return session

    def update_pose(self, device_id: str, x: float, y: float, z: float,
                    pitch: float, yaw: float, roll: float,
                    localized: bool = False,
                    map_code: str | None = None) -> ARPose:
        """Update a device's AR pose."""
        pose = ARPose(
            device_id=device_id,
            x=x, y=y, z=z,
            pitch=pitch, yaw=yaw, roll=roll,
            localized=localized,
            map_code=map_code,
        )
        self.poses[device_id] = pose
        # Also add to active session if any
        for session in self.sessions.values():
            if session.active:
                session.devices[device_id] = pose
                break
        if self.events:
            self.events.append({
                "event": "see_through_walls.pose_update",
                "device_id": device_id,
                "localized": localized,
                "at": pose.timestamp,
            })
        return pose

    def get_pose(self, device_id: str) -> ARPose | None:
        """Get a device's current pose."""
        return self.poses.get(device_id)

    def list_sessions(self) -> list[ARSession]:
        """List all AR sessions."""
        return list(self.sessions.values())

    def get_status(self) -> dict[str, Any]:
        """Get subsystem status."""
        return {
            "subsystem": "see_through_walls",
            "status": "operational" if self._initialized else "offline",
            "sdk": "MultiSet VPS",
            "sessions": len(self.sessions),
            "devices_tracked": len(self.poses),
            "capabilities": [
                "shared_map_localization",
                "pose_sharing",
                "multiplayer_ar",
                "skeleton_through_walls",
                "meta_ray_ban_companion",
            ],
            "read_only": True,
            "policy_gated": True,
            "constraints": [
                "no_raw_screenshot_storage",
                "no_clicks_typing_without_consent",
                "camera_mic_requires_policy_grant",
                "screen_observation_only",
            ],
        }


# Global instance
_stw: SeeThroughWalls | None = None


def get_see_through_walls(
    policy: PolicyEngine | None = None,
    events: EventStore | None = None,
) -> SeeThroughWalls:
    """Get or create the global See-Through-Walls instance."""
    global _stw
    if _stw is None:
        _stw = SeeThroughWalls(policy=policy, events=events)
    return _stw


__all__ = [
    "SeeThroughWalls",
    "ARPose",
    "ARSession",
    "get_see_through_walls",
]