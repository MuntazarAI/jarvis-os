"""Deterministic spatial queries over live observations.

Pure functions over in-memory records: radius search, kind filter,
nearest-N, and bounded summaries. Sorted output, no I/O, no models.
"""

from __future__ import annotations

from typing import Any, Iterable

from .models import LiveObservation, haversine_km


def within_radius(observations: Iterable[LiveObservation],
                  latitude: float, longitude: float,
                  radius_km: float) -> list[tuple[LiveObservation, float]]:
    """Observations with coordinates inside radius_km, nearest first."""
    out: list[tuple[LiveObservation, float]] = []
    for obs in observations:
        if obs.latitude is None or obs.longitude is None:
            continue
        dist = haversine_km(latitude, longitude, obs.latitude, obs.longitude)
        if dist <= radius_km:
            out.append((obs, dist))
    return sorted(out, key=lambda item: (item[1], item[0].name.lower()))


def by_kind(observations: Iterable[LiveObservation],
            kind: str) -> list[LiveObservation]:
    return sorted((o for o in observations if o.kind == kind),
                  key=lambda o: (o.observed_at, o.name))


def nearest(observations: Iterable[LiveObservation],
            latitude: float, longitude: float,
            limit: int = 5) -> list[tuple[LiveObservation, float]]:
    """Nearest-N positioned observations to a point."""
    ranked = within_radius(observations, latitude, longitude, float("inf"))
    return ranked[: max(0, limit)]


def summarize(observations: Iterable[LiveObservation]) -> dict[str, Any]:
    """Bounded counts per kind/provider for status + reasoning context."""
    rows = list(observations)
    kinds: dict[str, int] = {}
    providers: dict[str, int] = {}
    for obs in rows:
        kinds[obs.kind] = kinds.get(obs.kind, 0) + 1
        providers[obs.provider] = providers.get(obs.provider, 0) + 1
    return {"total": len(rows), "kinds": kinds, "providers": providers}
