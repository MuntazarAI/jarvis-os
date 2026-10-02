# JARVIS Neural Nervous System 4.0

JARVIS now has a **bio-inspired neural substrate** as a first-class subsystem.

## Purpose

This layer is inspired by biological nervous systems and spiking neural networks. It
does **not** replace the LLM/cognitive system. Instead it supplies temporal,
recurrent and event-driven dynamics that can sit between perception and cognition
or between cognition and action.

The long-term goal is to support connectome-inspired experiments, including
explicit biological topologies such as insect-brain circuits, without claiming
that structural similarity alone produces biological intelligence.

## Architecture

```
Sensors / perception
        |
        v
  Neural input events
        |
+-----------------------+
| Spiking neural layer  |
| LIF neurons           |
| recurrent connections |
| delayed synapses      |
| bounded plasticity    |
+-----------+-----------+
            |
      neural output events
            |
            v
World model / cognition / action planner
            |
            v
       Policy engine
            |
            v
      External actions
```

## Current implementation

- deterministic leaky-integrate-and-fire (LIF) neurons
- directed weighted synapses
- integer-step transmission delays
- recurrent network support
- explicit sensory and motor event boundaries
- bounded STDP and homeostatic plasticity rules
- serializable snapshots for inspection/debugging
- no direct shell, filesystem, network, device, or tool execution

The implementation deliberately has **no third-party runtime dependency**.

## Connectome roadmap

The API is intentionally topology-driven. Future versions can load a measured
connectome or a connectome-inspired graph instead of the default small circuit:

1. validate neuron and synapse metadata
2. import a documented biological topology
3. map sensory channels to sensory neurons
4. map motor neurons to typed JARVIS action channels
5. benchmark temporal behavior
6. compare against simpler baselines
7. integrate only behaviors that demonstrate measurable value

A future fruit-fly-inspired model may contain roughly the scale of the relevant
fly nervous-system dataset, but the exact neuron count depends on the biological
dataset and model resolution chosen.

## Safety boundary

Neural activity can **suggest** a typed output event. It cannot directly execute
an external action. The existing JARVIS policy/security layer remains authoritative.

This prevents learned/plastic neural dynamics from bypassing authorization.

## Integration strategy

The neural layer is designed to interoperate with:

- perception and vision
- voice/audio events
- the world model
- memory and temporal context
- proactive intelligence
- device fabric
- Android/Pi/robotics nodes
- agent orchestration

The first release is deliberately small and testable. Scaling to a large
biological network is a later engineering and research milestone.
