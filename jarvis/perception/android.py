"""Android perception seam (4.3).

Typed contract for future Android-side perception that flows through
the SAME observation pipeline — no second architecture, no screen
scraping, no camera streaming. An Android node reports perception
capabilities; its typed events convert to Observations here and enter
the normal validate -> bus -> world -> memory path.

Everything stays behind the existing gates: PolicyEngine,
DeviceCommandService, pairing/trust, and the 3.10 transport are
untouched. This module only names events and converts them.
"""

from __future__ import annotations

from typing import Any

from .contract import (
    Modality,
    Observation,
    PerceptionError,
    PrivacyClass,
    validate_confidence,
)

#: Device capability names a node may declare for perception.
ANDROID_PERCEPTION_CAPABILITIES = (
    "device.camera.snapshot",
    "device.screen.describe",
)

#: Typed Android perception event names -> observation modality.
ANDROID_PERCEPTION_EVENTS = {
    "camera.snapshot": Modality.CAMERA,
    "screen.describe": Modality.SCREEN,
}


def android_capability_for(modality: str) -> str:
    """Map an observation modality to its Android capability, if any."""
    mapping = {"camera": "device.camera.snapshot",
               "screen": "device.screen.describe"}
    capability = mapping.get(str(modality))
    if capability is None:
        raise PerceptionError(
            f"no Android perception capability for {modality!r}")
    return capability


def observation_from_device_event(device_id: str, event_name: str,
                                  data: dict[str, Any] | None = None,
                                  confidence: float = 0.5) -> Observation:
    """Convert a typed Android perception event into an Observation.

    Only closed event names in ANDROID_PERCEPTION_EVENTS are accepted;
    arbitrary screen scraping or camera streaming has no mapping and
    is refused. Payload is bounded scalars only — the phone never
    sends raw frames through this seam.
    """
    if event_name not in ANDROID_PERCEPTION_EVENTS:
        raise PerceptionError(
            f"unknown Android perception event: {event_name!r}")
    if not device_id:
        raise PerceptionError("device_id is required")
    data = dict(data or {})
    summary = ""
    objects: list[dict[str, Any]] = []
    dropped = 0
    if isinstance(data.get("objects"), list):
        from .contract import validate_object
        for item in data["objects"][:20]:
            if isinstance(item, dict):
                try:
                    objects.append(validate_object(item))
                except PerceptionError:
                    # Refused items never enter the observation; the
                    # count stays visible so probing is not silent.
                    dropped += 1
                    continue
    summary = str(data.get("summary", data.get("text", "")))[:500]
    modality = ANDROID_PERCEPTION_EVENTS[event_name]
    payload: dict[str, Any] = {"status": "ok", "summary": summary}
    if objects:
        payload["objects"] = objects
    if dropped:
        payload["dropped_items"] = dropped
    for key in ("scene", "visible_text", "active_app"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            payload[key] = value.strip()[:500]
    return Observation(
        source="android-perception", source_device=str(device_id)[:120],
        modality=modality, payload=payload,
        confidence=validate_confidence(confidence),
        provenance={"provider": "android-perception",
                    "event": event_name},
        privacy_class=PrivacyClass.LOCAL)


__all__ = [
    "ANDROID_PERCEPTION_CAPABILITIES",
    "ANDROID_PERCEPTION_EVENTS",
    "android_capability_for",
    "observation_from_device_event",
]
