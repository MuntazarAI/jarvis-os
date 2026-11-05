"""
Fruit Fly Brain Neural Network — JARVIS-OS integration.

Wraps the Drosophila-inspired connectome schema (FLY_166K_SCHEMA, 166,000
neurons, 12 populations, 16 projections) from jarvis.neural.topology as a
SparseLIFNetwork that JARVIS can drive with sensory events and read motor
outputs from.

Honesty contract (from topology.py):
- No measured biological connectome ships with this repository.
- FLY_166K_SCHEMA is *inspired by* Drosophila brain organization. Neuron
  counts, projections, weights and delays are schematic placeholders,
  NOT measured data.
- All output is tagged ``origin": "synthetic"`` and must never be presented
  as biological data.

Policy boundaries:
- Read-only neural simulation. No tool execution, no deploy, no install,
- no modify. Every output is an event; callers remain responsible for
- authorization through PolicyEngine.
- Opt-in: the fly brain is not wired into any control path by default.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .scale import SparseLIFNetwork
from .topology import (
    FLY_166K_SCHEMA,
    ConnectomeSchema,
    build_network,
    SyntheticGenerator,
)

__all__ = [
    "FlyBrainInput",
    "FlyBrainOutput",
    "FlyBrainNetwork",
    "get_fly_brain",
    "build_fly_brain_network",
]

# -- sensory input population mapping ---------------------------------------
# Each input channel maps to a population's neuron range. Driving a channel
# injects current into that population's neurons.
_SENSORY_POPULATIONS: dict[str, str] = {
    "vision:retina": "lamina",          # photoreceptor input
    "vision:medulla": "medulla",        # early visual processing
    "vision:lobula": "lobula",          # feature detection
    "olfaction:antenna": "antennal",    # odor input
    "gustation:proboscis": "gustatory", # taste input
}

# -- motor output population mapping ----------------------------------------
# Output channels read spike activity from motor populations.
_MOTOR_POPULATIONS: dict[str, str] = {
    "motor:descending": "descending",   # descending motor commands
    "motor:neck": "motor",              # head/neck motor output
}

# -- population index helpers ------------------------------------------------

def _population_slice(schema: ConnectomeSchema, name: str) -> tuple[int, int]:
    """Return (lo, hi) neuron indices for a population."""
    ranges = schema.population_ranges()
    if name not in ranges:
        raise ValueError(f"unknown population: {name}")
    return ranges[name]


class FlyBrainInput:
    """Sensory input driver for the fly brain network.

    Channels:
      vision:retina    -> lamina
      vision:medulla   -> medulla
      vision:lobula    -> lobula
      olfaction:antenna -> antennal
      gustation:proboscis -> gustatory
    """

    def __init__(self, network: SparseLIFNetwork, schema: ConnectomeSchema) -> None:
        self.network = network
        self.schema = schema
        self._slices = {
            channel: _population_slice(schema, pop)
            for channel, pop in _SENSORY_POPULATIONS.items()
        }
        self.last_values: dict[str, float] = {}

    def channels(self) -> list[str]:
        return sorted(self._slices.keys())

    def inject(self, channel: str, value: float) -> None:
        """Inject sensory current into a population.

        The value (0.0 to 1.0) is distributed as input current across the
        target population's neurons. Clamped to [0, 1].
        """
        if channel not in self._slices:
            raise ValueError(f"unknown input channel: {channel}")
        value = max(0.0, min(1.0, value))
        self.last_values[channel] = value
        lo, hi = self._slices[channel]
        # Distribute current across the population; each neuron gets a
        # fraction so large populations don't overwhelm the network.
        per_neuron = value / max(1, (hi - lo))
        for i in range(lo, hi):
            self.network.potentials[i] += per_neuron


class FlyBrainOutput:
    """Motor output reader for the fly brain network.

    Channels:
      motor:descending -> descending population
      motor:neck       -> motor population
    """

    def __init__(self, network: SparseLIFNetwork, schema: ConnectomeSchema) -> None:
        self.network = network
        self.schema = schema
        self._slices = {
            channel: _population_slice(schema, pop)
            for channel, pop in _MOTOR_POPULATIONS.items()
        }

    def channels(self) -> list[str]:
        return sorted(self._slices.keys())

    def read(self, channel: str) -> float:
        """Read normalized spike rate from a motor population (0.0 to 1.0)."""
        if channel not in self._slices:
            raise ValueError(f"unknown output channel: {channel}")
        lo, hi = self._slices[channel]
        total_spikes = sum(self.network.spike_counts[i] for i in range(lo, hi))
        size = hi - lo
        if size == 0 or self.network.time == 0:
            return 0.0
        # Normalize: spikes per neuron per time step, clamped to [0, 1]
        rate = total_spikes / (size * max(1, self.network.time))
        return min(1.0, rate)

    def read_all(self) -> dict[str, float]:
        return {ch: self.read(ch) for ch in self._slices}


# -- main network wrapper ----------------------------------------------------

@dataclass
class FlyBrainState:
    """Snapshot of fly brain network state."""
    version: str = "1.0-fly-brain-synthetic"
    origin: str = "synthetic"
    total_neurons: int = 0
    total_synapses: int = 0
    time: int = 0
    last_fired: list[int] = field(default_factory=list)
    motor_outputs: dict[str, float] = field(default_factory=dict)
    sensory_inputs: dict[str, float] = field(default_factory=dict)
    populations: dict[str, dict[str, Any]] = field(default_factory=dict)


class FlyBrainNetwork:
    """
    Drosophila-inspired spiking neural network for JARVIS-OS.

    Wraps FLY_166K_SCHEMA (166,000 neurons) as a SparseLIFNetwork.
    Provides sensory input channels and motor output channels.
    Read-only: emits events only, never executes tools.
    """

    def __init__(
        self,
        schema: ConnectomeSchema | None = None,
        seed: int = 0,
        max_delay: int = 32,
    ) -> None:
        self.schema = schema or FLY_166K_SCHEMA
        self.seed = int(seed)
        self.max_delay = int(max_delay)
        self.network = build_network(self.schema, seed=self.seed, max_delay=self.max_delay)
        self.input = FlyBrainInput(self.network, self.schema)
        self.output = FlyBrainOutput(self.network, self.schema)
        self.time = 0
        self._last_fired: list[int] = []
        self._initialized = True

    def step(
        self,
        sensory: dict[str, float] | None = None,
    ) -> dict[str, float]:
        """Advance the network one time step.

        Args:
            sensory: mapping of input channel -> value (0.0 to 1.0).
                Channels: vision:retina, vision:medulla, vision:lobula,
                olfaction:antenna, gustation:proboscis.

        Returns:
            mapping of output channel -> normalized spike rate (0.0 to 1.0).
                Channels: motor:descending, motor:neck.
        """
        # Inject sensory inputs
        if sensory:
            for channel, value in sensory.items():
                self.input.inject(channel, value)

        # Step the network
        self.network.step()
        self.time = self.network.time

        # Capture fired neurons
        self._last_fired = list(self.network.last_fired) if hasattr(self.network, "last_fired") else []

        # Read motor outputs
        outputs = self.output.read_all()
        return outputs

    def snapshot(self) -> FlyBrainState:
        """Return a read-only snapshot of network state."""
        pop_states: dict[str, dict[str, Any]] = {}
        ranges = self.schema.population_ranges()
        for name, (lo, hi) in ranges.items():
            pop_spikes = sum(self.network.spike_counts[i] for i in range(lo, hi))
            pop_states[name] = {
                "neurons": hi - lo,
                "spikes": pop_spikes,
                "threshold": float(self.network.thresholds[lo]) if lo < self.network.size else 0.0,
                "leak": float(self.network.leaks[lo]) if lo < self.network.size else 0.0,
            }

        total_synapses = len(self.network.targets)

        return FlyBrainState(
            total_neurons=self.network.size,
            total_synapses=total_synapses,
            time=self.network.time,
            last_fired=list(self._last_fired),
            motor_outputs=self.output.read_all(),
            sensory_inputs=dict(self.input.last_values),
            populations=pop_states,
        )

    def to_dict(self) -> dict[str, Any]:
        state = self.snapshot()
        return {
            "version": state.version,
            "origin": state.origin,
            "total_neurons": state.total_neurons,
            "total_synapses": state.total_synapses,
            "time": state.time,
            "last_fired_count": len(state.last_fired),
            "motor_outputs": state.motor_outputs,
            "sensory_inputs": state.sensory_inputs,
            "populations": state.populations,
            "policy_gated": True,
            "read_only": True,
        }


# -- global instance ----------------------------------------------------------

_fly_brain: FlyBrainNetwork | None = None


def get_fly_brain(
    schema: ConnectomeSchema | None = None,
    seed: int = 0,
    max_delay: int = 32,
) -> FlyBrainNetwork:
    """Get or create the global fly brain network instance."""
    global _fly_brain
    if _fly_brain is None:
        _fly_brain = FlyBrainNetwork(schema=schema, seed=seed, max_delay=max_delay)
    return _fly_brain


def build_fly_brain_network(
    seed: int = 0,
    max_delay: int = 32,
) -> FlyBrainNetwork:
    """Build a fresh fly brain network (not cached)."""
    return FlyBrainNetwork(schema=FLY_166K_SCHEMA, seed=seed, max_delay=max_delay)


# -- convenience helpers ------------------------------------------------------

def fly_brain_status() -> dict[str, Any]:
    """Return the current fly brain status (creates if needed)."""
    brain = get_fly_brain()
    return brain.to_dict()


def fly_brain_step(sensory: dict[str, float] | None = None) -> dict[str, float]:
    """Step the global fly brain and return motor outputs."""
    brain = get_fly_brain()
    return brain.step(sensory)

