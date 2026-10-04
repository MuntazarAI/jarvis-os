# Conductor 1.0

Unified front door: `jarvis "anything"` routes deterministically into
existing JARVIS capabilities. Conductor classifies, clarifies, and
dispatches. It never authorizes, plans, executes, remembers, or
synthesizes — those belong to the existing systems below.

## Architecture

```
USER → CONDUCTOR → INTENT ROUTER → capability/agent selection
                                              |
                    +-------------------------+------------------+
                    |                         |                  |
                 cycle_once              Orchestrator       devices/voice/
              (chat/memory/world)      (agent teams)      diagnostics/say
                    |                         |
                    +------> PolicyEngine ----+
                         (allow → approval → action → verify)
```

## Routing

Table-driven rules in `jarvis/conductor/router.py`: hostile markers
(security guards + forgery patterns) → routine (help/status) → voice
output → memory write/read → device → diagnostic → testing/review →
engineering/debugging → planning → safety questions → tasks →
World Intel currentness → session follow-ups → risk-verb ambiguity →
short-input ambiguity → CHAT default. No model calls; same input +
state → same route. Below confidence 0.55: clarify, never guess.

## RouteDecision

`intent/target/confidence/reason/risk_level` + clarification and
confirmation flags + entities + `provenance="conductor-router-v1"`.
Serializable, logged as `conductor.route` bus events (metadata only).

## Agent Mesh / World / Memory / Voice / Devices / Diagnostics

- RESEARCH/DEBUGGING/ENGINEERING/TESTING/REVIEW/PLANNING/SECURITY_ANALYSIS/DIAGNOSTIC → existing Orchestrator teams; Planner/Supervisor/tools reused; budgets/depth/fallbacks unchanged.
- WORLD_CURRENT/HISTORICAL/MIXED → `cycle_once` (world routing lives there).
- MEMORY_* → `cycle_once`; no Conductor memory store.
- VOICE_OUTPUT → `VoiceSpeaker` (existing TTS stack).
- DEVICE_READ → fabric listing; DEVICE_ACTION → guidance text pointing at the explicit command + policy path (never executes from prose).
- Existing commands untouched (see `docs/CONDUCTOR_AUDIT.md`).

## Security boundary

USER TEXT → CONDUCTOR → ROUTE → CAPABILITY/AGENT → POLICYENGINE →
DENY/APPROVAL → AUTHORIZED TOOL → VERIFY. Router output is data;
handoff content stays untrusted; emergency stop pauses everything but
read-only routes. Secrets scrubbed by existing perception contracts;
telemetry carries lengths/counts only.

## Sessions / REPL / CLI

One-shot `jarvis "..."` supports trailing `--speak`/`--json`.
`repl` routes every turn through the service, keeping
ConversationManager sessions (`/reset`, `/summary`, `/quit`
preserved). Exit codes: 0 with a response (including clarifications),
1 on hard errors, 2 on usage errors.

One way in: bare `jarvis`, `repl [--speak]`, and `jarvis "..."` all
run the same ConductorService turns. `talk` stays a direct cycle call
(routing short greetings through the conductor degraded them, so that
was tried and reverted). `listen` stays the hardware voice loop;
`say` stays direct TTS.

## Failure / degraded behavior

Unknown → clarify. Hostile → refuse + policy record. Unavailable
capability → honest message. Timeouts/budgets from existing layers.
No silent retries of anything dangerous.

## Extension

New capability = route rule + target handler calling an existing
subsystem + tests. No new registries; agent skills come from the
existing SkillRegistry via role cards.

## Known limitations

- Router is keyword/structural, not semantic: novel phrasings fall
  back to CHAT (safe) or clarify.
- DEVICE_ACTION never executes from prose (by design, permanent).
- True duplex voice barge-in out of scope.
- No cross-CLI daemon; REPL sessions are per-process.
