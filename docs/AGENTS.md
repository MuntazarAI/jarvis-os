# Agent Intelligence 2.0 — architecture

One controlled cognitive system with specialized reasoning capabilities.
Roles are logical, not processes: 30 role cards execute through the 8
existing executor agents plus bound subsystems. No new model instances.

## Topology

```
JARVIS (master loop)
└── Orchestrator (budgets, depth, tracing)
    ├── Executive      understanding, priority, constraints
    ├── Planner        validated DAGs, checkpoints, retries
    ├── Research       web evidence + citations
    ├── Coding         patches + tests (no commit/push w/o policy)
    ├── Computer       observe → approve → act → verify
    ├── Security       injection/SSRF/secret review (advisory + gate)
    ├── Memory         Memory 3.0 recall/write/correct (origin-preserving)
    ├── Knowledge      graph traversal, fact-vs-hypothesis
    ├── Verification   independent checks → verified/failed/uncertain
    └── Specialists    reasoning, critic, reviewer, debugger, browser,
                       devops, system, model, voice, vision, automation,
                       communication, goal, reflection, simulation,
                       forecast, knowledge-gap, perception, world,
                       privacy
```

## Lifecycle

```
goal → depth select (0-5) → blackboard open → stages run in order
  → per-role: policy gate → handler → bus COMPLETION/FAILURE
  → critic/verifier stages → conflict resolution → answer + trace
```

- Depth 0: direct communication answer, no tools.
- Depth 1: single specialist. Depth 2: + verifier.
- Depth 3: planner + specialists + verifier. Depth 4+: full team + critic.
- Depth 5: reserved for checkpointed autonomous workflows.

## Message protocol

Typed `AgentMessage`: REQUEST, OBSERVATION, HYPOTHESIS, PLAN,
ACTION_REQUEST, ACTION_RESULT, EVIDENCE, CRITIQUE, VERIFICATION,
CORRECTION, MEMORY_UPDATE, WORLD_UPDATE, ESCALATION, CANCEL, FAILURE,
COMPLETION. Every message: id, sender, recipient, task_id, parent_id,
timestamp, payload, provenance, confidence, priority, classification
(internal / observed / external / privileged). External content is
untrusted input and is injection-scanned before use.

## Blackboard

Sections: goal, constraints, state, observations, hypotheses, evidence,
plans, actions, results, conflicts, decisions, verification, answer.
Entries carry author/timestamp/provenance/confidence/lifecycle;
corrections supersede, never delete. Conflicts are detected between
opposing verdicts on one subject.

## Orchestration

- Budgets: max_depth (3), max_agents (8), max_runtime_s (120),
  max_tool_calls (15). Sub-agents spawn only via `spawn()` (depth-capped).
- Cancellation via bus CANCEL; cooperative deadline checks between steps.
- Fallbacks: research→knowledge, coder→reasoning, computer→reasoning,
  browser→research, vision→reasoning, voice→communication, debugger→coder.
- Conflict resolution preserves all claims, weighs evidence + provenance,
  never averages confidences.
- Evidence chains: `why_believe(claim)` walks blackboard + memory origins.

## Team patterns

- research: research → reasoning → critic → verifier → communication
- coding: planner → coder → verifier → reviewer → security → verifier
- debugging: debugger → reasoning → coder → verifier → reviewer
- computer: vision → planner → security → computer → verifier
- decision: research → reasoning → critic → knowledge-gap → communication
- daily: executive → memory → world → planner → coder → verifier

## Security

Every tool call passes `PolicyEngine.evaluate`; approval tokens are
surfaced, never auto-approved. Emergency stop terminates execution
(bus CANCEL + supervisor path unchanged). External content is scanned
with `security.guards.scan_injection`; SSRF-checked fetches only.
Memory writes keep Memory 3.0 origin semantics.

## Resource management

Sequential execution by default; shared model router with fallback
chain; cheap probes (fast models, cached reads) before deep reasoning.
`jarvis benchmark` tracks agent latencies; no parallel model fan-out.

## Observability

Every run emits a trace (task/agent/parent/timing/model/tools).
CLI: `jarvis agents`, `jarvis agents status`,
`jarvis agents run <goal> [--team T] [--depth N]`,
`jarvis agents explain`, `jarvis agents teams`.

## Failure recovery

Per-role try/except isolation, single fallback attempt, partial results
preserved on the blackboard, escalation records, degraded mode
(honest "subsystem not bound" failures), timeout + cancellation.

