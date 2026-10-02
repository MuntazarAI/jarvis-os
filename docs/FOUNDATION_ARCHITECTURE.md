# Foundation Architecture (Hardening Reference)

This document describes how the JARVIS subsystems fit together and, more
importantly, where the **trust boundaries** are. It is the reference for
anyone changing the loop, the policy gate, or the neural path.

## 1. System shape

```text
sources (user / device fabric / God's Eye / sensors / timers)
   │
   ▼
SensoryBus                jarvis/intelligence/sensory.py
   │  typed events, bounded payloads (blobs stay at the source)
   ▼
IntelligenceLoop          jarvis/intelligence/loop.py
   │  ingest → normalize → world → recall → neural → reason → plan
   │  → policy → act → observe → learn
   ├── WorldRegistry        jarvis/world/registry.py        (canonical facts)
   ├── SpatialMemoryPalace  jarvis/spatial/palace.py        (places + relations)
   ├── MemoryPalace         jarvis/memory/palace.py         (tiered recall)
   ├── SparseLIFNetwork     jarvis/neural/scale.py          (temporal layer)
   ├── MetaReasoner         jarvis/inference/reasoning.py   (symbolic layer)
   ├── MissionPlanner       jarvis/planning/planner.py      (proposes actions)
   ├── PolicyEngine         jarvis/policy/policy.py         (AUTHORITATIVE)
   └── ToolRegistry         jarvis/tools/tools.py           (typed effects)
```

Two loops coexist deliberately:

- `Jarvis.cycle_once(text)` (`jarvis/core/loop.py`) — the conversational
  entry point. Unchanged by the intelligence work.
- `IntelligenceLoop.cycle_once(event)` — the typed cognitive cycle used by
  CLI/daemon callers, sensors, and replay.

They share subsystems but not control flow. The intelligence loop never
calls `Jarvis.cycle_once`; the Jarvis loop never calls the intelligence
loop.

## 2. Trust boundaries (the important part)

| Boundary | Rule | Enforced in |
| --- | --- | --- |
| Perception → cognition | External payloads are untrusted data, never instructions | `scan_injection`, `sanitize_for_context` |
| Neural → action | Neural output is a typed `MotorIntent` in a 9-action allowlist; it can never name a tool | `jarvis/neural/interface.py` |
| Plan → action | Every proposed action passes `PolicyEngine.evaluate` | `make_policy_hook` |
| Unknown action | Denied: no tool registry ⇒ permissions unknown ⇒ fail closed | `make_policy_hook` |
| Approval | `requires_approval` returns a token and does **not** execute | `make_policy_hook` |
| Replay | Side-effect hooks are stubbed; executor hard-disabled | `IntelligenceLoop.sandbox` |
| Secrets | Snapshot/replay output is scrubbed | `intelligence/snapshot.scrub` |
| Code execution | `python_run` is AST-whitelisted (no imports/attrs/dunders/defs/loops) | `tools._python_ast_allowed` |

## 3. Why the policy hook resolves tool specs

An earlier 4.1 revision built `ActionPlan(action=..., args=...)` with no
`required_permissions`. PolicyEngine then evaluated an action with an
empty permission list, which *always* passed `permitted()` — so a plan
naming any tool could be authorized for an actor holding no grants. The
hardening pass fixed this: `make_policy_hook` requires a `ToolRegistry`,
looks the action up, and copies `required_permissions` and `risk` from the
tool spec — the same pattern as `Jarvis._execute_step`. Unknown tools are
denied outright.

Regression coverage: `tests/test_hardening.py::test_policy_hook_*`.

## 4. Failure model

- **Stage isolation.** Each loop stage is wrapped; one failure records
  `failed_stage` and stops the cycle. Later stages never run.
- **Timeouts.** Deadlines use `time.monotonic()` and are checked before
  and after every stage (`LoopState.TIMEOUT`). Hooks are synchronous, so a
  hook that blocks cannot be preempted — documented limit, not hidden.
- **Subsystem absence.** Unbound hooks return `{"skipped": True}`; the
  cycle still completes as observe-only.
- **Corrupt state.** `JsonFileWorldStore.load()` recovers to `{}` and sets
  `last_load_error`; the file is left on disk for forensics. `PairingManager`
  and the neural snapshot loader behave the same way.

## 5. What this architecture does not do

- It does not run itself. There is no daemon; cycles happen when a caller
  (CLI, service, or a future scheduler) invokes one.
- It does not execute unapproved work. Approval tokens are returned to the
  caller, never auto-consumed.
- It does not treat the neural layer as an authority. It contributes
  temporal state and bounded signals; the symbolic layer and policy decide.
- It does not model a measured connectome. `FLY_166K_SCHEMA` is schematic
  synthetic topology (see `docs/FLY_BRAIN.md`).