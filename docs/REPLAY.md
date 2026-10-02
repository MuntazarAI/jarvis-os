# Cycle Replay (4.1)

`jarvis/intelligence/snapshot.py`: capture, replay, compare.

- `capture(record, input_event, hints)` → `CycleSnapshot` with secrets
  scrubbed (password/secret/token/credential/api_key/private_key
  redacted, long strings truncated). Serializable via `to_json()`.
- `replay(snapshot, loop)` re-runs the cycle inside
  `loop.sandbox()` — a **genuine dry-run loop**, not just an unbound
  executor. The sandbox shares only the pure stages
  (normalize/neural/reason/plan); world, recall, policy, observe and
  learn are side-effect-free stubs; there is no executor at all
  (`IntelligenceLoop(dry_run=True)` refuses one at construction and the
  `act` stage is hard-disabled). Replay therefore never touches world
  state, spatial memory, policy audit, approvals, persistent memory, or
  live learning state. An optional `neural_checkpoint`/`neural_restore`
  pair (auto-wired by `wiring.build_loop` when the network supports
  snapshot/restore) freezes the live network across replay.
- `compare(original, replayed)` diffs the **cognitive decision path**
  only (failed stage, action, plan/reason details). Policy outcomes are
  reported as info, because sandbox replay deliberately never consults
  live policy state.

Replay fidelity depends on deterministic subsystems: seeded topologies,
sorted edge compilation, and snapshot/restore that preserves the neural
delivery queue. Nondeterministic components (live sensors, LLMs) will
diverge on replay — `compare` reports that honestly instead of hiding it.

CLI: `jarvis neural snapshot` runs a probe cycle and prints the captured
snapshot shape (redacted).
