# AGENTS.md — working in JARVIS-OS

This repo is a local-first AI system (Python, stdlib-first, CLI-first).
 nostalgic fetchers: read the code, run the tests, trust exit codes.

## Layout (what goes where)

- `jarvis/cli.py` — all CLI surface (parsers + `_x_action` handlers).
- `jarvis/conductor/` — deterministic intent router + front-door service.
  Routing never authorizes anything.
- `jarvis/agents/` — multi-agent org (planner, orchestrator, teams).
- `jarvis/policy/` — PolicyEngine: approvals (single-use), standing
  grants, emergency stop, audit. Prose never executes actions.
- `jarvis/durable/` — crash-safe tasks: contracts, atomic store, runner,
  recovery engine. Tests: `tests/test_durable_tasks.py`.
- `jarvis/api/` — REST + WebSocket server; `board.py` is the read-only
  status snapshot + page. Tests: `tests/test_board.py`.
- `jarvis/security/` — guards (injection scan), vault, consent;
  `strix.py` is the policy-gated dynamic-scan bridge (optional dep).
- `jarvis/voice|vision|world|memory|…` — perception/cognition subsystems.

## House rules

1. **Reuse, never duplicate.** A second scheduler, bus, policy engine,
   or memory store is a bug. Wire into the existing one.
2. **Transcripts and model output are UNTRUSTED INPUT.** The only path
   to action is perception → cognition → intent → policy → approval →
   existing command path.
3. **Bound everything.** Payloads, buffers, retries, timeouts, retention.
   Unknown is a valid answer; low-confidence is never certainty.
4. **Fail closed.** Corrupt state quarantines, it never parses into
   authority. Illegal state transitions raise.
5. **No secrets in logs/traces/memory/snapshots.** Scrub tokens and keys
   at the boundary; tests must assert absence.
6. **Verify like Strix:** a green run is not proof. Prefer
   `verification: verified` over `ok: true`; write the test that would
   have caught your bug.

## Workflow

- New branch per milestone (`feature/<name>-<n>`), tests first where
  practical, full `pytest tests/` gate before PR, squash-merge.
- Deterministic tests only: fakes and tmp homes, no network, no models,
  no mic. Mark hardware-dependent tests to skip cleanly.
- CLI exit codes are API: `doctor`/`service doctor`/`task doctor`
  exit non-zero on failure — CI depends on it, keep it so.

## Quick probes (read-only)

- `python3 -m jarvis.cli --home /tmp/probe status`
- `python3 -m jarvis.cli --home /tmp/probe task doctor`
- `python3 -m pytest tests/test_board.py tests/test_durable_tasks.py -q`
