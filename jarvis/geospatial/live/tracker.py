"""Bounded entity tracker for live observations.

Keeps the latest record per provider identity plus a short position
history. Stale tracks are pruned on read/write. Everything is plain
dicts so state round-trips through the service's atomic JSON file.
"""

from __future__ import annotations

from typing import Any

from ...core.types import now as _now
from .models import LiveObservation, LiveTrack


class EntityTracker:
    """Dedupe + track live entities by provider identity key."""

    def __init__(self, max_points: int = 50, ttl_s: float = 6 * 3600.0) -> None:
        self.max_points = max_points
        self.ttl_s = ttl_s
        self.latest: dict[str, LiveObservation] = {}
        self.tracks: dict[str, LiveTrack] = {}

    def observe(self, obs: LiveObservation, at: float | None = None) -> LiveTrack | None:
        """Record one observation; returns its track (None if unpositioned)."""
        stamp = at if at is not None else _now()
        self.latest[obs.key()] = obs
        if obs.latitude is None or obs.longitude is None:
            return self.tracks.get(obs.key())
        track = self.tracks.get(obs.key())
        if track is None:
            track = LiveTrack(key=obs.key(), kind=obs.kind, name=obs.name,
                              provider=obs.provider)
            self.tracks[obs.key()] = track
        track.kind = obs.kind or track.kind
        track.name = obs.name or track.name
        track.append(obs.latitude, obs.longitude, obs.observed_at or stamp,
                     {"alt": obs.altitude, "speed": obs.speed,
                      "heading": obs.heading},
                     limit=self.max_points)
        self.prune(at=stamp)
        return track

    def get(self, key: str) -> LiveObservation | None:
        return self.latest.get(key)

    def track(self, key: str) -> LiveTrack | None:
        return self.tracks.get(key)

    def prune(self, at: float | None = None) -> int:
        """Drop tracks/records older than TTL. Returns count removed."""
        stamp = at if at is not None else _now()
        stale = [k for k, t in self.tracks.items()
                 if stamp - t.updated_at > self.ttl_s]
        for key in stale:
            del self.tracks[key]
            self.latest.pop(key, None)
        return len(stale)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "latest": {k: v.to_dict() for k, v in self.latest.items()},
            "tracks": {k: v.to_dict() for k, v in self.tracks.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EntityTracker":
        tracker = cls()
        for key, raw in (data.get("latest") or {}).items():
            try:
                tracker.latest[key] = LiveObservation.from_dict(raw)
            except (TypeError, ValueError, KeyError):
                continue
        for key, raw in (data.get("tracks") or {}).items():
            try:
                tracker.tracks[key] = LiveTrack.from_dict(raw)
            except (TypeError, ValueError, KeyError):
                continue
        return tracker
