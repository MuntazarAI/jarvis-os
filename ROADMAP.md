# JARVIS OS Roadmap

This roadmap tracks the engineering direction of JARVIS OS. The project prioritizes correctness, security, and integration before adding more capabilities.

## Current state

- **Intelligence expansion 5.0:** adaptive-intelligence foundation implemented on `feature/intelligence-expansion-5-0`; pending verification/PR.
- **Verified multimodal perception:** screen, camera, image, file/document pipelines are implemented; audio/STT remains future work.

- **Main:** stable through 4.2 Persistent Device Intelligence; PR #38 is merged and main is green.
- **Primary next milestone:** **4.2 follow-up — Async Operator Command UX** (persistent policy grants + approval notification flow).
- **Android 3.10:** complete and emulator-proven; PR #37 merged. Issue #31 is now obsolete.
- **Raspberry Pi:** planned after the cognitive loop and operator UX are mature.

## Completed / substantially built

### Core platform
- [x] Repository foundation, licensing, contribution/security documentation
- [x] CI, Dependabot, GitHub project hygiene and governance tooling
- [x] Device Fabric foundation
- [x] Typed device capabilities and PolicyEngine-gated routing
- [x] Observability, doctor checks, deterministic test infrastructure

### Intelligence and world model
- [x] Working-memory and long-term memory foundations
- [x] World Model
- [x] Spatial Memory Palace
- [x] God's Eye View and live God's Eye intelligence
- [x] Proactive intelligence foundations
- [x] Missions/planning foundations
- [x] Neural Nervous System 4.0 foundation
- [x] Unified Intelligence 4.1 architecture
- [x] Synthetic 166k-neuron fly-brain schema/benchmark path
- [x] Replay/snapshot foundations with side-effect-safe replay

### Security and reliability
- [x] PolicyEngine as the authorization boundary
- [x] Typed action/tool interfaces
- [x] Fail-closed handling for unknown tools/actions
- [x] AST-gated `python_run` sandbox
- [x] Corrupt world-state recovery
- [x] Bounded frames, queues, telemetry and resource limits where implemented
- [x] Security regression tests and hardening coverage

