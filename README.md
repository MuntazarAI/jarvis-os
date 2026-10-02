# JARVIS-OS

<p align="center">
  <img src="docs/assets/jarvis-os-banner.svg" alt="JARVIS-OS — Local Intelligence System Core" width="100%">
</p>

<p align="center">
  <strong>LOCAL-FIRST · EVIDENCE-DRIVEN · MODULAR · BOUNDED AUTONOMY</strong>
</p>

<p align="center">
  <a href="https://github.com/MuntazarAI/jarvis-os/actions"><img src="https://img.shields.io/github/actions/workflow/status/MuntazarAI/jarvis-os/slsa.yml?label=build&style=flat-square" alt="Build"></a>
  <img src="https://img.shields.io/github/last-commit/MuntazarAI/jarvis-os?style=flat-square" alt="Last commit">
  <img src="https://img.shields.io/github/repo-size/MuntazarAI/jarvis-os?style=flat-square" alt="Repo size">
  <img src="https://img.shields.io/github/license/MuntazarAI/jarvis-os?style=flat-square&label=license" alt="License status">
</p>

<p align="center">
  <a href="#-system-overview">System Overview</a> ·
  <a href="#-core-capabilities">Capabilities</a> ·
  <a href="#-architecture">Architecture</a> ·
  <a href="#-quick-start">Quick Start</a> ·
  <a href="docs/README.md">Docs</a>
</p>

---


> **A local-first personal AI operating system for memory, reasoning, perception, automation, and computer control.**

JARVIS-OS is an experimental, modular personal AI platform designed to turn a local computer into a persistent, context-aware assistant.

It combines **cognition, memory, world modeling, evidence-based reasoning, agents, tools, automation, voice, vision, and security controls** behind one architecture.

> **Status:** Active development · public repository · architecture evolving rapidly

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

Offline voice support can be installed into the project environment:

```bash
uv venv .venv
uv pip install --python .venv/bin/python faster-whisper sounddevice pytest
source .venv/bin/activate
```

System backends are detected automatically when available, including Ollama, espeak-ng, Tesseract, FFmpeg, and ydotool.

---

## Current verification

The repository is developed verification-first.

The current project documentation records:

- Full test suite: **143 passed, 2 skipped** after World Model 2.0
- World Model 2.0 focused tests: **13 passed**
- `jarvis doctor`: hardware/dependency checks verified on the development machine
- Benchmarking includes cognitive-cycle and memory-search timing
- Resource-heavy model paths are explicitly treated as constrained on CPU-only hardware

The exact verification state can change as development continues; run the commands above for the current state.

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

No open-source license has been declared yet. Until a license is added to this repository, reuse rights should not be assumed.
