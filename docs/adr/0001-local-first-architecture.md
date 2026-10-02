# ADR 0001: Local-first architecture

## Status
Accepted

## Decision
JARVIS-OS should keep core orchestration, memory, policy and device control usable locally whenever practical.

## Why
- Reduces dependence on remote services.
- Keeps sensitive state under the operator's control.
- Allows offline operation and predictable local testing.
- Makes external AI providers optional rather than foundational.

## Consequences
Local models and hardware may have lower throughput than hosted services. Integrations can still be added behind explicit boundaries.
