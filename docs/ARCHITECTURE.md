# JARVIS-OS Architecture

## 1. System model

JARVIS-OS is a local-first cognitive system composed of bounded subsystems.

```text
Input
  │
  ▼
Perception
  │
  ▼
Understanding / Attention
  │
  ├──────────────► World Model
  │
  ├──────────────► Memory
  │
  └──────────────► Evidence
                     │
                     ▼
                 Reasoning
                     │
                     ▼
                  Planning
                     │
              ┌──────┴──────┐
              │             │
            Agents         Tasks
              │             │
              └──────┬──────┘
                     ▼
              Policy / Risk
                     │
                     ▼
                Tools / Action
                     │
                     ▼
                 Verification
                     │
                     ▼
                 Reflection
                     │
              ┌──────┴──────┐
              ▼             ▼
           Memory        World Model
```

The loop is intentionally closed: actions produce observations, observations update state, and verified outcomes can become future context.

## 2. Major boundaries

### Core

`jarvis/core/` owns shared types, configuration, and the master cognitive loop.

### Memory

`jarvis/memory/` provides persistent cognitive context. Memory 3.0 distinguishes provenance such as `told`, `inferred`, `observed`, `hypothesis`, and `system`.

### World

`jarvis/world/` represents external state. World Model 2.0 adds explicit snapshots and state changes without replacing the existing world model.

### Knowledge

The knowledge graph connects entities and relationships. Future temporal graph work should extend existing graph semantics rather than create a competing graph store.

### Cognition and inference

`jarvis/cognition/` handles understanding, attention, executive behavior, reflection, and mentalist analysis. `jarvis/inference/` handles evidence, hypotheses, reasoning, and analysis.

### Agents and tasks

Agents provide specialized execution capabilities. Tasks and workflows provide durable orchestration, retries, checkpoints, branches, and triggers.

### Policy and security

Policy/risk decisions are upstream of tool execution. Security handles secrets, consent, sessions, and emergency controls.

### Perception

Voice and vision are optional capability layers. The architecture supports hardware-aware degradation rather than assuming every sensor exists.

## 3. State and provenance

A central design rule is:

> **Never turn absence of evidence into evidence of absence.**

Unknown sensor state, missing history, unsupported predictions, and unverified hypotheses should remain explicitly uncertain.

Important information should be traceable through:

```text
Observation
   ↓
Evidence
   ↓
Claim / Hypothesis
   ↓
Plan
   ↓
Action
   ↓
Result
   ↓
Verification
   ↓
Memory / World update
```

## 4. Agent model

Agents are logical specialists, not necessarily separate processes or model instances.

The orchestration layer should enforce:

- bounded depth
- bounded agent count
- timeouts
- tool budgets
- resource budgets
- cancellation
- policy checks
- verification for important actions

This is particularly important on CPU-only development hardware.

## 5. Failure isolation

Optional subsystems should fail closed or degrade gracefully.

Examples:

- failed state capture must not break the cognitive cycle
- failed vision must not erase known state
- unavailable models should trigger routing/fallback behavior
- failed verification should produce uncertainty rather than fabricated success
- policy failures must block the protected action

## 6. Verification

Tests are part of the architecture.

A subsystem is not considered complete merely because its implementation exists. Focused tests, the full test suite, doctor checks, and benchmark results should be used to establish the current state.

## 7. Evolution rules

When extending JARVIS:

1. Inspect existing contracts first.
2. Reuse existing abstractions.
3. Prefer minimal additive changes.
4. Preserve backward compatibility.
5. Add regression tests.
6. Keep expensive work out of the normal fast path.
7. Make uncertainty explicit.
8. Keep security and policy boundaries centralized.
9. Document meaningful architectural changes.
10. Commit coherent milestones.

## 8. Current architectural priorities

The next major layers are:

1. temporal Knowledge Graph relationships
2. coordinated multi-agent intelligence
3. richer evidence-chain reconstruction
4. resource-aware scheduling and observability
5. richer human-facing interfaces

These priorities are implementation goals, not guarantees of current functionality.
