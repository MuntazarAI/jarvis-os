"""Object/scene perception interface (4.3).

Optional and honest: no ML model is bundled, so live detection reports
unavailability instead of fabricating labels. Persons are ALWAYS
anonymous entities — there is no identity recognition here, and the
validator refuses identity-shaped labels. Deterministic fakes keep
tests hardware-free. Real model backends (YOLO/CLIP, local-only) are
an explicit future integration point, not a hidden dependency.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .contract import MAX_OBJECTS, validate_object


class ObjectPerceptionProvider:
    """detect(image_path) -> list of validated anonymous objects."""

    name = "objects"

    def detect(self, image_path: str | Path) -> list[dict[str, Any]]:
        raise NotImplementedError

    def available(self) -> bool:
        raise NotImplementedError

    def health(self) -> dict[str, Any]:
        return {"provider": self.name, "available": self.available()}

    def capabilities(self) -> dict[str, Any]:
        return {"objects": self.available(), "identity": False,
                "note": "anonymous entities only; no face recognition"}

    def close(self) -> None:
        return None


class UnavailableObjects(ObjectPerceptionProvider):
    """No model bundled: explicit unavailability, never fake labels."""

    name = "unavailable"

    def available(self) -> bool:
        return False

    def detect(self, image_path: str | Path) -> list[dict[str, Any]]:
        return []


class FakeObjects(ObjectPerceptionProvider):
    """Deterministic scripted detections for tests."""

    name = "fake"

    def __init__(self, objects: list[dict[str, Any]] | None = None) -> None:
        self._objects = [validate_object(dict(o)) for o in (objects or [])]
        self.calls = 0

    def available(self) -> bool:
        return True

    def detect(self, image_path: str | Path) -> list[dict[str, Any]]:
        self.calls += 1
        return [dict(o) for o in self._objects[:MAX_OBJECTS]]


__all__ = ["ObjectPerceptionProvider", "UnavailableObjects",
           "FakeObjects"]
