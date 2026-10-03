# `jarvis.intelligence.loop`

## Members

### `CycleRecord` (class)

CycleRecord(cycle_id: 'str', started_at: 'float', ended_at: 'float' = 0.0, stages: 'list[StageResult]' = <factory>, action_taken: 'str' = '', policy_allowed: 'bool | None' = None, failed_stage: 'str' = '')

### `IntelligenceLoop` (class)

Bounded, observable cognitive cycle over injected subsystems.

### `LoopState` (class)

str(object='') -> str

### `StageResult` (class)

StageResult(stage: 'str', ok: 'bool' = True, detail: 'dict[str, Any]' = <factory>, error: 'str' = '', duration_ms: 'float' = 0.0)

### `scrub_token_strings` (function)

Redact in-memory/durable approval tokens from free text.
