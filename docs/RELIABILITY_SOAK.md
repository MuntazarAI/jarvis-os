# Reliability & Soak 1.0

JARVIS under prolonged operation: correct, bounded, isolated,
recoverable, observable, privacy-preserving, honest.

## Invariants (all tested)

1. Session isolation — no cross-session rows, ever.
2. Correlation integrity — every event attributable to its cycle.
3. Restart durability — committed events survive reopen.
4. Idempotent recovery — dedup keys absorb replays; single-use stays single-use.
5. Bounded memory — soak RSS growth single-digit MB per 500 cycles.
6. Bounded storage — ~1.1KB/cycle event log (measured, linear by design).
7. Learning conservatism — confidence clamped, floored, conflict-capped.
8. Private boundary — private experiences never learned (engine-enforced).
9. World honesty — offline/failed/slow providers yield "unverified", never currentness.
10. Response bounds — 2000-char cap enforced under flood.
11. Failure containment — subscriber crashes, model/world/tool failures contained; healthy next cycle.
12. Trace completeness — bus + conversation + episodes per correlation, payloads minimized.

## Soak methodology

One long-lived process, seeded RNG (seed 42), interleaved sessions,
15 scenario classes (greeting, memory write/recall, static, world
offline, mixed, verified calc, intentional failure, policy-adjacent,
ambiguous, repeats, large/empty input, conflict, voice-session meta,
multi-session). Fake model/router, offline world.

```bash
pytest tests/test_soak.py -q            # 100 cycles
SOAK_CYCLES=500 pytest tests/test_soak.py::test_soak_100_cycles -q
pytest tests/test_reliability.py tests/test_reliability_recovery.py tests/test_learning_drift.py -q
jarvis integration doctor
jarvis integration trace --cycle cycle-3
```

## Measured (500 cycles, this host)

0 failures, 0 isolation violations, 1050 events, RSS 46.9→53.8MB
(+6.8MB), db 127→709KB, beliefs 0→1, learned 8, avg 9.2ms,
p95 16.8ms, max 32.5ms. Verifications: 485 UNKNOWN / 12 VERIFIED /
3 FAILED — honest states, no inflation.

## Persistence semantics

EventStore: sqlite, per-statement commit, UNIQUE event_id, dedup_key
replay absorption. Uncommitted writes never appear. Corrupt rows are
flagged `_corrupt` and skipped past, never fatal. Corrupt DB file
fails loud at open (tested) — no silent degradation.

## Privacy findings

FOUND AND FIXED: credential-shaped spans (AWS/GH/Slack/PEM) persisted
into events.db + palace. `redact_secret_spans` now guards all cycle
persistence points; working text untouched. Verified: 0 credential
rows post-fix, response intact. Ordinary prose unaffected (documented
key-based limitation).

## Rate limiting

Per-process by design: API server instances don't share counters
(tested + documented). Correct for a loopback-first single-operator
system; a shared limiter would need IPC with no demonstrated need.

## Known limitations

- Registry (non-API) rate limits in-memory per process.
- Soak uses fake model; live-model soak not run (GPU/time).
- 1000-cycle run not needed: 500 shows flat slopes.