### Device integration
- [x] Device Fabric architecture
- [x] Android node architecture/skeleton
- [x] Android socket transport implementation (3.10, PR #37)
- [x] Real Android APK ↔ JARVIS host E2E lifecycle (3.10, emulator-proven)
- [x] Persistent device intelligence: durable grants, durable approvals,
  durable command outbox + drainer, DeviceCommandService, operator CLI,
  audit log (4.2 device track, emulator-proven end to end)
- [x] Async operator command UX: persistent policy grants + approval notification flow — mechanism proven in 4.2, operator ergonomics next

## 4.2 — End-to-End Cognitive Loop

> **Sequencing note:** the durable device-control track is complete enough for the next operator UX layer. The cognitive-loop work remains the next major intelligence milestone after that UX hardening.

**Goal:** make the intelligence already built operate as one coherent, testable loop.

Target flow:

```
Input / Environment
        ↓
Perception
        ↓
Sensory Bus
        ↓
Working Memory
        ↓
World Model
        ↓
Neural Core
        ↓
Meta Reasoner
        ↓
Mission Planner
        ↓
PolicyEngine
        ↓
Safe Tool / Device Action
        ↓
Observation
        ↓
Memory + World Model update
        ↺
```

### 4.2 deliverables
- [x] Explicit CognitiveLoop orchestration layer (CognitiveSupervisor over IntelligenceLoop)
- [x] Typed contracts for sensory state, cognitive state, reasoning, plans, actions, observations and memory updates
- [x] Real SensoryBus → Working Memory → World Model integration (supervised via wiring hooks)
- [x] Real Neural Core → MetaReasoner integration (supervised)
- [x] Real MetaReasoner → Mission Planner integration (supervised)
- [x] PolicyEngine remains the final authority before every external effect
- [x] Action → Observation → Memory/World Model feedback loop (observe/learn + learning record)
- [x] Bounded cycle/stage timeouts and cancellation behavior
- [x] Deterministic simulation/demo of a complete cognitive cycle (dry-run + replay)
- [x] Side-effect-free cognitive replay (sandbox + cycle store)
- [x] Structured cognitive telemetry (per-stage durations, outcome records)
- [x] End-to-end security regression tests (25-case battery)
- [x] Cognitive-loop performance benchmark (1.6 ms supervised CLI cycle)
- [x] `jarvis cognitive demo` or equivalent real CLI demonstration (`intelligence cycle|inspect|replay|events|failures`)
- [x] `docs/COGNITIVE_LOOP.md`

### 4.2 acceptance criteria

JARVIS should be able to accept a deterministic local task and demonstrate:

1. input received
2. sensory state created
3. working memory updated
4. world state queried/updated
5. neural processing executed
6. reasoning produced
7. plan generated
8. policy decision made
9. authorized action simulated/executed
10. observation captured
11. memory/world state updated
12. next cognitive cycle can continue

No stage may silently bypass the PolicyEngine.

## 4.3 — Real multimodal perception

After 4.2 is proven:

- [x] Camera perception pipeline (bounded one-shot/sampling, real v4l2 proven)
- [ ] Audio/microphone pipeline (future; voice/ + STT stay separate)
- [ ] Speech-to-text integration (future; faster-whisper optional dep untouched)
- [x] Vision-to-world-model integration (claims + gated file-entity apply)
- [x] Multimodal event normalization (typed contract + SensoryBus adapters)
- [x] Perception confidence/uncertainty (explicit, never inflated)
- [x] Resource-bounded local inference (tesseract/ffmpeg CLI, caps everywhere)
- [x] Hardware-aware model selection (capability detection, honest unavailable)

See `docs/MULTIMODAL_PERCEPTION.md` for architecture, proof, and limits.

## 3.10 — Android real-device transport

**Complete.** PR #37 is merged and the real APK ↔ host lifecycle was proven on emulator-5554.

Verified:
- [x] Pairing and explicit trust
- [x] Secret/key exchange and HMAC authentication
- [x] Heartbeat and presence
- [x] Typed host commands/results
- [x] Reconnect/auth resync behavior
- [x] Lane binding and fail-closed authorization
- [x] Android CI and Kotlin tests

Known limits remain documented: trusted-LAN transport without TLS, plain-prefs secret storage, and idle reconnect churn.

## 5.x — Raspberry Pi device node

The Raspberry Pi is intended to become a **physical JARVIS edge node**, not a replacement for the laptop brain.

Target architecture:

```
                    JARVIS CORE
                  Laptop / Server
                        │
                Secure node transport
                        │
                 Raspberry Pi Node
             ┌──────────┼──────────┐
             ↓          ↓          ↓
          Sensors     Camera      GPIO
          Audio       Display     Devices
```

### Raspberry Pi deliverables
- [ ] Raspberry Pi node registration in Device Fabric
- [ ] Secure authenticated transport
- [ ] Heartbeat/presence
- [ ] Typed capability discovery
- [ ] Sensor telemetry
- [ ] Camera input
- [ ] Microphone/audio input
- [ ] GPIO capability layer
- [ ] Local edge preprocessing
- [ ] Offline/reconnect behavior
- [ ] PolicyEngine-gated physical actions
- [ ] Device health monitoring
- [ ] Safe shutdown/recovery behavior
- [ ] Real Pi hardware E2E tests

### Intended role split

**Laptop/server**
- intelligence
- memory
- reasoning
- planning
- world model
- heavy models

**Raspberry Pi**
- sensors
- camera
- microphone
- GPIO
- lightweight edge processing
- physical device interface

**Android**
- mobile interface/presence
- mobile sensor/device node

## Later intelligence work

### Advanced memory
- [ ] Better episodic memory
- [ ] Semantic memory consolidation
- [ ] Memory relevance scoring
- [ ] Forgetting/decay policies
- [ ] Cross-device memory synchronization

### Advanced world model
- [ ] Temporal world state
- [ ] Causal relationships
- [ ] Uncertainty tracking
- [ ] Better spatial-temporal reasoning
- [ ] Persistent entity tracking

### Neural research
- [ ] Connectome-inspired topology loader
- [ ] Better neural benchmarks
- [ ] Learned weights/plasticity experiments
- [ ] Scale only after evidence
- [ ] Keep biological claims clearly separated from synthetic models

### Autonomous missions
- [ ] Multi-step mission execution
- [ ] Better failure recovery
- [ ] Observation-driven replanning
- [ ] Long-running mission state
- [ ] Human approval checkpoints for higher-risk actions

### Voice
- [ ] Wake-word pipeline
- [ ] Streaming speech recognition
- [ ] Natural TTS
- [ ] Interruptions/barge-in
- [ ] Voice-controlled cognitive loop

## Current priorities

The project should follow this order unless new evidence justifies a change:

1. **Complete the 4.2 Async Operator Command UX**
2. **Build and prove the 4.2 Cognitive Loop end to end**
3. **Build the Raspberry Pi device node**
4. **Expand multimodal perception**
5. **Deepen memory/world-model/autonomous mission capabilities**
6. **Harden distributed-device security for broader-than-LAN use**
7. **Scale neural/connectome-inspired research only when benchmarks justify it**

## Engineering principles

1. **Correctness before capability.**
2. **Integration before feature accumulation.**
3. **PolicyEngine is the final authority for external effects.**
4. **Fail closed on unknown or malformed actions.**
5. **Use typed contracts between intelligence stages.**
6. **Keep simulations and synthetic models clearly labeled.**
7. **Never claim hardware/device testing that was not actually performed.**
8. **Benchmark before making performance claims.**
9. **Prefer deterministic tests for core intelligence behavior.**
10. **Keep parked work visible instead of deleting unfinished work.**
11. **Add real-world capability only after the underlying control loop is reliable.**

## Definition of a mature JARVIS

The long-term goal is not simply a collection of AI features.

A mature JARVIS should be able to:

**perceive → understand state → reason → plan → obtain authorization → act → observe → learn/update state → continue**

while remaining:

- secure
- observable
- recoverable
- resource-bounded
- explainable at the system level
- controllable by the user
- extensible across computers and physical devices


## 5.0 — Adaptive Intelligence Foundation

**Goal:** make JARVIS learn from evidence and outcomes without allowing learning
to bypass security.

- [x] Evidence/provenance contracts
- [x] Bounded belief engine with contradiction tracking
- [x] Explicit uncertainty states
- [x] Deterministic hypothesis ranking
- [x] Active information-gathering selector
- [x] Goal contracts
- [x] Static plan critic
- [x] Experience store with bounded retention
- [x] Secret-key scrubbing at experience persistence
- [x] Prediction/outcome learning primitives
- [x] Capability fingerprinting
- [x] Deterministic regression tests
- [x] Architecture documentation
- [ ] Deep CognitiveSupervisor integration
- [ ] causal inference engine
- [ ] counterfactual simulation
- [ ] long-horizon mission learning
- [ ] skill acquisition
- [ ] multimodal model reasoning
- [ ] intelligence benchmark scorecard
