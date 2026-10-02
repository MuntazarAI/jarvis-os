# JARVIS OS Roadmap

This roadmap tracks the engineering direction of JARVIS OS. The project prioritizes correctness, security, and integration before adding more capabilities.

## Current state

- **Main:** stable foundation through the 4.0/4.1 intelligence work and subsequent hardening work as those changes are merged.
- **Primary next milestone:** **4.2 — End-to-End Cognitive Loop**
- **Android 3.10:** parked in `feature/android-transport-3-10` and tracked by Issue #31 until its real-device E2E work is resumed.
- **Raspberry Pi:** planned next device-node milestone after the cognitive loop and Android transport are sufficiently mature.

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
- [x] Android socket transport implementation on the parked 3.10 branch
- [ ] Real Android APK ↔ JARVIS host E2E lifecycle is still incomplete

## 4.2 — End-to-End Cognitive Loop

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
- [ ] Explicit CognitiveLoop orchestration layer
- [ ] Typed contracts for sensory state, cognitive state, reasoning, plans, actions, observations and memory updates
- [ ] Real SensoryBus → Working Memory → World Model integration
- [ ] Real Neural Core → MetaReasoner integration
- [ ] Real MetaReasoner → Mission Planner integration
- [ ] PolicyEngine remains the final authority before every external effect
- [ ] Action → Observation → Memory/World Model feedback loop
- [ ] Bounded cycle/stage timeouts and cancellation behavior
- [ ] Deterministic simulation/demo of a complete cognitive cycle
- [ ] Side-effect-free cognitive replay
- [ ] Structured cognitive telemetry
- [ ] End-to-end security regression tests
- [ ] Cognitive-loop performance benchmark
- [ ] `jarvis cognitive demo` or equivalent real CLI demonstration
- [ ] `docs/COGNITIVE_LOOP.md`

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

- [ ] Camera perception pipeline
- [ ] Audio/microphone pipeline
- [ ] Speech-to-text integration
- [ ] Vision-to-world-model integration
- [ ] Multimodal event normalization
- [ ] Perception confidence/uncertainty
- [ ] Resource-bounded local inference
- [ ] Hardware-aware model selection

## 3.10 — Android real-device transport

This work remains intentionally parked while the cognitive loop is stabilized.

Tracked by **Issue #31**.

Remaining work:

- [ ] Rebase transport against current main
- [ ] Complete APK ↔ host pairing
- [ ] Verify explicit trust approval
- [ ] Verify secret/key exchange
- [ ] Verify authenticated transport
- [ ] Verify heartbeat
- [ ] Verify events/results
- [ ] Verify host-issued typed commands
- [ ] Verify reconnect behavior
- [ ] Verify offline queue behavior
- [ ] Resolve foreground-service lifecycle issues
- [ ] Decide whether TLS/mTLS is required before use beyond a trusted LAN/tunnel
- [ ] Complete real emulator/device E2E tests
- [ ] Merge only after focused and full verification

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

1. **Merge and verify 4.1 intelligence work**
2. **Merge and verify foundation hardening**
3. **Build and prove 4.2 Cognitive Loop**
4. **Resume Android 3.10 and finish real-device E2E**
5. **Build the Raspberry Pi node**
6. **Expand multimodal perception**
7. **Deepen memory/world-model/autonomous mission capabilities**
8. **Scale neural/connectome-inspired research only when benchmarks justify it**

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
