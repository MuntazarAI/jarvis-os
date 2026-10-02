"""Small deterministic leaky-integrate-and-fire neural simulator."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


@dataclass
class LIFNeuron:
    """Leaky integrate-and-fire neuron with an explicit refractory period."""

    threshold: float = 1.0
    leak: float = 0.9
    reset: float = 0.0
    refractory_steps: int = 0
    potential: float = 0.0
    refractory_left: int = 0
    spikes: int = 0

    def step(self, current: float) -> bool:
        if self.refractory_left:
            self.refractory_left -= 1
            return False
        self.potential = self.potential * self.leak + current
        if self.potential < self.threshold:
            return False
        self.potential = self.reset
        self.refractory_left = self.refractory_steps
        self.spikes += 1
        return True

    def state(self) -> dict[str, float | int]:
        return {"potential": self.potential, "refractory_left": self.refractory_left, "spikes": self.spikes}


@dataclass(frozen=True)
class Synapse:
    """Directed weighted connection between two neurons."""

    source: int
    target: int
    weight: float
    delay: int = 0


@dataclass
class SpikingNetwork:
    """Deterministic recurrent SNN with integer-step delayed spike delivery."""

    size: int
    neurons: list[LIFNeuron] = field(default_factory=list)
    synapses: list[Synapse] = field(default_factory=list)
    time: int = 0

    def __post_init__(self) -> None:
        if self.size <= 0:
            raise ValueError("size must be positive")
        if not self.neurons:
            self.neurons = [LIFNeuron() for _ in range(self.size)]
        if len(self.neurons) != self.size:
            raise ValueError("neurons length must equal size")
        self._queue: dict[int, list[tuple[int, float]]] = {}

    def connect(self, source: int, target: int, weight: float, delay: int = 0) -> Synapse:
        self._check_node(source)
        self._check_node(target)
        if delay < 0:
            raise ValueError("delay must be non-negative")
        synapse = Synapse(source, target, float(weight), delay)
        self.synapses.append(synapse)
        return synapse

    def connect_many(self, edges: Iterable[tuple[int, int, float] | tuple[int, int, float, int]]) -> None:
        for edge in edges:
            self.connect(*edge)

    def step(self, inputs: dict[int, float] | None = None) -> list[int]:
        currents = [0.0] * self.size
        for node, current in self._queue.pop(self.time, []):
            currents[node] += current
        for node, current in (inputs or {}).items():
            self._check_node(node)
            currents[node] += float(current)

        fired = [node for node, neuron in enumerate(self.neurons) if neuron.step(currents[node])]

        # A zero-delay synapse means "next simulation tick", not same-tick
        # recursive firing. This keeps the simulator deterministic and finite.
        for synapse in self.synapses:
            if synapse.source in fired:
                arrival = self.time + max(1, synapse.delay)
                self._queue.setdefault(arrival, []).append((synapse.target, synapse.weight))

        self.time += 1
        return fired

    def run(self, inputs_by_step: Iterable[dict[int, float]]) -> list[list[int]]:
        return [self.step(inputs) for inputs in inputs_by_step]

    def reset(self) -> None:
        self.time = 0
        self._queue.clear()
        for neuron in self.neurons:
            neuron.potential = neuron.reset
            neuron.refractory_left = 0
            neuron.spikes = 0

    def snapshot(self) -> dict[str, object]:
        return {
            "time": self.time,
            "size": self.size,
            "neurons": [n.state() for n in self.neurons],
            "synapses": [{"source": s.source, "target": s.target, "weight": s.weight, "delay": s.delay} for s in self.synapses],
        }

    def _check_node(self, node: int) -> None:
        if not 0 <= node < self.size:
            raise IndexError(f"node {node} outside network of size {self.size}")
