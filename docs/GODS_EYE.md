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

The upstream project can be run separately using its documented Node.js setup.
The bridge records its upstream repository and local URL but does not execute
shell commands or download code automatically.

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
