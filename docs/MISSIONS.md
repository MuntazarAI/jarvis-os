# Missions 3.3 — persistent multi-dot objectives

A Mission coordinates Dots, Tasks, Agents, evidence, verification, and
recovery toward a long-running objective. It never executes tools.

## Vocabulary

- **Agent** — capability/worker role, orchestrated per activation.
- **Task** — one unit of work in TaskEngine (retries, checkpoints).
- **Goal** — desired persistent outcome (memory tier `goal`).
- **Dot** — persistent responsibility owner across sessions.
- **Mission** — persistent objective coordinating dots/tasks/agents
  with ordered objectives, verification, and recovery.
- **Objective** — one ordered step of a mission, with explicit
  dependencies (by ID, never keywords), optional Dot assignment,
  success criteria, evidence, and weight.
- **Orchestrator** — coordinates agents per activation.
- **PolicyEngine** — authorizes every action; missions add no grants.
- **World Model** — mission/objective state mirrored as entities.
- **Memory** — goals, verified outcomes, and user-approved preferences only.

## Lifecycle

```
DRAFT → READY → RUNNING → VERIFYING → COMPLETED
              ↘ WAITING / BLOCKED / NEEDS_APPROVAL / PAUSED
RUNNING → FAILED / CANCELLED / STOPPED (terminal)
```

Terminal states leave only via `recover()`, which archives the run and
starts fresh. Every transition is validated; anything else raises
`InvalidMissionTransition`.

Objectives: PENDING → READY → RUNNING → VERIFYING → COMPLETED, with
BLOCKED / FAILED / SKIPPED. An objective activates only when every
dependency (by explicit ID) is COMPLETED. Unknown dependency IDs block
instead of releasing. Failed dependencies mark dependents BLOCKED.

## Execution model

`MissionRuntime.advance()` runs exactly one bounded step, then stops:

1. Load + validate mission state.
2. Emergency-stop check (refuse when engaged).
3. Resolve ready objectives (dependency-aware).
4. Activate via assigned Dot (`DotRuntime.activate`) or directly
   through `Orchestrator.run` — both behind PolicyEngine.
5. Collect evidence (trace/task IDs, board entries, conflicts).
6. Verify against the objective's success criteria.
7. Update state, checkpoint, persist, mirror world, remember outcomes,
   notify.

Completion requires verification against explicit success criteria.
A successful final task alone never completes a mission.

## Verification

Verdicts: SUCCESS | FAILURE | UNCERTAIN | INCOMPLETE. Uncheckable →
UNCERTAIN (never assumed). Missing evidence → INCOMPLETE. Criterion
kinds: `task_completed`, `tests_passed`, `evidence_exists`,
`objectives_completed`, `files_exist`, `command_recorded`,
`security_passed`, `manual_approval` (token-checked, never reused
across actions).

## Progress

Deterministic weighted progress: completed objectives count fully,
failed/skipped count zero, in-progress counts `progress × 0.99`
(uncertainty discount). Weights normalize; missing weight = 1.0.

## Checkpoints & recovery

Every advance writes a checkpoint (mission/objective/task state,
verdict, evidence, uncertainty, budgets). Recovery preserves failure
history in `metadata.past_runs` and resets incomplete objectives to
PENDING. Interrupted work is never reported complete.

## Security boundaries

- No tool execution outside DotRuntime/Orchestrator → PolicyEngine.
- No auto-approvals, no standing grants, no permission escalation.
- Stale approval tokens authorize nothing (each action re-evaluated).
- Child objectives cannot escape the mission workspace.
- Secrets scrubbed before persistence.
- Emergency stop blocks new execution; in-flight work settles via
  existing mechanisms.

## CLI

`jarvis missions list|create|inspect|start|pause|resume|stop|cancel|`
`status|explain|objectives|verify|checkpoint|recover|advance [--json]`

## Concurrency

One runtime per mission advance call; TaskEngine owns task state;
objective activation is serialized by ready-resolution (a RUNNING
objective is never re-selected). Version counters detect stale writes.
