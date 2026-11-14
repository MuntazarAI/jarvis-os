# Changelog

All notable project milestones are recorded here.

## Unreleased

### A British voice for JARVIS

- Added the Kokoro TTS provider: a natural local British male voice
  (`bm_george`), no GPU needed
- Added the Edge TTS provider (`en-GB-RyanNeural`): the most natural
  voice, but it is cloud, so it is opt-in only and never picked
  automatically
- The piper fallback now finds its voice model by itself and prefers the
  British male voices; it also gets its text as bytes on stdin, which is
  what piper actually reads
- `voice.tts_provider` now defaults to `auto`: kokoro → piper →
  chatterbox → espeak, the best local engine that is really installed
- Added `jarvis voice voices` (what is installed, what can speak) and
  `jarvis voice voices --install piper|kokoro` for the voice assets
- Added `jarvis voice runtime`: creates the voice runtime
  (`~/.config/jarvis/voice-venv`, Python 3.12 via `uv`) that holds
  piper, kokoro and edge-tts — they do not install on Python 3.13+
- `jarvis install` now also makes JARVIS able to speak: it creates the
  voice runtime when needed, installs the British male voice, and moves
  an old pinned config to `auto`
- The doctor check `voice:chatterbox` is now `voice:engine`

### Any model, any provider

- Added pluggable model backends: local Ollama, NVIDIA NIM, and any
  OpenAI-compatible server (LM Studio, vLLM, llama.cpp, Groq,
  OpenRouter, Together, OpenAI)
- Added per-kind model selection (`fast`, `reasoning`, `coding`, `vision`,
  `embedding`) with a fallback chain across backends
- Added `jarvis models list|add|remove|use|test|key`; keys live in the
  encrypted vault, never in config, argv or logs
- Added a local-only privacy wall that removes remote backends from the
  routing chain until it is deliberately turned off
- Added `jarvis install`: one command that installs the package, starts
  the two user systemd services (background loop + local API), configures
  a backend, and runs the health checks
- Added `docs/MODELS.md`

### Security and correctness pass

- Approval tokens are minted with the `appr-` prefix the redactors
  recognise, so a token that reaches a log or a cycle record is scrubbed
- Approval arguments are stored scrubbed plus an exact fingerprint: the
  binding survives a restart, a credential does not reach the store
- An ambiguous token prefix resolves to nothing; a spent approval stays
  spent; `consume_approval` refuses a token that was never approved;
  `approved()` honours the expiry
- A device denial is final instead of re-asking forever; an explicit
  standing-grant deny beats an older allow
- The emergency stop fails closed in the device router and the security
  scanner
- `filesystem_read` refuses credential stores, with one shared list
- The task store quarantines a corrupt file and refuses to overwrite it;
  the world state file is written atomically
- The tool budget is per cycle again, and "Tests PASS." reads the exit
  code
- `python_run` executes in a child process with an OS-enforced timeout
- The coding loop goes through the policy gate as the coder role
- Stored goals are no longer silently truncated; a failed capture is an
  error, not an observation; daily schedules re-arm and fire again
- CLI exit codes are honest: the doctor sub-commands, device approvals
  and a failed security scan now fail loudly
- Bounded the in-memory state that grew without limit (tool history,
  orchestrator runs, hypotheses, observations, notifications, graph
  history)

### In development

- Knowledge Graph 2.0 — temporal relationships
- Agent Intelligence 2.0 — coordinated specialist agents
- Stronger evidence-chain reconstruction
- Resource-aware multi-agent scheduling
- Expanded observability

## 2026-10-02

### World Model 2.0

- Added `StateSnapshot` and `StateChange`
- Added bounded state history and JSON persistence
- Added application, network, resource, room, and file diffs
- Added temporal helpers
- Added expectation lifecycle
- Added prediction lifecycle with evidence requirements
- Added candidate-only causal relationships
- Preserved unknown-as-unknown semantics
- Integrated state capture into the cognitive loop with failure isolation
- Added 13 focused World Model tests
- Verified the broader suite at 143 passed / 2 skipped on the development machine

### Repository presentation

- Reorganized the public README
- Added documentation index and architecture guide
- Added contribution and security policies
- Added changelog
- Added GitHub issue and pull-request templates
