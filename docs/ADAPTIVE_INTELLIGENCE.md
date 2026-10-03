# Adaptive Intelligence (4.4) — Experience & Learning

JARVIS learns from verified experience through a bounded,
deterministic, fully inspectable pipeline. This system implements
**bounded deterministic adaptive intelligence, not AGI.**

## Architecture

```
cognitive cycle outcome
        │
        v
Experience (immutable, append-only)
        │
        v
OutcomeEvaluator → should_learn?
        │
        v
LearningEngine → belief adjustments + patterns (provenanced)
        │
        ├──→ Dots metadata (last_verified, experience_refs)
        ├──→ World entities (confidence, last_verified)
        └──→ MemoryPalace (only via consolidation proposals)
```

## Experience model

One immutable record per cycle: refs to observation/event/decision/
action/verification (IDs + digests, never media), outcome
(SUCCESS|PARTIAL|FAILED|NO_ACTION|NO_DECISION|UNKNOWN), prediction
error, confidence, provenance, privacy class. Corrections are new
evaluation records appended to the same experience — history is
never rewritten. Idempotent on `cycle_id` (retries safe).

## Beliefs

A belief is a statement plus separate confidence, evidence, and
status (ACTIVE|WEAKENED|CONTRADICTED|SUPERSEDED|EXPIRED). Later
evidence revises confidence or status with revision bumps — the
original record and its evidence stay intact. Contradictions
preserve both sides and resolve by freshness, provenance,
reliability, and verification (explicit, never silent).

## Prediction evaluation

Categorical verdicts (CORRECT|INCORRECT|PARTIAL|UNRESOLVED) plus
optional 0..1 magnitude. Textual expected/actual compare with
partial-overlap → ambiguous (never forced). Missing evidence →
UNRESOLVED, never success.

## Learning engine

Deterministic heuristic, documented weights (`CONF_STEP=0.05`,
clamp [0.05, 0.95]): verified-correct predictions nudge up,
failures nudge down, partials preserve contradiction, repeated
action failures weaken supporting beliefs, recurring outcomes
(≥3) become pattern candidates with evidence refs. Source
reliability nudges per verified outcome (weighting only).

`PRIVATE` experiences are never learned; proposals skip
sensitive/private beliefs. Consolidation to semantic memory
requires ACTIVE + confidence ≥0.8 + ≥2 evidence + never promoted,
and goes through `palace.store_fact` (dedup and poisoning
guards intact).

## Structural safety boundary

`jarvis/cognition/learning.py` imports no policy, device,
transport, or permission code (proven by AST test). Learning can
change beliefs, confidence, predictions, patterns, and
consolidation proposals. It CANNOT change permissions, trust,
authorization, policy, secrets, pairing, or allowlists — a learned
"50 successes" pattern never authorizes anything.

## Neural signal (experiment)

Fixed 32-neuron deterministic spiking read-out (seed 7, no
training, no RNG in step): 8 experience features → bounded
±0.03 nudge. Fallback is exactly 0.0. Measured on a scripted
8-case battery: base error 3.800 vs neural 3.733 (marginal, within
noise) at ~10 ms per fresh instance. Verdict: stays optional;
learning proceeds identically without it.

## Replay

Sandbox replay never learns, never acts, never touches providers.
Duplicate events never create duplicate experiences.

## CLI

`intelligence experience list|show|search|evaluate`,
`intelligence beliefs list|show|contradictions`,
`intelligence learning status|explain`. Bounded, secret-free,
deterministic exit codes.

## Retention

Experiences: append-only file, bounded 2000-entry index.
Beliefs: bounded 500 with weakest-eviction. Predictions expire
via `PredictionBoard` TTLs. Memory consolidation follows palace
retention; private material never persists.
