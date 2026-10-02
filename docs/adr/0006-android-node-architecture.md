# ADR 0006: Android as a typed JARVIS node

## Status
Accepted

## Decision
Android participates in the device fabric through explicit pairing, typed capabilities and policy-gated commands.

## Why
The phone is a useful sensor/actuator node, but unrestricted remote control would violate the platform's least-privilege design.

## Consequences
Network transport, identity and permission handling must remain explicit as the Android implementation evolves.
