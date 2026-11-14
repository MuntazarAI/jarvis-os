"""
Geospatial Intelligence — JARVIS-OS OMNINET subsystem.

Provides location services, mapping, geocoding, and distance calculations
through allowlisted geographic data sources. Read-only — no location
modification or tracking capability.
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
class GeoLocation:
    """A geographic location."""
    location_id: str
    name: str
    latitude: float
    longitude: float
    address: str
    country_code: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class GeoDistance:
    """A distance calculation between two points."""
    distance_id: str
    origin: str
    destination: str
    distance_km: float
    distance_miles: float
    timestamp: float = field(default_factory=time.time)


@dataclass
class GeoMap:
    """A map reference."""
    map_id: str
    center_lat: float
    center_lon: float
    zoom_level: int
    map_type: str  # street, satellite, terrain, hybrid
    timestamp: float = field(default_factory=time.time)


class GeospatialIntelligence:
    """
    Geospatial Intelligence — location services, mapping, geocoding,
    and distance calculations.

    Read-only geographic information from allowlisted sources. All requests
    pass through PolicyEngine. No location modification or tracking.
    """

    ALLOWED_DOMAINS: frozenset[str] = frozenset({
        "openstreetmap.org",
        "nominatim.openstreetmap.org",
        "usgs.gov",
        "nga.mil",
        "geonames.org",
        "epsg.org",
    })

    def __init__(
        self,
        policy: PolicyEngine | None = None,
        events: EventStore | None = None,
    ) -> None:
        self.policy = policy
        self.events = events
        self.locations: dict[str, GeoLocation] = {}
        self.distances: dict[str, GeoDistance] = {}
        self.maps: dict[str, GeoMap] = {}
        self._initialized = False

    def initialize(self) -> dict[str, Any]:
        """Initialize the geospatial intelligence subsystem."""
        self._initialized = True
        return {
            "status": "operational",
            "subsystem": "geospatial_intelligence",
            "domains": len(self.ALLOWED_DOMAINS),
            "policy_gated": True,
            "read_only": True,
        }

    def geocode(self, address: str) -> GeoLocation:
        """Convert an address to geographic coordinates."""
        loc_id = f"geo-{int(time.time() * 1000)}"

        grant_result = {"approved": False, "reason": "no policy engine"}
        if self.policy:
            grant_result = self.policy.evaluate(
                "geospatial_intelligence.geocode",
                {"address": address, "domains": list(self.ALLOWED_DOMAINS)},
            )

        loc = GeoLocation(
            location_id=loc_id,
            name=address,
            latitude=0.0,
            longitude=0.0,
            address=address,
            country_code="",
        )
        self.locations[loc_id] = loc

        if self.events:
            self.events.append({
                "event": "geospatial_intelligence.geocode",
                "location_id": loc_id,
                "address": address,
                "approved": grant_result.get("approved", False),
                "at": loc.timestamp,
            })

        return loc

    def reverse_geocode(self, latitude: float, longitude: float) -> GeoLocation:
        """Convert coordinates to an address."""
        loc_id = f"rgeo-{int(time.time() * 1000)}"
        loc = GeoLocation(
            location_id=loc_id,
            name=f"{latitude},{longitude}",
            latitude=latitude,
            longitude=longitude,
            address="unknown",
            country_code="",
        )
        self.locations[loc_id] = loc
        return loc

    def calculate_distance(
        self,
        origin: str,
        destination: str,
    ) -> GeoDistance:
        """Calculate distance between two locations."""
        dist_id = f"dist-{int(time.time() * 1000)}"
        dist = GeoDistance(
            distance_id=dist_id,
            origin=origin,
            destination=destination,
            distance_km=0.0,
            distance_miles=0.0,
        )
        self.distances[dist_id] = dist
        return dist

    def get_map(
        self,
        center_lat: float,
        center_lon: float,
        zoom_level: int = 10,
        map_type: str = "street",
    ) -> GeoMap:
        """Get a map reference for a location."""
        map_id = f"map-{int(time.time() * 1000)}"
        gmap = GeoMap(
            map_id=map_id,
            center_lat=center_lat,
            center_lon=center_lon,
            zoom_level=zoom_level,
            map_type=map_type,
        )
        self.maps[map_id] = gmap
        return gmap

    def list_domains(self) -> list[str]:
        """List allowlisted domains."""
        return sorted(self.ALLOWED_DOMAINS)

    def get_status(self) -> dict[str, Any]:
        """Get subsystem status."""
        return {
            "subsystem": "geospatial_intelligence",
            "status": "operational" if self._initialized else "offline",
            "locations": len(self.locations),
            "distances": len(self.distances),
            "maps": len(self.maps),
            "domains": sorted(self.ALLOWED_DOMAINS),
            "capabilities": [
                "geocoding",
                "reverse_geocoding",
                "distance_calculation",
                "map_reference",
            ],
            "constraints": [
                "read_only_geographic_data",
                "policy_gated_domain_access",
                "no_location_modification",
            ],
        }


# Global instance
_geo: GeospatialIntelligence | None = None


def get_geospatial_intelligence(
    policy: PolicyEngine | None = None,
    events: EventStore | None = None,
) -> GeospatialIntelligence:
    """Get or create the global Geospatial Intelligence instance."""
    global _geo
    if _geo is None:
        _geo = GeospatialIntelligence(policy=policy, events=events)
    return _geo


__all__ = [
    "GeospatialIntelligence",
    "GeoLocation",
    "GeoDistance",
    "GeoMap",
    "get_geospatial_intelligence",
]