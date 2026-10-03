# JARVIS Intelligence Expansion 5.0

Bounded, measurable, adaptive intelligence built ON the existing
nervous system — no parallel supervisor, policy, or device stack.

> JARVIS implements bounded adaptive intelligence. It is not AGI
> and makes no claim of consciousness or human-equivalent reasoning.

## Architecture

```
goal → hypotheses → context → beliefs → reason → predict
  → plan → critic → policy → act/select-tool → verify
  → evaluate → learn → consolidate → simulate/counterfactual
```

Every engine is a conductor-side library: deterministic, bounded,
provenance-carrying, fail-closed. Execution stays exclusively in
`DeviceCommandService` + `ToolRegistry.call` behind `PolicyEngine`.

## Modules (`jarvis/cognition/`)

| Module | Role |
|---|---|
| `hypotheses.py` | Ranked candidates, Uncertainty states; top is never truth |
| `context.py` | Bounded relevance assembly (world/memory/mission/event) + gaps |
| `temporal.py` | Timelines (no inferred causes), staged causal promotion, HYPOTHETICAL counterfactuals on dicts only |
| `goals.py` | GoalInterpreter, HierarchicalPlanner over MissionPlanner, PlanCritic VALID/NEEDS_REVISION/BLOCKED |
| `skills.py` | SelfCorrection (bounded), propose-only ToolSelector, chain validation, Skill contract (approval never grants) |
| `simulation.py` | Dict-only boundary (rejects live objects), ComputeBudget with partial results |
| `selfmodel.py` | Honest capability inventory, decide_mode ACT/ASK/WAIT/EXPLAIN/STOP/ESCALATE, evidence-only explanations |
| `scorecard.py` | Computed scores + benchmarks (never assigned) |

Prior 5.0-adjacent work reused unchanged: experience/belief/
learning stores, PredictionBoard, MissionPlanner, PolicyEngine,
DeviceCommandService, replay, audit.

## Safety invariants (tested)

- Learning cannot authorize, grant, or execute (AST-proven import boundary).
- Simulation/replay cannot touch transport, camera, tools, or network.
- Skills never grant permissions; approval is separate and audited.
- Confidence clamped [0,1], never NaN; uncertainty preserved.
- Unknown remains valid everywhere; low confidence never masquerades.
- Secrets/tokens never in logs, experiences, or explanations.

## Measured results (2026-10-03)

- Scorecard overall 1.0 across 15 probed categories (contract-level probes).
- Benchmarks: context 0.43ms, hypothesis 0.06ms, planning 0.06ms, simulation 0.03ms, learning 0.05ms, trend 0.07ms; supervised CLI cycle 1.6ms.
- Live emulator E2E (real APK): goal → hypothesis (honestly UNCERTAIN) → 13-stage cycle → `device.get_battery` → VERIFIED → COMPLETED.
- Deterministic scenarios A (perception→learning), B (goal→correction→success), C (contradiction→verified decision).

## Limitations

- Predictions are trend/evidence-gated, not a world model.
- Goal patterns are keyword-based, not NLU.
- Neural signal measured marginal; stays optional.
- Audio/STT, bundled ML perception, and push approvals remain future.
- Scorecard probes contracts, not open-world capability.
