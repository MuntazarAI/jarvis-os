# Conductor CLI audit (ground truth, 2026-10-04)

31 top-level commands. All keep working; Conductor is additive.
Strategy per command: DIRECT (deterministic admin, stays as-is) or
ROUTABLE (natural-language equivalent enters via Conductor).

| command | implementation | capability | conductor intent | mode | notes |
|---|---|---|---|---|---|
| talk <text> | cycle_once | chat/memory/world | CHAT (passthrough) | DIRECT | canonical path, unchanged |
| repl | ConversationManager loop | session chat | same loop, routed turns | DIRECT+ROUTED | turns routed, session kept |
| say <text> | Speaker/TTS | voice output | VOICE_OUTPUT | DIRECT | deterministic, stays |
| listen | VoiceLoop mic loop | voice I/O | voice input → cycle; output optional | DIRECT | hardware path, stays |
| audio … | perception inspect | audio diagnostics | — | DIRECT | diagnostics, stays |
| voice … | TTS/meal diagnostics | voice diagnostics | — | DIRECT | diagnostics, stays |
| voice-test | deterministic self-test | voice test | — | DIRECT | diagnostics, stays |
| world … | research/cache/sync | live knowledge | WORLD_CURRENT/RESEARCH | DIRECT | admin+research, stays |
| remember … | palace store | memory write | MEMORY_WRITE | DIRECT | deterministic, stays |
| mentalist … | analysis mode | reasoning | KNOWLEDGE | DIRECT | stays |
| see … | vision observe | perception | — | DIRECT | hardware path, stays |
| devices | capability snapshot | diagnostics | DIAGNOSTIC | DIRECT | stays |
| device … | android/transport ops | device control | DEVICE_* | DIRECT | policy-gated, stays |
| device-fabric … | mesh ops | device control | DEVICE_* | DIRECT | stays |
| pi … | pi node ops | edge control | DEVICE_* | DIRECT | stays |
| agents … | orchestrator CLI | agent ops | AGENT_WORKFLOW | DIRECT | stays |
| dots/missions/proactive | workers/missions | tasks | TASK/PROJECT | DIRECT | stays |
| intelligence … | supervisor loop | cognition | — | DIRECT | stays |
| integration … | trace/doctor | diagnostics | DIAGNOSTIC | DIRECT | stays |
| gods-eye … | geo app | live geo | WORLD_CURRENT | DIRECT | stays |
| neural … | fly substrate | neural | — | DIRECT | stays |
| benchmark | timed scenarios | perf | — | DIRECT | stays |
| consolidate | memory job | memory maintenance | — | DIRECT | stays |
| serve/status/start/stop/restart | service mgmt | infra | STATUS | DIRECT | stays |
| doctor | health checks | diagnostics | DIAGNOSTIC | DIRECT | stays |

Overlaps investigated:
- say vs voice say: same engine family (Speaker vs TTS abstraction);
  genuinely distinct backends → both stay, documented.
- devices vs device vs device-fabric: snapshot vs node ops vs mesh
  ops → distinct scopes, all stay.
- voice vs voice-test vs audio: diagnostics vs self-test vs
  perception → distinct, all stay.
- agents vs dots vs missions: org vs workers vs coordinated
  missions → distinct, all stay.

No command is removed or renamed in Conductor 1.0. No thin aliases
introduced: audit found no pair safe to merge without behavior loss,
so the alias layer is documented as future work, not implemented.
