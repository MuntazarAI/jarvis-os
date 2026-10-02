"""Keyless live providers + registry.

Every adapter here mirrors a real, verified endpoint (shapes confirmed
against live responses during milestone 3.7 planning):

- USGS Earthquake Catalog (GeoJSON, U.S. public domain)
- NHC CurrentStorms.json (U.S. public domain / NWS terms)
- OpenSky anonymous states/all with bbox (non-commercial use)
- adsb.lol v2 point API (ODbL-derived; bounded queries only)
- SpaceDevs Launch Library 2 upcoming (anonymous, rate-limited)
- NIFC WFIGS current perimeters (ArcGIS GeoJSON, U.S. public domain)
- Open-Meteo current weather (CC BY 4.0, attribution required)
- Photon place search (OSM/ODbL data, fair use)

Parse functions are pure: raw JSON in, LiveObservation list out.
Malformed items are skipped; a malformed envelope raises LiveDataError
so sync failures stay explicit instead of silently empty.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import quote_plus

from ...core.types import now as _now
from ...security.guards import sanitize_for_context
from .models import LiveObservation, clean_text, clamp


class LiveDataError(ValueError):
    """Raised when a provider envelope is not the expected shape."""


def _require_dict(raw: Any, provider: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise LiveDataError(f"{provider}: expected JSON object envelope")
    return raw


def _ms_to_s(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    # USGS reports epoch milliseconds; accept seconds too.
    return number / 1000.0 if number > 1e12 else number


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


# -- USGS earthquakes --------------------------------------------------------

USGS_BASE = "https://earthquake.usgs.gov/fdsnws/event/1/query"


def usgs_url(params: dict[str, Any] | None = None) -> str:
    p = params or {}
    query = {
        "format": "geojson",
        "starttime": str(p.get("starttime", "2026-09-25")),
        "minmagnitude": str(p.get("minmagnitude", 4.5)),
        "limit": str(int(p.get("limit", 50))),
        "orderby": "time",
    }
    for key in ("minlatitude", "maxlatitude", "minlongitude", "maxlongitude"):
        if p.get(key) is not None:
            query[key] = str(p[key])
    return USGS_BASE + "?" + "&".join(f"{k}={quote_plus(v)}" for k, v in query.items())


def parse_usgs(raw: Any, at: float | None = None) -> list[LiveObservation]:
    data = _require_dict(raw, "usgs-earthquakes")
    features = data.get("features")
    if not isinstance(features, list):
        raise LiveDataError("usgs-earthquakes: missing features[]")
    out: list[LiveObservation] = []
    for item in features:
        try:
            if not isinstance(item, dict):
                continue
            props = item.get("properties") or {}
            geom = item.get("geometry") or {}
            coords = geom.get("coordinates") or []
            if len(coords) < 2:
                continue
            lon, lat = float(coords[0]), float(coords[1])
            mag = _num(props.get("mag"))
            name = clean_text(props.get("place") or f"M{mag} earthquake")
            if not name:
                continue
            confidence = clamp(0.55 + (0.08 if mag is not None and mag >= 5 else 0.0), 0, 1)
            out.append(LiveObservation(
                kind="earthquake", name=name, latitude=lat, longitude=lon,
                provider="usgs-earthquakes", external_id=clean_text(item.get("id"), 64),
                observed_at=_ms_to_s(props.get("time")) or (at or _now()),
                confidence=confidence,
                evidence_refs=[clean_text(props.get("url"), 300)] if props.get("url") else [],
                attributes={
                    "magnitude": mag, "depth_km": float(coords[2]) if len(coords) > 2 else None,
                    "event_page": clean_text(props.get("url"), 300),
                },
            ))
        except (ValueError, TypeError):
            continue
    return out


# -- NHC cyclones ------------------------------------------------------------

NHC_URL = "https://www.nhc.noaa.gov/CurrentStorms.json"


def nhc_url(params: dict[str, Any] | None = None) -> str:
    return NHC_URL


def parse_nhc(raw: Any, at: float | None = None) -> list[LiveObservation]:
    data = _require_dict(raw, "nhc-cyclones")
    storms = data.get("activeStorms")
    if not isinstance(storms, list):
        raise LiveDataError("nhc-cyclones: missing activeStorms[]")
    out: list[LiveObservation] = []
    for item in storms:
        try:
            if not isinstance(item, dict):
                continue
            lat = _num(item.get("latitudeNumeric"))
            lon = _num(item.get("longitudeNumeric"))
            if lat is None or lon is None:
                continue
            name = clean_text(item.get("name") or item.get("id") or "storm")
            out.append(LiveObservation(
                kind="cyclone", name=f"{name} ({clean_text(item.get('classification'), 8)})",
                latitude=lat, longitude=lon,
                provider="nhc-cyclones", external_id=clean_text(item.get("id"), 64),
                confidence=0.7,
                attributes={
                    "bin": clean_text(item.get("binNumber"), 16),
                    "classification": clean_text(item.get("classification"), 8),
                    "intensity_kt": _num(item.get("intensity")),
                    "pressure_mb": _num(item.get("pressure")),
                    "movement_deg": _num(item.get("movementDir")),
                    "movement_kt": _num(item.get("movementSpeed")),
                    "last_update": clean_text(item.get("lastUpdate"), 64),
                },
            ))
        except (ValueError, TypeError):
            continue
    return out


# -- OpenSky flights ---------------------------------------------------------

OPENSKY_BASE = "https://opensky-network.org/api/states/all"


def opensky_url(params: dict[str, Any] | None = None) -> str:
    p = params or {}
    lamin = float(p.get("lamin", 28.0))
    lomin = float(p.get("lomin", 76.5))
    lamax = float(p.get("lamax", 29.2))
    lomax = float(p.get("lomax", 77.9))
    return (f"{OPENSKY_BASE}?lamin={lamin}&lomin={lomin}"
            f"&lamax={lamax}&lomax={lomax}")


def parse_opensky(raw: Any, at: float | None = None) -> list[LiveObservation]:
    data = _require_dict(raw, "opensky-flights")
    states = data.get("states")
    if states is None:
        return []
    if not isinstance(states, list):
        raise LiveDataError("opensky-flights: states is not a list")
    out: list[LiveObservation] = []
    for row in states:
        try:
            if not isinstance(row, list) or len(row) < 7:
                continue
            icao, callsign, _origin = clean_text(row[0], 16), clean_text(row[1], 16), row[2]
            lon, lat = row[5], row[6]
            if lat is None or lon is None:
                continue
            out.append(LiveObservation(
                kind="aircraft", name=callsign or f"icao:{icao}",
                latitude=float(lat), longitude=float(lon),
                altitude=_num(row[7]), speed=_num(row[9]), heading=_num(row[10]),
                provider="opensky-flights", external_id=icao,
                confidence=0.6,
                attributes={"icao24": icao, "origin_country": clean_text(row[2], 64),
                            "on_ground": bool(row[8]) if len(row) > 8 else None},
            ))
        except (ValueError, TypeError):
            continue
    return out


# -- adsb.lol flights ----------------------------------------------------------

ADSB_BASE = "https://api.adsb.lol/v2"


def adsb_url(params: dict[str, Any] | None = None) -> str:
    p = params or {}
    return (f"{ADSB_BASE}/lat/{float(p.get('lat', 28.6))}"
            f"/lon/{float(p.get('lon', 77.2))}/dist/{float(p.get('dist_nm', 50))}")


def parse_adsb(raw: Any, at: float | None = None) -> list[LiveObservation]:
    data = _require_dict(raw, "adsb-lol-flights")
    aircraft = data.get("ac")
    if aircraft is None:
        return []
    if not isinstance(aircraft, list):
        raise LiveDataError("adsb-lol-flights: ac is not a list")
    out: list[LiveObservation] = []
    for item in aircraft:
        try:
            if not isinstance(item, dict):
                continue
            lat, lon = _num(item.get("lat")), _num(item.get("lon"))
            if lat is None or lon is None:
                continue
            alt = _num(item.get("alt_baro"))
            if alt is None:
                alt = _num(item.get("alt_geom"))
            out.append(LiveObservation(
                kind="aircraft", name=clean_text(item.get("flight") or item.get("hex") or "adsb"),
                latitude=lat, longitude=lon, altitude=alt,
                speed=_num(item.get("gs")), heading=_num(item.get("track")),
                provider="adsb-lol-flights", external_id=clean_text(item.get("hex"), 16),
                confidence=0.6,
                attributes={"squawk": clean_text(item.get("squawk"), 8),
                            "emergency": clean_text(item.get("emergency"), 16),
                            "category": clean_text(item.get("category"), 8)},
            ))
        except (ValueError, TypeError):
            continue
    return out


# -- SpaceDevs launches --------------------------------------------------------

LL2_BASE = "https://ll.thespacedevs.com/2.3.0/launches/upcoming/"


def spacedevs_url(params: dict[str, Any] | None = None) -> str:
    p = params or {}
    return f"{LL2_BASE}?limit={int(p.get('limit', 10))}"


def parse_spacedevs(raw: Any, at: float | None = None) -> list[LiveObservation]:
    data = _require_dict(raw, "spacedevs-launches")
    results = data.get("results")
    if not isinstance(results, list):
        raise LiveDataError("spacedevs-launches: missing results[]")
    out: list[LiveObservation] = []
    for item in results:
        try:
            if not isinstance(item, dict):
                continue
            pad = item.get("pad") or {}
            status = item.get("status") or {}
            out.append(LiveObservation(
                kind="launch", name=clean_text(item.get("name") or "launch"),
                provider="spacedevs-launches", external_id=clean_text(item.get("id"), 80),
                confidence=0.65,
                attributes={
                    "net": clean_text(item.get("net"), 64),
                    "window_start": clean_text(item.get("window_start"), 64),
                    "pad": clean_text(pad.get("name"), 120),
                    "pad_location": clean_text((pad.get("location") or {}).get("name"), 120),
                    "status": clean_text(status.get("name"), 64),
                    "mission": clean_text((item.get("mission") or {}).get("description"), 300),
                },
            ))
        except (ValueError, TypeError):
            continue
    return out


# -- NIFC wildfires ------------------------------------------------------------

NIFC_BASE = ("https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/"
             "WFIGS_Interagency_Perimeters_Current/FeatureServer/0/query")
NIFC_FIELDS = ",".join([
    "poly_IncidentName", "attr_UniqueFireIdentifier", "attr_IncidentSize",
    "attr_PercentContained", "attr_POOState", "attr_IncidentTypeCategory",
    "attr_FireDiscoveryDateTime", "poly_DateCurrent",
])


def nifc_url(params: dict[str, Any] | None = None) -> str:
    p = params or {}
    where = "1=1"
    if p.get("state"):
        safe_state = clean_text(p["state"], 4).upper()
        where = f"attr_POOState='{safe_state}'"
    query = {
        "where": where, "outFields": NIFC_FIELDS, "outSR": "4326",
        "f": "geojson", "resultRecordCount": str(int(p.get("limit", 200))),
    }
    return NIFC_BASE + "?" + "&".join(f"{k}={quote_plus(v)}" for k, v in query.items())


def _polygon_centroid(rings: Any) -> tuple[float | None, float | None]:
    try:
        ring = rings[0] if isinstance(rings, list) and rings else []
        xs = [float(pt[0]) for pt in ring if isinstance(pt, (list, tuple)) and len(pt) >= 2]
        ys = [float(pt[1]) for pt in ring if isinstance(pt, (list, tuple)) and len(pt) >= 2]
    except (ValueError, TypeError):
        return None, None
    if not xs:
        return None, None
    return sum(ys) / len(ys), sum(xs) / len(xs)


def parse_nifc(raw: Any, at: float | None = None) -> list[LiveObservation]:
    data = _require_dict(raw, "nifc-wildfires")
    features = data.get("features")
    if not isinstance(features, list):
        raise LiveDataError("nifc-wildfires: missing features[]")
    out: list[LiveObservation] = []
    for item in features:
        try:
            if not isinstance(item, dict):
                continue
            props = item.get("properties") or {}
            geom = item.get("geometry") or {}
            coords = geom.get("coordinates")
            lat = lon = None
            if isinstance(coords, list) and coords and isinstance(coords[0], (int, float)):
                lon, lat = float(coords[0]), float(coords[1])
            else:
                lat, lon = _polygon_centroid(coords)
            name = clean_text(props.get("poly_IncidentName") or "wildfire")
            if not name:
                continue
            out.append(LiveObservation(
                kind="wildfire", name=name, latitude=lat, longitude=lon,
                provider="nifc-wildfires",
                external_id=clean_text(props.get("attr_UniqueFireIdentifier"), 80),
                confidence=0.7,
                attributes={
                    "size_acres": _num(props.get("attr_IncidentSize")),
                    "percent_contained": _num(props.get("attr_PercentContained")),
                    "state": clean_text(props.get("attr_POOState"), 8),
                    "category": clean_text(props.get("attr_IncidentTypeCategory"), 40),
                    "discovered": clean_text(props.get("attr_FireDiscoveryDateTime"), 64),
                    "perimeter_current": clean_text(props.get("poly_DateCurrent"), 64),
                },
            ))
        except (ValueError, TypeError):
            continue
    return out


# -- Open-Meteo weather ----------------------------------------------------------

METEO_BASE = "https://api.open-meteo.com/v1/forecast"


def openmeteo_url(params: dict[str, Any] | None = None) -> str:
    p = params or {}
    return (f"{METEO_BASE}?latitude={float(p.get('lat', 28.6))}"
            f"&longitude={float(p.get('lon', 77.2))}"
            "&current=temperature_2m,relative_humidity_2m,weather_code,"
            "wind_speed_10m&timezone=auto")


def parse_openmeteo(raw: Any, at: float | None = None) -> list[LiveObservation]:
    data = _require_dict(raw, "open-meteo-weather")
    current = data.get("current")
    if not isinstance(current, dict):
        raise LiveDataError("open-meteo-weather: missing current{}")
    lat, lon = _num(data.get("latitude")), _num(data.get("longitude"))
    code = _num(current.get("weather_code"))
    return [LiveObservation(
        kind="weather",
        name=f"weather@{lat},{lon}" if lat is not None else "weather",
        latitude=lat, longitude=lon,
        speed=_num(current.get("wind_speed_10m")),
        provider="open-meteo-weather",
        external_id=f"{lat},{lon},{clean_text(current.get('time'), 32)}",
        confidence=0.6,
        attributes={
            "temperature_c": _num(current.get("temperature_2m")),
            "humidity_pct": _num(current.get("relative_humidity_2m")),
            "wmo_code": code,
            "observed_time": clean_text(current.get("time"), 64),
        },
    )]


# -- Photon places ---------------------------------------------------------------

PHOTON_BASE = "https://photon.komoot.io/api/"


def photon_url(params: dict[str, Any] | None = None) -> str:
    p = params or {}
    query = str(p.get("q", ""))
    if not query.strip():
        raise LiveDataError("photon-places: q is required")
    url = f"{PHOTON_BASE}?q={quote_plus(query)}&limit={int(p.get('limit', 5))}"
    if p.get("lat") is not None and p.get("lon") is not None:
        url += f"&lat={float(p['lat'])}&lon={float(p['lon'])}"
    return url


def parse_photon(raw: Any, at: float | None = None) -> list[LiveObservation]:
    data = _require_dict(raw, "photon-places")
    features = data.get("features")
    if not isinstance(features, list):
        raise LiveDataError("photon-places: missing features[]")
    out: list[LiveObservation] = []
    for item in features:
        try:
            if not isinstance(item, dict):
                continue
            props = item.get("properties") or {}
            coords = (item.get("geometry") or {}).get("coordinates") or []
            if len(coords) < 2:
                continue
            name = clean_text(props.get("name") or "place")
            if not name:
                continue
            out.append(LiveObservation(
                kind="place", name=name,
                latitude=float(coords[1]), longitude=float(coords[0]),
                provider="photon-places",
                external_id=f"{clean_text(props.get('osm_type'), 4)}:"
                            f"{clean_text(props.get('osm_id'), 24)}",
                confidence=0.55,
                attributes={
                    "country": clean_text(props.get("country"), 80),
                    "countrycode": clean_text(props.get("countrycode"), 8),
                    "osm_key": clean_text(props.get("osm_key"), 32),
                    "osm_value": clean_text(props.get("osm_value"), 32),
                },
            ))
        except (ValueError, TypeError):
            continue
    return out


# -- registry ----------------------------------------------------------------------

@dataclass
class ProviderSpec:
    name: str
    kinds: tuple[str, ...]
    build_url: Callable[[dict[str, Any] | None], str]
    parse: Callable[[Any, float | None], list[LiveObservation]]
    ttl_s: float = 300.0
    attribution: str = ""
    license: str = ""


def _terms(name: str) -> dict[str, str]:
    from .models import PROVIDER_TERMS
    return PROVIDER_TERMS.get(name, {})


def default_providers() -> dict[str, ProviderSpec]:
    specs = {
        "usgs-earthquakes": ProviderSpec(
            "usgs-earthquakes", ("earthquake",), usgs_url, parse_usgs, ttl_s=300.0),
        "nhc-cyclones": ProviderSpec(
            "nhc-cyclones", ("cyclone",), nhc_url, parse_nhc, ttl_s=600.0),
        "opensky-flights": ProviderSpec(
            "opensky-flights", ("aircraft",), opensky_url, parse_opensky, ttl_s=60.0),
        "adsb-lol-flights": ProviderSpec(
            "adsb-lol-flights", ("aircraft",), adsb_url, parse_adsb, ttl_s=60.0),
        "spacedevs-launches": ProviderSpec(
            "spacedevs-launches", ("launch",), spacedevs_url, parse_spacedevs,
            ttl_s=3600.0),
        "nifc-wildfires": ProviderSpec(
            "nifc-wildfires", ("wildfire",), nifc_url, parse_nifc, ttl_s=1800.0),
        "open-meteo-weather": ProviderSpec(
            "open-meteo-weather", ("weather",), openmeteo_url, parse_openmeteo,
            ttl_s=600.0),
        "photon-places": ProviderSpec(
            "photon-places", ("place",), photon_url, parse_photon, ttl_s=86400.0),
    }
    for name, spec in specs.items():
        terms = _terms(name)
        spec.attribution = terms.get("attribution", "")
        spec.license = terms.get("license", "")
    return specs


def quote_query(text: str) -> str:
    """Sanitize-then-quote free text for provider query strings."""
    return quote_plus(sanitize_for_context(text, limit=120))
