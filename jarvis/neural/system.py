"""JARVIS-facing facade around the spiking neural substrate."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .core import LIFNeuron, SpikingNetwork


@dataclass
class NeuralEvent:
    """A bounded sensory or motor event crossing the neural boundary."""

    channel: str
    value: float
    source: str = "internal"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class NeuralNervousSystem:
    """Temporal neural layer connecting sensors to bounded motor signals.

    The neural layer is intentionally subordinate to JARVIS policy. It emits
    typed events only; callers remain responsible for authorization and tool
    execution.
    """

    input_size: int
    hidden_size: int
    output_size: int
    threshold: float = 1.0

    def __post_init__(self) -> None:
        if min(self.input_size, self.hidden_size, self.output_size) <= 0:
            raise ValueError("all layer sizes must be positive")
        self.network = SpikingNetwork(self.input_size + self.hidden_size + self.output_size)
        for neuron in self.network.neurons:
            neuron.threshold = self.threshold
        self.input_nodes = list(range(self.input_size))
        self.hidden_nodes = list(
            range(self.input_size, self.input_size + self.hidden_size)
        )
        self.output_nodes = list(
            range(self.input_size + self.hidden_size, self.network.size)
        )
        self._wire_default_circuit()
        self.last_fired: list[int] = []

    def _wire_default_circuit(self) -> None:
        # Dense input→hidden and hidden→output routing keeps the first version
        # deterministic while allowing arbitrary connectome-like topologies later.
        for src in self.input_nodes:
            for dst in self.hidden_nodes:
                self.network.connect(src, dst, 0.35)
        for src in self.hidden_nodes:
            for dst in self.output_nodes:
                self.network.connect(src, dst, 0.35)
        # Recurrent hidden loop provides temporal state.
        for i, src in enumerate(self.hidden_nodes):
            self.network.connect(src, self.hidden_nodes[(i + 1) % len(self.hidden_nodes)], 0.08)

    def step(self, events: list[NeuralEvent] | None = None) -> list[NeuralEvent]:
        inputs: dict[int, float] = {}
        for event in events or []:
            if event.channel.startswith("input:"):
                try:
                    index = int(event.channel.split(":", 1)[1])
                except ValueError as exc:
                    raise ValueError(f"invalid neural input channel: {event.channel}") from exc
                if not 0 <= index < self.input_size:
                    raise IndexError("neural input index outside configured input size")
                inputs[index] = inputs.get(index, 0.0) + event.value

        self.last_fired = self.network.step(inputs)
        fired_outputs = [node for node in self.last_fired if node in self.output_nodes]
        return [
            NeuralEvent(
                channel=f"output:{node - self.output_nodes[0]}",
                value=1.0,
                source="neural",
                metadata={"node": node, "time": self.network.time},
            )
            for node in fired_outputs
        ]

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": "4.0-neural-nervous-system",
            "input_size": self.input_size,
            "hidden_size": self.hidden_size,
            "output_size": self.output_size,
            "time": self.network.time,
            "last_fired": list(self.last_fired),
            "network": self.network.snapshot(),
        }
