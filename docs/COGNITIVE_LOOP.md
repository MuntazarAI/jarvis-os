# Cognitive Loop (4.1)

`IntelligenceLoop` (`jarvis/intelligence/loop.py`) is the first-class
bounded cycle: 11 stages (`STAGES`), explicit lifecycle
(`START → RUNNING ⇄ PAUSED → STOPPING → STOPPED`, plus `ERROR` on timeout).

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

## Sensory input

Producers publish `SensoryEvent`s (source, type, timestamp, confidence,
≤4 KiB payload, correlation id) to the `SensoryBus`. Adapters exist for
God's Eye observations, device-fabric events, and user text. Raw frames
and audio never cross the loop — only references plus bounded features
(see `VisualPreprocessor`: region-mean statistics, not pixels).
