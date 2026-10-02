# JARVIS Intelligence Architecture (4.1)

One coherent cognitive system built from the existing subsystems — not a
replacement, an orchestration layer.

## The cycle

```
Perception → SensoryBus → WorkingMemory → WorldModel → NeuralCore
  → Reasoning → Planning → Policy → Action → Observation → Learning
  → repeat (bounded)
```

Every stage is implemented in `jarvis/intelligence/`:

| Stage | Module | Real subsystem behind it |
|---|---|---|
| ingest/normalize | `sensory.py` | `SensoryBus`, typed `SensoryEvent`s |
| world | `wiring.py` | `WorldRegistry`, `SpatialMemoryPalace` |
| recall | `wiring.py` | `MemoryPalace.search` |
| neural | `wiring.py` | `SparseLIFNetwork` + codec |
| reason | `wiring.py` | `MetaReasoner` (or passthrough) |
| plan | `planning/planner.py` | `MissionPlanner` rule registry |
| policy | `wiring.py` | `PolicyEngine.evaluate` (fail closed) |
| act | `wiring.py` | `ToolRegistry.call` (post-approval only) |
| observe/learn | `wiring.py` | `MemoryPalace.store_observation` |

## Hybrid design (deliberate)

- **Neural**: temporal patterns, association, novelty, motor-intent signals.
- **Symbolic**: world model, explicit memory, goals, missions, tools, policy.
- **Reasoning**: deductive/inductive/abductive + red-team + meta-audit.

No layer bypasses another. Neural output is advisory typed signals;
`PolicyEngine` is the sole authority for action.

## Failure model

Each stage is failure-isolated: an exception marks `failed_stage` and ends
the cycle with prior stages' trace intact. One bad subsystem never corrupts
the loop. Policy denial is a normal outcome, not an error.

## entry points

- `jarvis intelligence status` / `jarvis intelligence cycle --text ...`
- `IntelligenceLoop.run(events, max_cycles, timeout_s)` for embedding.
