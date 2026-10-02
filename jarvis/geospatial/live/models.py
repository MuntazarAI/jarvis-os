"""Live God's Eye Intelligence — canonical models.

These models sit between raw provider payloads and the existing
:class:`GeoObservation` contract. They carry uncertainty, provenance,
licensing, and identity explicitly. Raw provider text is treated as
untrusted data, never instructions.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from ...core.types import new_id, now

# Provider-stable observation kinds for the live layer.
LIVE_KINDS = (
    "earthquake",
    "wildfire",
    "aircraft",
    "launch",
    "cyclone",
    "weather",
    "place",
)

# Attribution / license notes kept with the provider layer (not invented;
# they mirror upstream DATA_SOURCES.md and each provider's published terms).
PROVIDER_TERMS: dict[str, dict[str, str]] = {
    "usgs-earthquakes": {
        "license": "U.S. public domain",
        "attribution": "USGS Earthquake Hazards Program",
    },
    "nhc-cyclones": {
        "license": "U.S. public domain (NWS terms)",
        "attribution": "NOAA National Hurricane Center",
    },
    "opensky-flights": {
        "license": "non-commercial / academic / research / educational use",
        "attribution": "OpenSky Network",
    },
    "adsb-lol-flights": {
        "license": "ODbL-derived, no bulk redistribution",
        "attribution": "adsb.lol",
    },
    "spacedevs-launches": {
        "license": "anonymous use rate-limited; courtesy credit",
        "attribution": "The Space Devs",
    },
    "nifc-wildfires": {
        "license": "U.S. public domain (interagency)",
        "attribution": "NIFC / WFIGS",
    },
    "open-meteo-weather": {
        "license": "CC BY 4.0 (attribution required)",
        "attribution": "Open-Meteo",
    },
    "photon-places": {
        "license": "ODbL data (OSM), fair use",
        "attribution": "Photon / OpenStreetMap contributors",
    },
}

_WS_RE = re.compile(r"\s+")


def clean_text(value: Any, limit: int = 160) -> str:
    """Collapse whitespace and clip provider text. Never returns markup."""
    text = _WS_RE.sub(" ", str(value or "")).strip()
    text = text.replace("<", "").replace(">", "")
    return text[:limit]


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km. Pure and deterministic."""
    radius = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.asin(min(1.0, math.sqrt(a)))


@dataclass
class LiveConfig:
    """Operator-controlled live layer settings."""

    enabled: bool = True
    # Local-only default: live sync refuses network egress unless the caller
    # explicitly passes allow_remote=True (CLI: --allow-remote).
    allow_remote: bool = False
    timeout_s: float = 20.0
    max_bytes: int = 2 * 1024 * 1024
    max_observations: int = 2000
    max_track_points: int = 50
    track_ttl_s: float = 6 * 3600.0
    default_ttl_s: float = 300.0
    min_confidence: float = 0.35
    state_path: str = "gods-eye-live.json"
    providers: dict[str, bool] = field(default_factory=lambda: {
        "usgs-earthquakes": True,
        "nhc-cyclones": True,
        "opensky-flights": True,
        "adsb-lol-flights": True,
        "spacedevs-launches": True,
        "nifc-wildfires": True,
        "open-meteo-weather": True,
        "photon-places": True,
    })


@dataclass
class LiveObservation:
    """One normalized live record. Identity is provider + external id."""

    id: str = field(default_factory=lambda: new_id("live"))
    kind: str = ""
    name: str = ""
    latitude: float | None = None
    longitude: float | None = None
    altitude: float | None = None
    speed: float | None = None
    heading: float | None = None
    provider: str = ""
    external_id: str = ""
    observed_at: float = field(default_factory=now)
    received_at: float = field(default_factory=now)
    confidence: float = 0.6
    evidence_refs: list[str] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    # Live data is external: untrusted until an explicit approved promotion.
    trusted: bool = False

    def __post_init__(self) -> None:
        if self.kind not in LIVE_KINDS:
            raise ValueError(f"unknown live kind: {self.kind}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if self.latitude is not None and not -90 <= self.latitude <= 90:
            raise ValueError("latitude out of range")
        if self.longitude is not None and not -180 <= self.longitude <= 180:
            raise ValueError("longitude out of range")

    def key(self) -> str:
        """Stable dedupe key: provider + external id, or id fallback."""
        if self.provider and self.external_id:
            return f"{self.provider}:{self.external_id}"
        return self.id

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LiveObservation":
        return cls(**data)


@dataclass
class LiveTrack:
    """Bounded position history for one tracked entity (e.g. an aircraft)."""

    key: str
    kind: str = ""
    name: str = ""
    provider: str = ""
    points: list[dict[str, Any]] = field(default_factory=list)
    updated_at: float = field(default_factory=now)

    def append(self, latitude: float, longitude: float, at: float,
               extra: dict[str, Any] | None = None,
               limit: int = 50) -> None:
        point = {"lat": latitude, "lon": longitude, "at": at}
        if extra:
            point.update(extra)
        self.points.append(point)
        self.points = self.points[-limit:]
        self.updated_at = at

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LiveTrack":
        return cls(**data)


@dataclass
class LiveAlert:
    """A thresholded live signal. Data only — never an instruction."""

    id: str = field(default_factory=lambda: new_id("alert"))
    kind: str = ""
    title: str = ""
    detail: str = ""
    severity: str = "info"  # info | elevated | high | critical
    observation_key: str = ""
    provider: str = ""
    at: float = field(default_factory=now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LiveAlert":
        return cls(**data)