## Agent Intelligence 2.1 — verification, explainability & resilience

### Run traces

Every run builds a `RunRecord`: run_id, task_id, parent_id, goal,
depth/team, status (running/ok/failed/cancelled/timeout), timestamps,
duration, roles, tools, tool-call count, budget snapshot, evidence
references, fallbacks, policy decisions, outcome, failure reason, board
summary. Records persist as JSONL-adjacent files (`<home>/traces/`) so
`agents explain` works across sessions. Trace events carry the same
fields for machine-readable replay.

### Explainability

`agents explain <task-id>` reconstructs request → orchestration decision
→ roles → evidence → actions → verification → result from the stored
record, trace, and board. Secrets are redacted (`password/token/key`
assignments and long tokens). Unknown tasks report "no trace" —
never invented.

### Evidence pipeline

Memory promotion carries per-item `{id, origin, confidence, tier,
score}` (Memory 3.0 origins preserved). Blackboard entries link via
`supports` / `refutes` / `derives`; `evidence_for(subject)` returns
supporting and conflicting evidence side by side — conflicts stay
visible. `why_believe` semantics unchanged (chain + memory, verdict
supported/unsupported).

### Blackboard robustness

Entries carry a monotonic `version`. `correct()` accepts
`expected_version` and raises `VersionConflict` on stale or
non-active targets; `current()` follows the supersession chain
forward. Serialization round-trips version, links, and state,
including legacy entries that lack the new fields. Corrections never
delete: superseded entries remain readable.

### Orchestrator resilience

Cancellation (bus + pre-stage checks), cooperative deadlines, spawn
depth caps with budget-scaled timeouts, tool-call budgets, single
fallback per role, verifier/critic failures recorded on the board with
an honest `failed` outcome, partial results preserved. `_finish`
always reports a failure reason instead of silent `ok: false`.

### Depth heuristic

Act-based via `DialogueRouter` (greeting/identity/conversation → 0;
memory/task/tool/computer → 1; project/system → 2; research/coding →
3), plus a verification bump (→ min 2) and a multi-step bump (cap 4).
Depth 5 is explicit-only. Deterministic: same input, same depth.

### CLI

`agents status [--json]`, `agents run <goal> [--team T] [--depth N]
[--json]`, `agents explain <task-id>` (cross-session via persisted
traces), `agents list`, `agents teams`. Human-readable by default,
`--json` for machines.

## World Model 2.2 — typed registry

`jarvis/world/registry.py` adds a typed entity/relationship layer beside
World Model 2.0 snapshots (both kept; neither replaced):

- 15 entity types, 13 validated relations, stable `type:slug` IDs
- Per-entity state with versioned history, CAS updates, provenance,
  confidence, explicit uncertainty lists, evidence refs
- Observations recorded first, applied explicitly; conflicts stay visible
- Memory promotion preserves origin/confidence, refuses speculation and
  unknown origins without override, dedupes, audits every decision
- `WorldRegistry` + `WorldRepository` protocol + `JsonFileWorldStore`
- World agent answers entity/type questions with per-entity evidence on
  the blackboard; degrades cleanly when tracker or registry is absent
- CLI: `agents world entities|get|relations|history|conflicts|uncertain|changes`
- Loop persists `world.json` on close; orchestrator receives the registry
- No auto-approvals, no standing permissions, external content stays untrusted

## Proactive Intelligence 3.0 — event attention, controlled decisions

`jarvis/proactive/engine.py` proposes; it never executes. Pipeline:

world/state/events → attention → candidate → decision
(IGNORE / INFORM / ASK / PLAN) → existing orchestrator →
PolicyEngine → approval → action only when permitted

- 10 normalized event types with id/timestamp/source/entity/confidence/provenance
- Deterministic attention: urgency × confidence + novelty + goal relevance,
  every factor recorded as a reason; zero confidence = no signal
- Deduplication with cooldowns; duplicates suppressed, events preserved
- Decisions: <0.35 IGNORE, <0.6 INFORM, <0.8 ASK, above proposes a bounded
  PLAN (team/depth/goal) that is NOT executed by this layer
- Caps: untrusted content and conflicting evidence can never reach PLAN
- Emergency stop forces IGNORE; expiry forces IGNORE
- Goal blockage detection: failed-tasks + stalled goals → candidates
- Bounded JSON persistence (`proactive.json`); corrupt files load as empty
- No threads, no polling, no model calls; EventBus subscription only
- CLI: `proactive status|candidates|explain <id>|scan [--json]`
