# Cognitive Loop (4.1 engine, 4.3 supervision)

`IntelligenceLoop` (`jarvis/intelligence/loop.py`) is the first-class
bounded cycle: 13 stages (`STAGES` — ingest, normalize, world, recall,
neural, reason, **predict**, plan, policy, act, **verify**, observe,
learn), explicit lifecycle
(`START → RUNNING ⇄ PAUSED → STOPPING → STOPPED`, plus `ERROR` and
`TIMEOUT`).

`CognitiveSupervisor` (`jarvis/intelligence/cognitive.py`) conducts
the engine: typed contract objects per stage, a 12-state lifecycle
(IDLE … COMPLETED/FAILED) with validated transitions, duplicate-event
suppression (bounded 1000), append-only JSONL cycle store
(`<home>/cognitive-cycles.jsonl`, secret-scrubbed), sandbox replay
(no physical actions, ever), and full observability
(`status`/`inspect`/`failures`, `intelligence cycle|inspect|replay|
events|failures` CLI).

## Timeout contract (real, monotonic)

- Deadlines use `time.monotonic()`, checked **before and after every
  stage** — not just between events. `run(events, max_cycles, timeout_s)`
  and `cycle_once(event, timeout_s)` both enforce it.
- Each stage also gets a per-stage budget (`stage_timeout_s`, defaults to
  the cycle budget). A stage that overruns records
  `failed_stage="timeout:<stage>"` with the measured vs budget detail and
  the loop enters `TIMEOUT`. `status()` reports `total_timeouts`.
- Hooks can cooperate via `context["deadline_monotonic"]`.
- Residual limitation, documented honestly: a synchronous hook cannot be
  preempted mid-call (no threads used to hide this). The guarantee is that
  **nothing runs after the boundary**: the next stage never starts, no
  action executes past timeout, and the timeout is reported
  deterministically.

## Rules

- `run(events, max_cycles, timeout_s)` always bounds execution. There is
  no infinite-loop entry point.
- `cycle_once(event)` returns a `CycleRecord` with per-stage results,
  durations, the action taken, and the policy verdict.
- Policy denial or a missing policy fails **closed**: the `act` stage is
  skipped and the executor is never called.
- `pause()`/`resume()`/`stop()` are honored between cycles.
- Every cycle is timestamped (`cycle_id`, started/ended) and retained in a
  bounded history (`max_history`, default 200).

## Predict / verify stages (4.3)

- `predict` runs after `reason`: with a `PredictionBoard` bound it
  forecasts evidence-backed trends (confidence capped at 0.5, status
  unverified — planning input, never authorization); otherwise it
  honestly reports `NO_PREDICTION`. Uncertainty is never converted
  to certainty; `NO_DECISION`/`NO_PREDICTION`/`UNKNOWN` are valid.
- `verify` runs after `act`: a pure result-vs-expectation check
  (`VERIFIED` / `PARTIALLY_VERIFIED` / `FAILED` / `UNKNOWN`).
  Approval-waiting results verify as `UNKNOWN` (not failure).
  No result is ever marked successful merely for being submitted.
- Device actions (`device.*`) flow through `DeviceCommandService`
  (grant + policy + single-use approval at delivery); the loop only
  pre-checks and records, and replays waiting exactly once per cycle.
- Stage details carry truncated summaries only (no secret values);
  approval-token patterns are redacted from persisted reasons.

## Sensory input

Producers publish `SensoryEvent`s (source, type, timestamp, confidence,
≤4 KiB payload, correlation id) to the `SensoryBus`. Adapters exist for
God's Eye observations, device-fabric events, and user text. Raw frames
and audio never cross the loop — only references plus bounded features
(see `VisualPreprocessor`: every sample contributes to exactly one
region; region-mean statistics, not pixels).
