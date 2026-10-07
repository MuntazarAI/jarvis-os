# JARVIS-OS — System Map (single paper)

Everything built so far, how it connects, and where it lives.

## The one loop everything serves

```
INPUT (text/voice/device/world)
  → Conductor routes → cycle_once → memory/world/reasoning
  → policy → tools/agents/devices → verification → learning
  → memory/world update → traceable RESPONSE (+ optional voice)
```

## The map

```
                        ┌─ YOU ──────────────────────────┐
                        │ repl / talk / listen / API     │
                        └───────────────┬────────────────┘
                                        ▼
                              ┌──────────────────┐
                              │ CONDUCTOR 1.0    │  front door: jarvis "..."
                              │ deterministic    │  20 intents, floor 0.55
                              │ router           │  hostile→refuse, vague→ask
                              └────────┬─────────┘
              ┌────────────────────────┼────────────────────────┐
              ▼                        ▼                        ▼
   ┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
   │ COGNITIVE LOOP   │    │ AGENT MESH 1.0   │    │ DIRECT COMMANDS  │
   │ talk/repl/voice  │    │ 31 roles, teams  │    │ say/device/world │
   │ memory/world/KG  │    │ least-privilege  │    │ grants/doctor…   │
   │ policy → verify  │    │ tester, budgets  │    │ (31 cmds, kept)  │
   └────────┬─────────┘    └────────┬─────────┘    └──────────────────┘
            │                       │
            ▼                       ▼
   ┌────────────────────────────────────────────┐
   │ POLICY ENGINE (sole authority)             │
   │ grants (actor/durable/standing) + approvals│
   │ (single-use) + emergency stop + audit      │
   └────────┬───────────────────────────────────┘
            ▼
   ┌────────────────────────────────────────────┐
   │ SUBSYSTEMS (all reuse, none duplicated)    │
   │ Memory 3.0 · World Intel 1.x · KG · Dots/  │
   │ Missions · Device fabric (Android/Pi) ·    │
   │ Voice (Chatterbox Turbo, persistent) ·     │
   │ Vision · Computer control · Research ·     │
   │ Security-audit tools (approval-gated)      │
   └────────┬───────────────────────────────────┘
            ▼
   ┌────────────────────────────────────────────┐
   │ FOUNDATIONS                                │
   │ EventStore (sqlite, traceable) · Backup   │
   │ (create/verify/restore) · 24/7 service    │
   │ (lifecycle/scheduler/systemd) · Presence  │
   └────────────────────────────────────────────┘
```

## Milestones shipped (all merged, tagged, released)

| # | Milestone | What it added | Proof |
|---|-----------|---------------|-------|
| 5.1 | Voice & Audio | Chatterbox TTS, JARVIS voice, audio→cognition | heard aloud, non-silent wav |
| 5.2 | Persistent voice | Turbo loads once, stays READY; bridge | 3×1 load, RTF ~10 CPU |
| 5.3 | Conversational loop | turn-taking, session link, stop(), latency stats | 15 tests |
| 6.0 | World Intel 1.0 | evidence/claims/conflicts/freshness, research, briefings | 36 tests, live HN/wiki verified |
| 6.1 | Experience 1.0 | one coherent loop, trace, eval/learn, session ids | 13 golden E2E |
| 6.2 | Reliability 1.0 | 500-cycle soak, leak fixed, drift bounds | 500/0-fail, 1030 tests |
| 6.3 | World Intel 1.1 | subscriptions, refresh, proactive briefings | live CLI verified |
| — | Agent Mesh 1.0 | least-privilege gate, tester, chain guard | 23 tests |
| — | Conductor 1.0 | front door + router + REPL integration | 46 tests |
| — | Autonomy 1.0 | standing grants, presence, organize, preferences | 23 tests |
| — | Sec tools + approvals | 6 audit tools, durable single-use approvals | 20 tests |
| — | Backup 1.0 | create/verify/restore/retention, wiki guide | 7 tests |
| — | Service 2.0 | lifecycle, watchdog, scheduler, systemd unit | 19 tests |

## Guarantees holding across all of it

- PolicyEngine authorizes everything; transcripts/web content never do.
- Transcripts untrusted · audio transient · secrets scrubbed · telemetry metadata-only.
- Deterministic offline tests; real hardware/network always opt-in and labeled.
- Full suite green at every merge (currently **1177 passed**).

## Honest limits (unchanged)

CPU voice ~15s/sentence · no duplex barge-in · mic content untested ·
Pi audio pending · faster-whisper PyAV-blocked · per-process rate limits.
