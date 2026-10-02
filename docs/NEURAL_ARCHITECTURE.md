# Neural Architecture (4.1)

Two layers, one contract: the small exact simulator (`core.py`) for
readability and tests, the sparse substrate (`scale.py`) for scale. Both
share LIF semantics and delay conventions, verified by mirrored tests.

## SparseLIFNetwork (`jarvis/neural/scale.py`)

- State: flat arrays (potentials, thresholds, leaks, refractory,
  spike counts, last-spike tick). No Python object per neuron state.
- Synapses: CSR (`row_ptr`, `targets`, `weights`, `delays`). No object
  per synapse. `synapse_count()` reports edges; `edge_count` property too.
- Delivery: event-driven sparse queue keyed by arrival tick. A step costs
  O(N) membrane updates + O(spikes × fan-out) deliveries — never O(N×M).
- Delays: `arrival = time + max(1, delay)`, identical to `core.py`.
- Plasticity (optional, off by default): bounded STDP via the existing
  `STDPRule` on pre/post spike pairs + homeostatic threshold nudges.
- Determinism: staged edges are sorted at `compile()`; seeded
  `SyntheticGenerator` for topologies; snapshot/restore includes the
  in-flight queue, so replay is exact.
- Validation: NaN/Inf weights rejected, node bounds checked, delays ≥ 0.

## Measured performance (this laptop, pure Python, no numpy)

- 166,000 neurons, 1,671,998 synthetic edges: generation 3.4 s.
- 10 steps on that network: ~2.1 s total.
- 500 neurons / 5,000 edges: ~0.11 ms per step.

## Boundaries

`jarvis/neural/interface.py` defines the only neural↔cognitive vocabulary:
`NeuralObservation`, `NeuralState`, `NeuralIntent`, `SensoryEmbedding`,
`MotorIntent` (9-action allowlist), `AttentionSignal`, `NoveltySignal`,
`ConfidenceSignal`. The network emits typed signals; it cannot execute.
