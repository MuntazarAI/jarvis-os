# God's Eye View integration

JARVIS 3.5 adds a geospatial integration boundary for the open-source
[God's Eye View](https://github.com/bilawalsidhu/gods-eye-view) project.

The upstream project is a browser-based live spatial-intelligence visualization.
Its current package describes a photorealistic 3D globe with live aircraft,
ships, satellites, earthquakes, traffic, public cameras, and voice control.
JARVIS does not vendor the whole browser application into the Python core.
Instead, JARVIS provides a normalized observation bridge so a visualization or
provider layer can feed the existing World Model and Spatial Memory Palace.

## Architecture

    God's Eye View providers / UI
                 |
                 v
        GeoObservation contract
                 |
          God's Eye Bridge
          /              \
         v                v
    World Model      Spatial Memory
         |                |
         +-------+--------+
                 v
        JARVIS reasoning / missions / dots

The bridge separates observation from assertion. Ingested records are persisted
first. A record must be explicitly applied before it can change canonical JARVIS
state. Untrusted records cannot be applied. Missing coordinates remain missing.

## Supported normalized kinds

aircraft, ship, satellite, earthquake, traffic, camera, transit, radio, place,
and infrastructure.

The bridge keeps source/provider/evidence/confidence with every observation.
World entities receive geospatial state such as latitude/longitude/altitude,
while observations with coordinates can also populate the Spatial Memory Palace.

## Local setup

JARVIS 3.6 includes a lifecycle manager for the actual God's Eye View browser
application. The upstream checkout stays separate from the JARVIS Python core,
while JARVIS can explicitly install, start, stop, inspect, and open it.

    jarvis gods-eye status
    jarvis gods-eye install
    jarvis gods-eye start
    jarvis gods-eye open
    jarvis gods-eye stop

The default checkout is:

    ~/.jarvis-os/apps/gods-eye-view

The local app is bound to 127.0.0.1:4173 by default. Starting it does not
automatically open a browser; `open` is an explicit action.

The upstream package currently declares Node.js 24.14+ on the 24.x line or
26.x. JARVIS checks that requirement before installing or starting the app.


Before 3.6, the bridge only recorded the upstream repository and local URL.
3.6 adds the lifecycle manager above; installation remains an explicit user
command and the upstream application remains a separate checkout.

This separation is intentional: the upstream source code is MIT-licensed, but
its third-party live/bundled datasets and 3D assets have their own terms.
JARVIS therefore treats the upstream project as an optional integration and
keeps provider licensing/attribution with the provider layer.

See the upstream [license](https://github.com/bilawalsidhu/gods-eye-view/blob/main/LICENSE)
and [data-source notes](https://github.com/bilawalsidhu/gods-eye-view/blob/main/DATA_SOURCES.md)
before redistributing bundled data. The upstream project also notes that
public-data results can be delayed, incomplete, modeled, inferred, or wrong,
so JARVIS should preserve uncertainty rather than present them as authoritative.

## Programmatic use

    from jarvis.geospatial import GodsEyeBridge, GeoObservation

    bridge = GodsEyeBridge(
        "~/.jarvis-os/gods-eye-observations.json",
        world_registry=jarvis.world_registry,
        spatial=jarvis.spatial,
    )

    obs = bridge.ingest(GeoObservation(
        kind="aircraft",
        name="Example flight",
        latitude=28.6,
        longitude=77.2,
        provider="example-provider",
        confidence=0.8,
    ))

    bridge.apply(obs.id)

The actual God's Eye View application remains the visualization surface.
A future adapter can consume its provider payloads directly without changing
the JARVIS World/Spatial contracts.

## 3.7 Live God's Eye Intelligence

Milestone 3.7 adds an observe-only live layer (`jarvis/geospatial/live/`)
over eight verified keyless endpoints. Nothing polls in the background and
network egress requires explicit per-call consent (`allow_remote=True`,
CLI: `--allow-remote`). Local-only is the default: without consent the sync
refuses to open any socket.

    jarvis gods-eye live-status
    jarvis gods-eye live-doctor
    jarvis gods-eye live-sync --allow-remote
    jarvis gods-eye live-sync --allow-remote --provider usgs-earthquakes
    jarvis gods-eye live-query --lat 28.6 --lon 77.2 --radius-km 500
    jarvis gods-eye live-promote --key <observation-key> --approve

Keyless providers (all endpoint shapes verified against live responses):

- `usgs-earthquakes` — USGS Earthquake Catalog GeoJSON (U.S. public domain)
- `nhc-cyclones` — NHC CurrentStorms.json (U.S. public domain / NWS terms)
- `opensky-flights` — OpenSky anonymous states/all, bbox
  (non-commercial / academic / research / educational use)
- `adsb-lol-flights` — adsb.lol v2 point API (ODbL-derived; bounded queries,
  no bulk redistribution)
- `spacedevs-launches` — SpaceDevs Launch Library 2 upcoming
  (anonymous use is rate-limited; courtesy credit)
- `nifc-wildfires` — NIFC WFIGS current perimeters, ArcGIS GeoJSON
  (U.S. public domain, interagency)
- `open-meteo-weather` — Open-Meteo current weather
  (CC BY 4.0, attribution required)
- `photon-places` — Photon place search (OSM/ODbL data, fair use)

Trust model: every live record is external and untrusted (`trusted=False`).
Sync records, tracks, and raises threshold alerts (data only, never
instructions). Explicit `promote(..., approved=True)` ingests through the
3.5/3.6 `GodsEyeBridge` and applies into World/Spatial state; alert signals
fan out as untrusted `world_changed` proactive candidates; Dots receive only
injection-scanned events; missions receive DRAFT→PROPOSED proposals only;
memory receives observation-tier records with quoted external text.

State lives in `gods-eye-live.json` (atomic JSON, TTL-cached per provider,
bounded observations/tracks/alerts). Status and offline doctor checks
(including SSRF URL-safety per provider) are exposed via
`LiveIntelligenceService.status()` / `.doctor()`, the `status` command, and
the `doctor` dependency checks.
