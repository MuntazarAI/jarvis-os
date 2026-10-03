# JARVIS-OS

<p align="center">
  <img src="docs/assets/jarvis-os-banner.svg" alt="JARVIS-OS — Local Intelligence System Core" width="100%">
</p>

<p align="center">
  <strong>LOCAL-FIRST · EVIDENCE-DRIVEN · MODULAR · BOUNDED AUTONOMY</strong>
</p>

<p align="center">
  <a href="https://github.com/MuntazarAI/jarvis-os/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/MuntazarAI/jarvis-os/ci.yml?branch=main&label=CI&style=flat-square" alt="CI"></a>
  <a href="https://github.com/MuntazarAI/jarvis-os/blob/main/LICENSE"><img src="https://img.shields.io/github/license/MuntazarAI/jarvis-os?style=flat-square" alt="License"></a>
  <a href="https://github.com/MuntazarAI/jarvis-os"><img src="https://img.shields.io/github/stars/MuntazarAI/jarvis-os?style=flat-square" alt="GitHub stars"></a>
  <a href="https://github.com/MuntazarAI/jarvis-os/issues"><img src="https://img.shields.io/github/issues/MuntazarAI/jarvis-os?style=flat-square" alt="GitHub issues"></a>
  <a href="https://github.com/MuntazarAI/jarvis-os/commits/main"><img src="https://img.shields.io/github/last-commit/MuntazarAI/jarvis-os?style=flat-square" alt="Last commit"></a>
  <a href="https://github.com/MuntazarAI/jarvis-os/actions/workflows/project-health.yml"><img src="https://github.com/MuntazarAI/jarvis-os/actions/workflows/project-health.yml/badge.svg?branch=main" alt="Project health"></a>
  <a href="https://github.com/MuntazarAI/jarvis-os/actions/workflows/codeql.yml"><img src="https://github.com/MuntazarAI/jarvis-os/actions/workflows/codeql.yml/badge.svg?branch=main" alt="CodeQL"></a>
  <a href="https://github.com/MuntazarAI/jarvis-os/actions/workflows/scorecard.yml"><img src="https://github.com/MuntazarAI/jarvis-os/actions/workflows/scorecard.yml/badge.svg?branch=main" alt="OpenSSF Scorecard"></a>
  <a href="https://muntazarai.github.io/jarvis-os/"><img src="https://img.shields.io/website?url=https%3A%2F%2Fmuntazarai.github.io%2Fjarvis-os%2F&style=flat-square&label=docs%20site" alt="Docs site"></a>
</p>

<p align="center">
  <a href="#-system-overview">System Overview</a> ·
  <a href="#-core-capabilities">Capabilities</a> ·
  <a href="#-architecture">Architecture</a> ·
  <a href="#-quick-start">Quick Start</a> ·
  <a href="docs/README.md">Docs</a> ·
  <a href="https://muntazarai.github.io/jarvis-os/">Docs site</a> ·
  <a href="https://muntazarai.github.io/jarvis-os/dashboard.html">System Explorer</a>
</p>

---


> **A local-first personal AI operating system for memory, reasoning, perception, automation, and computer control.**

JARVIS-OS is an experimental, modular personal AI platform designed to turn a local computer into a persistent, context-aware assistant.

It combines **cognition, memory, world modeling, evidence-based reasoning, agents, tools, automation, voice, vision, and security controls** behind one architecture.

> **Status:** Active development · public repository · architecture evolving rapidly

## What is JARVIS-OS?

Think of JARVIS-OS as the **infrastructure around an AI brain**.

A model can answer a question. JARVIS-OS is designed to provide the larger operating loop:

**observe → remember → understand → reason → plan → act → verify → reflect**

It is not currently a finished consumer operating system or a claim of human-level intelligence. It is an evolving, testable architecture for building a persistent personal AI system.

## JARVIS in one minute

