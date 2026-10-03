# JARVIS Intelligence 5.0

JARVIS 5.0 adds an adaptive-intelligence foundation around the existing
CognitiveSupervisor rather than replacing it.

## New capabilities

- Evidence and provenance contracts
- Bounded beliefs with contradiction tracking
- Explicit uncertainty states
- Deterministic hypothesis ranking
- Active information-gathering selection
- Goal contracts
- Static plan criticism
- Prediction/outcome learning primitives
- Bounded experience persistence
- Secret-key scrubbing at the experience boundary
- Capability fingerprints
- A stable adaptive-intelligence facade

## Safety boundary

This layer does **not**:

- execute tools
- execute device commands
- grant permissions
- modify PolicyEngine state
- modify trust
- expose secrets
- turn predictions into facts
- turn beliefs into authorization
- execute simulations in the real world

Existing PolicyEngine and DeviceCommandService remain the authority for
external effects.

## Intelligence model

The intended direction is:

```
PERCEIVE
  ↓
CONTEXT
  ↓
EVIDENCE
  ↓
BELIEFS
  ↓
HYPOTHESES
  ↓
INFORMATION GATHERING
  ↓
REASON
  ↓
PREDICT
  ↓
PLAN
  ↓
POLICY
  ↓
ACT
  ↓
VERIFY
  ↓
OUTCOME
  ↓
EXPERIENCE
  ↓
LEARN
  ↺
```

5.0 is an architectural foundation. It does not claim AGI, consciousness, or
human-equivalent reasoning. Capability is measured by deterministic tests and
benchmarks rather than by a manually assigned intelligence score.

## Current limitations

The repository still needs deeper integration for:

- causal inference
- counterfactual simulation
- generalized computer use
- audio/STT
- long-running autonomous missions
- learned skills
- production TLS/secret storage
- richer multimodal model reasoning
- stronger neural benchmarking

Those remain explicit future work rather than hidden claims.
