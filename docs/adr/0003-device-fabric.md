# ADR 0003: Typed device fabric

## Status
Accepted

## Decision
Devices expose typed capabilities instead of arbitrary shell, filesystem or code-execution access.

## Why
A common capability model makes laptops, Android nodes and future hardware easier to reason about and audit.

## Consequences
New hardware integrations may require adapters, but the security model remains consistent.