```text
User
 │
 ▼
Perception
 │
 ├──► Memory
 ├──► World Model
 └──► Evidence
          │
          ▼
       Reasoning
          │
          ▼
     Agents / Tasks
          │
          ▼
   Policy + Security
          │
          ▼
    Tools / Devices
          │
          ▼
    Verify → Reflect
          │
          ▼
       Memory
```

## ◈ System Overview

JARVIS-OS is being built as a **personal intelligence runtime**, not a chat wrapper.

The architecture treats intelligence as a closed operational loop:

`PERCEIVE → CONTEXTUALIZE → REMEMBER → REASON → PLAN → ACT → VERIFY → REFLECT`

Every stage can expose evidence, uncertainty, provenance, budgets, and failure state.

## Why JARVIS-OS?

Most assistants are centered around a single conversation and a single model call.

JARVIS-OS is built around a different idea:

```text
Perceive → Understand → Remember → Reason → Plan → Act → Verify → Reflect
                 ↑                                  ↓
                 └──────── World + Knowledge ───────┘
```

The system is designed to preserve context across tasks while keeping observations, memories, hypotheses, actions, and verification distinguishable.

---

## Core capabilities

| System | What it provides |
|---|---|
| 🧠 Cognitive loop | End-to-end perception, reasoning, planning, action, verification |
| 🗃️ Memory 3.0 | Provenance-aware memory with tiers, correction, reinforcement, and consolidation |
| 🌍 World Model 2.0 | Snapshots, state changes, temporal queries, expectations, predictions, and uncertainty |
| 🕸️ Knowledge graph | Entity relationships, traversal, paths, identity, and version history |
| 🔎 Evidence & reasoning | Hypotheses, Bayesian-style updates, alternatives, red-team analysis |
| 🕵️ Mentalist mode | Evidence-first observation and hypothesis analysis without pretending to read minds |
| 🤖 Agents | DAG planning, delegation, voting, validation, and specialized execution |
| 🛠️ Tools | Sandboxed tools with timeouts and policy controls |
| 🛡️ Security | Policy gates, approvals, consent, sealed secrets, audit, and emergency stop |
| 🖥️ Computer control | Screen observation, clipboard, and approved input automation |
| 🌐 Research | Browser/research workflows with source-aware reasoning |
| 🎙️ Voice | Offline STT, TTS, VAD, wake-word architecture |
| 👁️ Vision | Camera/screen perception with resource-aware fast/slow paths |
| 🧩 Model routing | Local-first model selection and fallback chains |
| ⚙️ Tasks | Workflows, triggers, retries, checkpoints, branches, and cancellation |
| 📡 API | REST + WebSocket interfaces |
| 📊 Verification | Tests, doctor checks, benchmarks, and failure isolation |

---

## Architecture

JARVIS-OS is organized as cooperating subsystems rather than one giant assistant class.

```text
                         ┌─────────────────────┐
                         │       USER          │
                         └──────────┬──────────┘
                                    │
                         ┌──────────▼──────────┐
                         │   Cognitive Loop    │
                         └──────────┬──────────┘
                                    │
              ┌─────────────────────┼─────────────────────┐
              │                     │                     │
       ┌──────▼──────┐       ┌──────▼──────┐       ┌──────▼──────┐
       │  Perception │       │   Memory    │       │    World    │
       │ voice/vision│       │   Memory 3  │       │   Model 2   │
       └──────┬──────┘       └──────┬──────┘       └──────┬──────┘
              │                     │                     │
              └─────────────────────┼─────────────────────┘
                                    │
                         ┌──────────▼──────────┐
                         │ Knowledge + Evidence│
                         │   + Reasoning       │
                         └──────────┬──────────┘
                                    │
                  ┌─────────────────┼─────────────────┐
                  │                 │                 │
           ┌──────▼──────┐   ┌──────▼──────┐   ┌──────▼──────┐
           │    Agents   │   │   Planner   │   │    Policy   │
           │  + DAG      │   │ + Tasks     │   │ + Risk      │
           └──────┬──────┘   └──────┬──────┘   └──────┬──────┘
                  │                 │                 │
                  └─────────────────┼─────────────────┘
                                    │
                         ┌──────────▼──────────┐
                         │ Tools / Computer /  │
                         │ Browser / Services  │
                         └──────────┬──────────┘
                                    │
                         ┌──────────▼──────────┐
                         │ Verify → Reflect →  │
                         │ Memory / World      │
                         └─────────────────────┘
```

