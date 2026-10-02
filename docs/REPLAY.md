# Cycle Replay (4.1)

`jarvis/intelligence/snapshot.py`: capture, replay, compare.

- `capture(record, input_event, hints)` → `CycleSnapshot` with secrets
  scrubbed (password/secret/token/credential/api_key/private_key
  redacted, long strings truncated). Serializable via `to_json()`.
- `replay(snapshot, loop)` re-runs the cycle with the action executor
  **forcibly unbound** — replay can never cause side effects, even when
  the original decision was "allow". Restores the executor afterwards.
- `compare(original, replayed)` diffs decisions: failed stage, action,
  policy verdict, plan/policy details. Reports `match` + mismatches.

Replay fidelity depends on deterministic subsystems: seeded topologies,
sorted edge compilation, and snapshot/restore that preserves the neural
delivery queue. Nondeterministic components (live sensors, LLMs) will
diverge on replay — `compare` reports that honestly instead of hiding it.

CLI: `jarvis neural snapshot` runs a probe cycle and prints the captured
snapshot shape (redacted).
