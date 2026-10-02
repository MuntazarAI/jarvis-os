# ADR 0002: Policy Engine is the security boundary

## Status
Accepted

## Decision
Model output, neural output and agent plans are proposals. External actions must pass through typed routing and the PolicyEngine.

## Why
Generative components are not trustworthy authorization mechanisms.

## Consequences
Every new tool or device capability needs a bounded command shape and an authorization path.
