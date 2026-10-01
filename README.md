# JARVIS-OS — Personal AI Operating System

Fresh implementation. Core runs on the standard library only.
Voice STT lives in `.venv` (faster-whisper, offline); system backends
(ollama, espeak-ng, tesseract, ffmpeg, ydotool) auto-detect.

## Quick start (the `jarvis` command works from any folder)

```bash
jarvis talk "hello there"
jarvis repl
jarvis remember "deploy key rotates monthly" --room "Home"
jarvis mentalist "chair moved"
jarvis status
jarvis devices          # voice/vision/computer/model capability snapshot
jarvis see screen --fast
jarvis see camera --fast
jarvis say "Voice online"
jarvis listen --always --no-speak   # needs .venv for offline STT
jarvis serve --port 8765
pytest tests/ -q
```

## Voice setup (one time, already done on this machine)

```bash
uv venv .venv && uv pip install --python .venv/bin/python faster-whisper sounddevice pytest
source .venv/bin/activate  # then `jarvis listen` uses offline STT
```

## Architecture (spec: `docs/JARVIS_FULL_MASTER_MAP_UNIFIED.md`)

| Spec system | Module | Status |
|---|---|---|
| Master Cognitive Loop | `jarvis/core/loop.py` | working end-to-end |
| Config / types | `jarvis/core/` | validated, tested |
| Event sourcing + bus | `jarvis/events/store.py` | dedup, snapshots, replay |
| Memory Palace (13 tiers, 20 rooms) | `jarvis/memory/palace.py` | hybrid retrieval, decay |
| Consolidation | `jarvis/memory/consolidation.py` | dedup, merge, promote |
| Knowledge graph + identity | `jarvis/memory/graph.py` | traverse, paths, versions |
| World model + timeline gaps | `jarvis/world/model.py` | arrival-order anomaly detection |
| Perception / understanding / attention | `jarvis/cognition/cognition.py` | intent, entities, budget |
| Executive / reflection | `jarvis/cognition/cognition.py` | Eisenhower, decompose, failure analysis |
| Mentalist mode | `jarvis/cognition/mentalist.py` | display contract, safeguards |
| Evidence / hypothesis / analysis / reasoning | `jarvis/inference/` | Bayesian update, red-team, deception guard |
| Tools (7 sandboxed) | `jarvis/tools/tools.py` | restricted python, timeouts |
| Policy + risk | `jarvis/policy/policy.py` | gates, approvals, e-stop, audit |
| Agents + DAG planner | `jarvis/agents/agents.py` | validated plans, voting |
| Tasks / workflows / triggers | `jarvis/tasks/engine.py` | retries, checkpoints, branches |
| Models router + lifecycle | `jarvis/models/models.py` | local-first, fallback chain |
| Self-model / improvement | `jarvis/models/models.py` | human-gated patches |
| Secrets / sessions / consent | `jarvis/security/security.py` | sealed vault, TTL consent |
| REST + WebSocket API | `jarvis/api/server.py` | token auth |
| Voice / vision | `jarvis/voice/`, `jarvis/vision/` | dormant without hardware |

## Verification

65+ pytest tests on system Python (plus venv-only live-audio/model tests),
all executed against the real code. Verification-first found and fixed
15+ real bugs before they shipped, including: hypothesis-engine recursion,
dead timeline-gap detection, graph kind clobbering, workflow ok-on-failure,
condition short-circuit, cancel idempotency, backwards file triggers,
attention starvation, hypothesis leakage, vacuous permission checks,
tool-risk ignored by the gate, `apt`-in-`capture` false positive,
PyAV incompatibility, and capture-ok-vs-recognized conflation.

## Known hardware truth (this machine, verified live)

- Models: qwen2.5:3b/coder, minicpm-v, nomic-embed via Ollama — answers work.
  No GPU: scene description takes minutes on CPU, so `see` defaults to a
  documented fast/slow split.
- Voice: mic + espeak-ng live; offline faster-whisper STT in `.venv`.
- Computer: screenshot (XWayland layer), GTK clipboard, ydotool input with
  daemon running; full-desktop capture needs portal consent.
- GNOME blocks legacy screenshot DBus and wtype; stadium-grade input waits
  for explicit approval per action.

## Safety rules enforced in code

- Policy gates every tool call; destructive verbs blocked or approval-gated.
- `python_run` has no imports, no dunders, no `open`.
- Deception analysis can never output "person is lying".
- Conflicts are reported with alternative causes, never labeled as lies.
- Secrets are sealed with HMAC; tampering detected on load.
- EMERGENCY STOP file blocks all actions.