### Architecture map

| Layer | Location | Responsibility |
|---|---|---|
| Core | `jarvis/core/` | Loop, configuration, shared types |
| Events | `jarvis/events/` | Event sourcing, replay, snapshots |
| Memory | `jarvis/memory/` | Memory palace, consolidation, graph, identity |
| World | `jarvis/world/` | Environmental and system state |
| Cognition | `jarvis/cognition/` | Intent, attention, executive functions, mentalist mode |
| Inference | `jarvis/inference/` | Evidence, hypotheses, reasoning, analysis |
| Agents | `jarvis/agents/` | Agent orchestration and DAG planning |
| Tasks | `jarvis/tasks/` | Workflows, triggers, retries, checkpoints |
| Models | `jarvis/models/` | Model registry, routing, lifecycle |
| Tools | `jarvis/tools/` | Controlled tool execution |
| Policy | `jarvis/policy/` | Permissions, risk gates, approvals |
| Security | `jarvis/security/` | Secrets, sessions, consent, safeguards |
| Voice | `jarvis/voice/` | STT, TTS, VAD, wake-word pipeline |
| Vision | `jarvis/vision/` | Screen/camera perception |
| API | `jarvis/api/` | REST and WebSocket interfaces |

For the detailed system specification, see [the unified architecture map](docs/JARVIS_FULL_MASTER_MAP_UNIFIED.md).

---

## Quick start

### 1. Clone

```bash
git clone git@github.com:MuntazarAI/jarvis-os.git
cd jarvis-os
```

### 2. Install the package

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

The core project intentionally keeps its Python dependency surface small. Optional capabilities can use local system backends and optional packages.

### 3. Run JARVIS

```bash
jarvis status
jarvis doctor
jarvis talk "hello there"
jarvis repl
```

### Useful commands

```bash
jarvis status
jarvis devices
jarvis doctor
jarvis benchmark
jarvis consolidate

jarvis remember "deploy key rotates monthly" --room "Home"
jarvis mentalist "chair moved"

jarvis see screen --fast
jarvis see camera --fast

jarvis say "Voice online"
jarvis listen --always --no-speak

jarvis start
jarvis stop
jarvis restart
jarvis serve --port 8765
```

### Test the project

```bash
pytest tests/ -q
```

---

## Voice

JARVIS voice = **Chatterbox** (local-first) + the Chatterbox reference
sample `male_old_movie.flac`, selected as the JARVIS voice identity
(a reference prompt, not an official voice).
Reference: `https://storage.googleapis.com/chatterbox-demo-samples/prompts/male_old_movie.flac`

```bash
jarvis voice status
jarvis voice setup     # explicit reference-voice install + verify
jarvis voice test      # deterministic, no mic/GPU/net
jarvis say "Voice online"
jarvis listen --always --no-speak
```

Transcripts are untrusted input through the normal
perception → cognition → policy path; TTS only speaks finished
responses (Chatterbox → existing local fallback → text-only).
Raw audio is transient by default. See
[docs/VOICE_AUDIO_INTELLIGENCE.md](docs/VOICE_AUDIO_INTELLIGENCE.md).

Offline voice support can be installed into the project environment:

```bash
uv venv .venv
uv pip install --python .venv/bin/python faster-whisper sounddevice pytest
source .venv/bin/activate
```

System backends are detected automatically when available, including Ollama, espeak-ng, Tesseract, FFmpeg, and ydotool.

---

## Current status

The repository is actively evolving through milestone-based development. The code and automated tests are the source of truth for what is currently implemented.

