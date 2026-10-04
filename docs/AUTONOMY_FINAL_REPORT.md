# Autonomy & Presence 1.0 — Final Report

## Baseline / branch / files
- Baseline: main `01765d1` (Conductor merged). Branch:
  `feature/autonomy-presence-10`. No push/PR/release per mission
  (done at the very end per user instruction to push+merge).
- New: `jarvis/policy/standing.py`, `jarvis/autonomy/{organize,
  presence, preferences, perceive}.py`, `tests/test_autonomy.py`
  (23 tests), 4 docs.
- Modified: `jarvis/tools/tools.py` (+filesystem_move),
  `jarvis/policy/policy.py` (+bind/authorize_standing),
  `jarvis/core/config.py` (+AutonomyConfig),
  `jarvis/cli.py` (grants/autonomy commands),
  `jarvis/conductor/{router,service}.py` (AUTONOMY route).

## Architecture changes
Standing grants as authorization INPUT (never bypass): grant fills
scope coverage; risk/approval/egress/e-stop stay in evaluate().
Organize flow: plan (deterministic rules) → grant check → policy
evaluate → move → verify. Presence: PID-guarded tick runtime reusing
proactive/notification/world-refresh machinery. Preferences recorded
as provenance-marked beliefs, structurally unable to touch
permissions. Perception: pure correlate() over existing contracts.

## Authorization integration
`authorize_standing` consulted explicitly by autonomy paths;
`evaluate()` untouched (zero regression surface). Deny > policy >
grant; expired/revoked/corrupt/mismatch = deny.

## Tests / soak / perf
- 23 autonomy tests green (contract, matrix, store, policy seam,
  organize incl. malicious names, presence incl. e-stop + file watch,
  preferences, correlate, conductor routes, 4 golden E2E).
- Full suite + 100/500-cycle soak rerun at the end (see below).
- Perf: grant check sub-ms (dict lookups); tick dominated by world
  refresh only when due; presence idle = one PID-file read.

## Security audit / threat matrix
See docs/AUTONOMY_SECURITY.md (18 rows, each with mitigation+test).
No shell/eval/exec in new code. Emergency stop verified end to end.

## Known limitations / deferred
- No cross-process shared limiter beyond mtime reload (documented,
  sufficient for loopback single-operator).
- Rename rules: moves only in v1 (names preserved).
- Daemonization is foreground/CLI/cron-driven, not a system service.
- Hardware-dependent capabilities (Pi/phone/HA) audit-only.
- CPU TTS latency unchanged (out of scope by design).
