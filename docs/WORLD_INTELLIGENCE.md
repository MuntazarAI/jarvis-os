# World Intelligence 1.0

Evidence-driven live knowledge — not a chatbot search button. JARVIS
determines whether a question needs current information, retrieves
through a provider-neutral architecture, preserves provenance and
time, extracts claims, detects conflicts, tracks freshness, updates
the existing World Model and Knowledge Graph, and answers with
labeled uncertainty.

## What existed vs what was added

Reused (no duplicates): geospatial live providers + bounded HTTP +
SyncEngine (retrieval/storage), ResearchEngine + BrowserAgent + SSRF/
injection guards (research/fetch), WorldRegistry + JsonFileWorldStore
(observations), KnowledgeGraph (entities/relations/identity),
StateTracker (change primitives), TaskEngine (scheduling), PrivacyClass
+ secret scrubbing, JarvisConfig, CLI/doctor/API conventions.

New (`jarvis/worldintel/`, only the reasoning pieces that did not
exist): claims + rule-based extractor, freshness engine, dedupe +
corroboration + conflict detector, currentness router, source registry
(+ RSS/HackerNews providers), bounded evidence cache, research
orchestrator, world/KG sync, snapshot diff, briefings, local-world
adapters, health, `world` CLI, two API routes.

## Pipeline

```
question → route (STATIC/CURRENT/HISTORICAL/LOCAL/MIXED/RESEARCH/CLARIFY)
  → retrieve (HN/RSS/wiki/live, budgeted, rate-limited)
  → normalize → dedupe → claims → conflicts → freshness
  → synthesize (question/scope/claims/conflicts/freshness/conclusion/
    uncertainty/provenance) → sync to World Model + KG → answer
```

## Key contracts

- Internet content is untrusted evidence, never instructions.
  Injection scans flag content; claims never contain payload text that
  matched attack patterns (tested).
- Claims keep qualifiers (reportedly/alleged/may…); conflicts stay
  explicit and unresolved — sides are never silently picked.
- Freshness is per-domain policy (news hours, reference months);
  missing timestamps are UNKNOWN, never fresh.
- Cached evidence is labeled stale-or-fresh, never presented as live.
- Live retrieval failures produce "unverified" answers, never
  fabricated currentness.
- Local observations are LOCAL class and never leave the machine.
- Budgets: 4 searches, 12 evidence items, 90s, 2MB per research task.

## CLI / API

`jarvis world status|sources|search|research|events|changes|refresh|
briefing|health|diagnostics`. `POST /api/world/research`,
`GET /api/world/health` (existing token gate applies).

## Measured (2026-10-03)

HN top-5 fetch 5.6s; wiki search 0.8s; full research turn recorded in
telemetry. Extractor recall is conservative by design: 10/10 HN
headlines retrieved, 0 full claims (headlines lack verbs) — briefings
label these unverified leads instead of forcing claims. SNN-style
overclaiming is a design violation here.

## Limitations

Registry rate limits are per-process (in-memory); cross-process flood
protection is future work. Briefings read local snapshots only.
No background crawling (refresh is explicit, consent-gated).
API research calls are per-client throttled
(`WorldConfig.api_rate_limit_n` per `api_rate_window_s`, 429 with
retry guidance); legitimate spaced calls are unaffected.

## 1.1 — Subscriptions, scheduled refresh, proactive briefings

- `world topics [--topic NAME | --topic -NAME]`: bounded (50) atomic
  watch list, separate from code-side config topics.
- `world refresh [--notify]`: live geo sync + per-topic research with
  interval skip, snapshot history, and change diffing. First refresh
  per topic establishes a silent baseline; only genuine deltas notify.
- Notifications flow as untrusted `world_changed` proactive events
  (cooldowns, quiet hours, and dedupe handled by the existing engine).
