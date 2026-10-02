# JARVIS-OS Research Lab

The Research Lab is the experimental area of JARVIS-OS. Experiments should be reproducible, measurable, and explicit about uncertainty.

## Experiment contract

Every serious experiment should document:

1. **Hypothesis** — what should change and why.
2. **Implementation** — the exact subsystem or algorithm changed.
3. **Inputs** — dataset, synthetic workload, hardware, model, and configuration.
4. **Baseline** — the comparison method.
5. **Metrics** — latency, throughput, accuracy, memory, energy, reliability, or another measurable outcome.
6. **Result** — raw measurements and environment.
7. **Conclusion** — what the evidence supports and what it does not.
8. **Next step** — the smallest useful follow-up.

Do not describe an experiment as successful from intuition alone. Record the measurement.

## Areas

- [Neural systems](neural/README.md)
- Agent planning and tool use
- Memory and retrieval
- Perception
- World modelling
- Device intelligence
- Security and policy
- Performance engineering

## Reproducibility

Prefer deterministic seeds, checked-in configuration, machine-readable benchmark output, and versioned experiment notes. Hardware-specific results must include the hardware and software environment.

Use the [experiment template](templates/EXPERIMENT.md) for new studies.