| Area | Status |
|---|---|
| Core cognitive architecture | ✅ Foundation |
| Memory / provenance | ✅ Implemented |
| World model | ✅ Implemented |
| Device fabric | ✅ Implemented |
| Android node | ✅ 3.10 transport + E2E |
| Persistent device intelligence | ✅ 4.2 grants/approvals/outbox |
| Neural Nervous System | 🧪 4.0 foundation |
| Real Android network transport | ✅ 3.10 E2E-proven |
| Connectome-scale neural experiments | 🔬 Future research |

> This table intentionally distinguishes implemented foundations from experiments and future work.

---

## Design principles

### Local first

Prefer local models, local memory, local state, and local processing whenever practical.

### Evidence over confidence theater

Observations, facts, hypotheses, predictions, and unknowns should remain distinguishable.

### Unknown stays unknown

A missing sensor or unavailable observation must not silently become a negative fact.

### Verify important work

Actions and conclusions should be independently checked when the task or risk level requires it.

### Policy before action

Tools and computer actions pass through security and policy controls.

### Bounded autonomy

Agents and automation operate within explicit permissions, budgets, timeouts, and cancellation boundaries.

### Resource awareness

The architecture should scale down gracefully on ordinary hardware rather than assuming unlimited GPUs.

### Incremental architecture

Existing working subsystems should be extended rather than repeatedly rewritten.

---

## Safety and security

JARVIS-OS includes application-level safeguards such as:

- policy gates around tool calls
- approval gates for destructive operations
- restricted Python execution
- secret sealing and tamper detection
- consent/session controls
- emergency-stop handling
- prompt/tool injection defenses
- evidence and provenance tracking
- failure isolation

These are software safeguards, not a guarantee of security. Review the code and your local environment before using JARVIS with sensitive systems.

See [SECURITY.md](SECURITY.md) for the project's security-reporting process.

---

## Neural Nervous System 4.0

JARVIS-OS includes a specialized bio-inspired spiking neural subsystem. It does **not** replace the language-model/cognitive stack.

The current foundation provides LIF neurons, recurrent weighted synapses, delayed spike delivery, bounded STDP, homeostatic plasticity, serializable snapshots, and typed sensory/motor boundaries.

A future fruit-fly/connectome-inspired model is a **research direction**, not a claim that the current repository contains a 166,000-neuron biological brain model.

Read [NEURAL_NERVOUS_SYSTEM.md](docs/NEURAL_NERVOUS_SYSTEM.md).

---

## Android node

Android is treated as a normal typed device-fabric node rather than a privileged special case.

The 3.9 foundation includes explicit pairing/trust, typed capabilities, bounded telemetry, heartbeat/presence, safe commands, typed events/results, policy-gated routing, and bounded offline queueing.

The real network transport is complete for the current trusted-LAN model and was E2E-proven with the real APK on emulator-5554. Persistent device intelligence 4.2 now adds durable grants, approvals, command outbox/draining, and audit. Known transport limits remain documented.

Read [ANDROID_NODE.md](docs/ANDROID_NODE.md).

---

## Engineering platform

- [Architecture Decision Records](docs/adr/README.md) — why foundational design choices were made.
- [Plugin SDK](docs/PLUGIN_SDK.md) — bounded extension contract and example.
- [Benchmark Lab](docs/BENCHMARKS.md) — reproducible performance measurements.
- [Release workflow](.github/workflows/release.yml) — source archives, checksums, SBOM and provenance.

## Developer environment

Open this repository in **GitHub Codespaces** or any Dev Container-compatible VS Code setup to get a ready-to-use Python environment. The configuration lives in `.devcontainer/devcontainer.json`.

## Documentation

| Document | Purpose |
|---|---|
| [Architecture map](docs/JARVIS_FULL_MASTER_MAP_UNIFIED.md) | Complete system specification |
| [Documentation index](docs/README.md) | Organized entry point for project documentation |
| [Architecture guide](docs/ARCHITECTURE.md) | High-level architecture and subsystem boundaries |
| [Contributing](CONTRIBUTING.md) | Development workflow and contribution standards |
| [Security](SECURITY.md) | Security reporting and safe disclosure |
| [Changelog](CHANGELOG.md) | Milestone history |

