"""Normalizer: LiveObservation → GeoObservation.

Live records are external and untrusted. The normalizer preserves that:
every GeoObservation produced here has ``trusted=False`` and keeps the
provider, attribution-relevant metadata, and evidence refs.

Kinds pass through verbatim (earthquake, wildfire, aircraft, launch,
cyclone, weather, place). The bridge maps kinds it does not know onto
the generic ``event`` world-entity slot via ``SOURCE_KINDS.get(kind,
\"event\")`` — honest, with the live kind preserved in attributes.
Promotion to trusted/canonical state happens only through the service's
explicit approved ``promote()`` path, which then calls the existing
:class:`GodsEyeBridge.apply`.
"""

from __future__ import annotations

from ..gods_eye import GeoObservation
from .models import LIVE_KINDS, LiveObservation


def to_geo_observation(obs: LiveObservation) -> GeoObservation:
    """Convert one live record. Always untrusted; provenance preserved."""
    if obs.kind not in LIVE_KINDS:
        raise ValueError(f"unknown live kind: {obs.kind}")
    return GeoObservation(
        kind=obs.kind,
        name=obs.name,
        latitude=obs.latitude,
        longitude=obs.longitude,
        altitude=obs.altitude,
        speed=obs.speed,
        heading=obs.heading,
        source="live:" + obs.provider,
        provider=obs.provider,
        observed_at=obs.observed_at,
        confidence=obs.confidence,
        evidence_refs=list(obs.evidence_refs),
        attributes={
            "live_id": obs.id,
            "external_id": obs.external_id,
            **obs.attributes,
        },
        trusted=False,
    )
