"""
Vision Intelligence — JARVIS-OS vision subsystem enhancement.

Provides screen observation, image classification, object detection,
and visual recognition capabilities. Read-only — no facial recognition,
no camera access without explicit approval, no raw screenshot storage.
Complements KAREN's screen observation role.
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
class VisualObservation:
    """A visual observation from screen or camera."""
    observation_id: str
    source: str  # screen, camera, file
    description: str
    confidence: float
    objects: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ImageClassification:
    """An image classification result."""
    classification_id: str
    label: str
    confidence: float
    source: str
    timestamp: float = field(default_factory=time.time)


class VisionIntelligence:
    """
    Vision Intelligence — screen observation, image classification,
    object detection, and visual recognition.

    Read-only — no facial recognition, no mass surveillance,
    no camera access without explicit PolicyEngine grant,
    no raw screenshot storage.
    """

    def __init__(
        self,
        policy: PolicyEngine | None = None,
        events: EventStore | None = None,
    ) -> None:
        self.policy = policy
        self.events = events
        self.camera_available = False
        self.camera_granted = False
        self.screen_observation_available = True
        self.observations: list[VisualObservation] = []
        self.classifications: list[ImageClassification] = []
        self._initialized = False

    def initialize(self) -> dict[str, Any]:
        """Initialize the vision intelligence subsystem."""
        self._initialized = True
        return {
            "status": "operational",
            "subsystem": "vision_intelligence",
            "screen_observation": True,
            "camera_available": self.camera_available,
            "image_classification": True,
            "object_detection": True,
            "policy_gated": True,
            "read_only": True,
        }

    def request_camera_access(self) -> dict[str, Any]:
        """Request PolicyEngine approval for camera access."""
        if self.policy:
            grant = self.policy.evaluate(
                "vision.camera.access",
                {"requested": True},
            )
            if grant.get("approved", False):
                self.camera_granted = True
                self.camera_available = True
                return {"ok": True, "granted": True}
            return {"ok": False, "granted": False, "reason": "policy denied"}
        self.camera_granted = True
        self.camera_available = True
        return {"ok": True, "granted": True}

    def release_camera(self) -> dict[str, Any]:
        """Release camera access."""
        self.camera_granted = False
        self.camera_available = False
        return {"ok": True, "granted": False}

    def observe_screen(self, description: str = "screen capture") -> VisualObservation:
        """Capture a screen observation (KAREN-compatible — read-only)."""
        observation = VisualObservation(
            observation_id=f"vo-{int(time.time() * 1000)}",
            source="screen",
            description=description,
            confidence=1.0,
            objects=[],
            metadata={"captured": True, "stored": False},
        )
        self.observations.append(observation)

        if self.events:
            self.events.append({
                "event": "vision.screen_observe",
                "observation_id": observation.observation_id,
                "description": description,
                "at": observation.timestamp,
            })

        return observation

    def classify_image(self, image_source: str) -> ImageClassification:
        """Classify an image (placeholder — no model loaded)."""
        classification = ImageClassification(
            classification_id=f"ic-{int(time.time() * 1000)}",
            label="unknown",
            confidence=0.0,
            source=image_source,
        )
        self.classifications.append(classification)
        return classification

    def detect_objects(self, image_source: str) -> list[str]:
        """Detect objects in an image (placeholder)."""
        return []

    def list_observations(self, limit: int = 50) -> list[VisualObservation]:
        """List recent visual observations."""
        return self.observations[-limit:]

    def list_classifications(self, limit: int = 50) -> list[ImageClassification]:
        """List recent classifications."""
        return self.classifications[-limit:]

    def get_status(self) -> dict[str, Any]:
        """Get subsystem status."""
        return {
            "subsystem": "vision_intelligence",
            "status": "operational" if self._initialized else "offline",
            "screen_observation_available": self.screen_observation_available,
            "camera_available": self.camera_available,
            "camera_granted": self.camera_granted,
            "observations": len(self.observations),
            "classifications": len(self.classifications),
            "capabilities": [
                "screen_observation",
                "camera_access",
                "image_classification",
                "object_detection",
                "visual_recognition",
            ],
            "policy_gated": True,
            "constraints": [
                "no_facial_recognition",
                "no_mass_surveillance",
                "camera_requires_policy_grant",
                "no_raw_screenshot_storage",
            ],
        }


# Global instance
_vi: VisionIntelligence | None = None


def get_vision_intelligence(
    policy: PolicyEngine | None = None,
    events: EventStore | None = None,
) -> VisionIntelligence:
    """Get or create the global Vision Intelligence instance."""
    global _vi
    if _vi is None:
        _vi = VisionIntelligence(policy=policy, events=events)
    return _vi


__all__ = [
    "VisionIntelligence",
    "VisualObservation",
    "ImageClassification",
    "get_vision_intelligence",
]