---

## Project structure

```text
jarvis-os/
├── .github/
│   ├── workflows/
│   ├── ISSUE_TEMPLATE/
│   └── pull_request_template.md
├── docs/
│   ├── ARCHITECTURE.md
│   ├── JARVIS_FULL_MASTER_MAP_UNIFIED.md
│   └── README.md
├── jarvis/
│   ├── agents/
│   ├── api/
│   ├── cognition/
│   ├── core/
│   ├── events/
│   ├── inference/
│   ├── memory/
│   ├── models/
│   ├── policy/
│   ├── security/
│   ├── tasks/
│   ├── tools/
│   ├── vision/
│   ├── voice/
│   └── world/
├── tests/
├── CHANGELOG.md
├── CONTRIBUTING.md
├── README.md
├── SECURITY.md
└── pyproject.toml
```

---

## Roadmap

### Completed foundations

- [x] Core cognitive loop
- [x] Memory 3.0 provenance architecture
- [x] World Model 2.0
- [x] Evidence and hypothesis infrastructure
- [x] Policy and security foundations
- [x] Agent/DAG foundation
- [x] Voice/vision/computer foundations
- [x] Research and developer workflows

### In active development

- [ ] Knowledge Graph 2.0 — temporal relationships
- [ ] Agent Intelligence 2.0 — coordinated specialist agents
- [ ] Stronger evidence-chain reconstruction
- [ ] Resource-aware multi-agent scheduling
- [ ] Deeper observability and execution tracing
- [ ] Richer UI/HUD layer

### Longer-term

- [ ] Distributed JARVIS nodes
- [ ] Advanced multimodal temporal memory
- [ ] Capability discovery
- [ ] Model lifecycle management
- [ ] Self-improvement with strict human gates

The roadmap is directional; implemented behavior is defined by the code and tests, not by the specification alone.

---

## Development philosophy

JARVIS-OS is intentionally being built as an evolving systems project.

The goal is not to make a demo that appears intelligent.

The goal is to build infrastructure that can:

**observe → remember → connect → reason → act → verify → learn**

while remaining transparent about uncertainty and limitations.

---

## License

JARVIS-OS is licensed under the [Apache License 2.0](LICENSE).

Copyright 2026 Muntazar Al-Zaidi.

The software license does not automatically grant rights to use project branding or trademarks. See [NOTICE](NOTICE).

## Developer platform

The repository also includes an engineering platform around the runtime:

- **Research Lab** — reproducible experiments and evidence-driven results: [research/](research/README.md)
- **Hardware Lab** — compatibility levels and device reporting: [docs/HARDWARE.md](docs/HARDWARE.md)
- **Developer Portal** — contributor map and subsystem entry points: [docs/DEVELOPER_PORTAL.md](docs/DEVELOPER_PORTAL.md)
- **API map** — stable public boundaries and local API exploration: [docs/API.md](docs/API.md)
- **Roadmap** — implementation, research, and platform work: [docs/ROADMAP.md](docs/ROADMAP.md)
- **Nightly diagnostics** — scheduled deterministic tests and neural benchmark artifacts
- **OpenSSF Scorecard** — supply-chain security analysis
- **Container publishing** — tagged releases can publish a GHCR image
- **Reproducible releases** — release automation already produces checksums, SBOM, and provenance

### Container

Build locally:

```bash
docker build -t jarvis-os .
docker run --rm jarvis-os
```

The container is an orchestration/runtime image. Optional host integrations such as cameras, microphones, GUI automation, and device transports require explicit configuration outside the image.

### GitHub planning

The issue templates provide dedicated paths for research experiments and hardware reports. When GitHub Project-management API access is available, the recommended board columns are:

`Backlog → Ready → In progress → Review → Verified → Released`

Issues should link to the relevant roadmap, experiment, benchmark, or architecture decision.
