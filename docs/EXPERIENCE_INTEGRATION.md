# Experience & Integration 1.0

One interaction travels one path: OBSERVE → CONTEXTUALIZE → REMEMBER →
UNDERSTAND → REASON → PLAN → POLICY → ACT → VERIFY → REFLECT → LEARN →
UPDATE → RESPOND. This page maps that path onto actual code and proves
each boundary with tests.

## What was already unified (no changes needed)

- `Jarvis.cycle_once` (`jarvis/core/loop.py`): perception → attention
  → understand → dialogue → memory → hypotheses → policy → act →
  reflect → episode → world events, all under one correlation id.
- Voice (`VoiceLoop.converse_once`) uses the same `cycle_once` with
  `source="voice"` — same policy path, never a second brain.
- Conversation continuity: dialogue router + last-4-turns context +
  open tasks; pronouns resolve or clarify honestly.
- Failure: TaskEngine bounded retries; cycle errors stay honest strings.

## What was missing and added (minimal extensions only)

1. **World routing in questions** (`_world_answer`): memory miss →
   currentness router → bounded researcher (2 searches, 30s) for
   CURRENT/HISTORICAL/RESEARCH, local snapshot for LOCAL. Static
   default; failures fall through to model/gap honestly.
2. **Voice sessions** (`VoiceSession` wired into `VoiceLoop`;
   `cycle_once(..., session_id=...)`): turns share a session id across
   processes; palace rows + episode metadata carry it.
3. **Outcome evaluation + learning**: per-cycle tool results →
   VERIFIED/FAILED/UNKNOWN → `OutcomeEvaluator` →
   `LearningEngine`+`BeliefStore` (selective, private never learned) →
   `CycleResult.verification` / `.learned`.
4. **Persistent event log**: `EventStore` now lives at
   `<home>/events.db` (was `:memory:`) so traces survive restarts.
   Same schema, tests untouched.
5. **Unified trace** (`jarvis/cognition/trace.py`): bus events +
   conversation + episodes by correlation id; unknown ids return
   explicit gaps.
6. **CLI**: `jarvis integration doctor` (10 boundaries) and
   `jarvis integration trace --cycle <id> [--session <id>]`.

## Boundaries that stay separate (documented, not merged)

- `EventBus` (core cycle) vs `SensoryBus` (intelligence path): two
  orchestrations sharing the same stores. Merging event systems is
  out of scope; both are tested.
- `intelligence/` supervisor path keeps its own learning wiring;
  core cycle now has its own via shared engine classes.

## Measured baselines (this host)

context 0.76ms · memory 0.06ms · routing 0.13ms · full cycle 23ms
(fake model) · events.db 32KB · jarvis.db 92KB per cycle-home.
No bottlenecks; nothing optimized.

## Verification

`tests/test_experience_e2e.py`: 10 golden scenarios (conversation,
memory, world offline/evidence, mixed context, verified action,
honest failure, voice session, device observation, injection
inertness, resource bounds) + session/verification plumbing.
