# Spatial Memory Palace

The Spatial Memory Palace is JARVIS's semantic map of where things are.

It extends the existing Memory Palace and World Model rather than replacing
either one. The map is intentionally representation-first: it can describe
spaces and relative positions now, while future vision/SLAM backends can feed
it observations.

## Model

A spatial hierarchy can look like:

    Home
    └── Office
        └── Desk
            ├── Laptop
            ├── Phone
            └── Monitor

Each node may carry:

- semantic kind (`world`, `room`, `surface`, `container`, `object`, ...)
- parent/containing location
- optional x/y/z position and dimensions
- confidence, uncertainty, provenance, and evidence
- version and movement history

Explicit relations include `near`, `adjacent_to`, `left_of`, `right_of`,
`above`, `below`, `in_front_of`, `behind`, `on`, and `attached_to`.

## Observation contract

A camera/sensor/backend should first create a `SpatialObservation`. Recording
an observation does not change the map. A trusted observation must be
explicitly applied. External/web/untrusted observations are recorded but
cannot mutate spatial state.

Unknown coordinates remain unknown; the subsystem never invents a position.

## Integration

`Jarvis` exposes `jarvis.spatial`.

When spatial nodes are created or moved:

1. the spatial map is persisted to `spatial.json`;
2. the corresponding World Model entity is mirrored when possible;
3. containment becomes a World Model `located_at` relation;
4. optional human-readable facts can be stored in the existing Memory Palace
   with tier `spatial`.

This keeps the separation clear:

**Vision observes → Spatial Memory represents → World Model reasons about the
world → Missions/Dots/Agents act through existing policy boundaries.**

## Future backends

The subsystem is ready for:

- camera object detection
- OCR and screen-space mapping
- depth cameras
- SLAM / visual odometry
- room and floor maps
- multi-device spatial synchronization
- a 3-D HUD/visualizer

Those backends should provide observations rather than bypassing the
spatial trust/provenance contract.
