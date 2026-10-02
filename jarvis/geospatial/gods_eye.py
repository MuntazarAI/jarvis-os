"""God's Eye View bridge for JARVIS geospatial intelligence.

This is an integration boundary, not a vendored copy of the upstream browser
application. God's Eye View remains the visualization/data-source project;
JARVIS owns the normalized observation contract and world/spatial state.

Public geospatial data is treated as observational, not authoritative.
Observations are recorded before promotion into canonical state. Provenance,
confidence, evidence, and missing coordinates remain explicit.

Upstream: https://github.com/bilawalsidhu/gods-eye-view
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..core.types import new_id, now

SOURCE_KINDS = {
    "aircraft": "aircraft",
    "ship": "vessel",
    "satellite": "satellite",
    "earthquake": "event",
    "traffic": "event",
    "camera": "camera",
    "transit": "vehicle",
    "radio": "signal",
    "place": "location",
    "infrastructure": "location",
}


@dataclass
class GodsEyeConfig:
    enabled: bool = True
    upstream_repo: str = "https://github.com/bilawalsidhu/gods-eye-view"
    workspace: str = ""
    base_url: str = "http://127.0.0.1:4173"
    observation_path: str = "gods-eye-observations.json"
    min_confidence: float = 0.35


@dataclass
class GeoObservation:
    """Normalized observation accepted from God's Eye View or another provider."""

    id: str = field(default_factory=lambda: new_id("geo"))
    kind: str = ""
    name: str = ""
    latitude: float | None = None
    longitude: float | None = None
    altitude: float | None = None
    speed: float | None = None
    heading: float | None = None
    source: str = "gods-eye-view"
    provider: str = ""
    observed_at: float = field(default_factory=now)
    confidence: float = 0.6
    evidence_refs: list[str] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    trusted: bool = True

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if self.latitude is not None and not -90 <= self.latitude <= 90:
            raise ValueError("latitude out of range")
        if self.longitude is not None and not -180 <= self.longitude <= 180:
            raise ValueError("longitude out of range")
        if self.altitude is not None and self.altitude < -1000:
            raise ValueError("altitude is implausibly low")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GeoObservation":
        return cls(**data)


class GodsEyeBridge:
    """Bridge God's Eye observations into JARVIS World + Spatial memory.

    The bridge does not scrape or silently trust external data. A frontend or
    provider hands JARVIS normalized observations, which are recorded first.
    Only explicit apply() promotes a trusted observation.
    """

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        config: GodsEyeConfig | None = None,
        world_registry: Any | None = None,
        spatial: Any | None = None,
    ) -> None:
        self.config = config or GodsEyeConfig()
        self.path = Path(path) if path else Path(self.config.observation_path)
        self.world_registry = world_registry
        self.spatial = spatial
        self.observations: dict[str, GeoObservation] = {}
        self.applied: set[str] = set()
        self.history: list[dict[str, Any]] = []
        self._load()

    @property
    def upstream_repo(self) -> str:
        return self.config.upstream_repo

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.config.enabled,
            "upstream": self.config.upstream_repo,
            "base_url": self.config.base_url,
            "workspace": self.config.workspace,
            "observations": len(self.observations),
            "applied": len(self.applied),
            "kinds": sorted({o.kind for o in self.observations.values() if o.kind}),
        }

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for key, raw in data.get("observations", {}).items():
            try:
                self.observations[key] = GeoObservation.from_dict(raw)
            except (TypeError, ValueError, KeyError):
                continue
        self.applied = set(data.get("applied", []))
        self.history = list(data.get("history", []))[-1000:]

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "observations": {k: v.to_dict() for k, v in self.observations.items()},
            "applied": sorted(self.applied),
            "history": self.history[-1000:],
        }
        fd, tmp = tempfile.mkstemp(prefix=".gods-eye-", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def ingest(self, observation: GeoObservation | dict[str, Any]) -> GeoObservation:
        """Record an observation without mutating canonical world state."""
        if not self.config.enabled:
            raise RuntimeError("God's Eye integration is disabled")
        obs = GeoObservation.from_dict(observation) if isinstance(observation, dict) else observation
        if obs.confidence < self.config.min_confidence:
            self.history.append({
                "event": "rejected",
                "id": obs.id,
                "reason": "below_min_confidence",
                "at": now(),
            })
            self._save()
            return obs
        self.observations[obs.id] = obs
        self.history.append({
            "event": "observed",
            "id": obs.id,
            "kind": obs.kind,
            "source": obs.source,
            "trusted": obs.trusted,
            "at": now(),
        })
        self._save()
        return obs

    def ingest_many(self, observations: list[GeoObservation | dict[str, Any]]) -> int:
        for observation in observations:
            self.ingest(observation)
        return len(observations)

    def get(self, observation_id: str) -> GeoObservation | None:
        return self.observations.get(observation_id)

    def apply(self, observation_id: str) -> dict[str, Any]:
        """Explicitly promote one trusted observation into JARVIS state."""
        obs = self.observations.get(observation_id)
        if obs is None:
            raise KeyError(f"unknown geospatial observation: {observation_id}")
        if not obs.trusted:
            raise PermissionError("untrusted geospatial observations cannot be applied")
        if obs.confidence < self.config.min_confidence:
            raise PermissionError("geospatial observation is below confidence threshold")

        world_id = None
        spatial_id = None
        entity_type = SOURCE_KINDS.get(obs.kind, "event")
        state = {
            key: value
            for key, value in {
                "latitude": obs.latitude,
                "longitude": obs.longitude,
                "altitude": obs.altitude,
                "speed": obs.speed,
                "heading": obs.heading,
                "observed_at": obs.observed_at,
                "provider": obs.provider,
                "source": obs.source,
            }.items()
            if value is not None
        }

        if self.world_registry is not None and obs.name:
            entity, _ = self.world_registry.upsert_entity(
                entity_type,
                obs.name,
                state=state,
                attributes=dict(obs.attributes),
                provenance={
                    "observer": "gods-eye-view",
                    "source": obs.source,
                    "provider": obs.provider,
                    "observation_id": obs.id,
                },
                confidence=obs.confidence,
            )
            world_id = entity.id

        if (
            self.spatial is not None
            and obs.name
            and obs.latitude is not None
            and obs.longitude is not None
        ):
            position = {"x": obs.longitude, "y": obs.latitude}
            if obs.altitude is not None:
                position["z"] = obs.altitude
            node = self.spatial.add_node(
                "object",
                obs.name,
                position=position,
                attributes={
                    "geospatial_kind": obs.kind,
                    "provider": obs.provider,
                    "source": obs.source,
                    **obs.attributes,
                },
                confidence=obs.confidence,
                provenance={
                    "observer": "gods-eye-view",
                    "observation_id": obs.id,
                },
                evidence_refs=list(obs.evidence_refs),
            )
            spatial_id = node.id

        self.applied.add(obs.id)
        self.history.append({
            "event": "applied",
            "id": obs.id,
            "world_id": world_id,
            "spatial_id": spatial_id,
            "at": now(),
        })
        self._save()
        return {
            "observation_id": obs.id,
            "world_id": world_id,
            "spatial_id": spatial_id,
        }

    def snapshot(self, *, kind: str | None = None) -> list[dict[str, Any]]:
        rows = self.observations.values()
        if kind:
            rows = (o for o in rows if o.kind == kind)
        return [
            o.to_dict()
            for o in sorted(rows, key=lambda x: (x.observed_at, x.name))
        ]

    def launch_url(self) -> str:
        """Return the configured local God's Eye View URL; never launches it."""
        return self.config.base_url
