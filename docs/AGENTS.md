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
