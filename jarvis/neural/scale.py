"""Sparse, scalable leaky-integrate-and-fire network.

This module complements :mod:`jarvis.neural.core` (per-object neurons, good
for small circuits) with an array-backed representation that can actually
hold ~166,000 neurons and a connectome-scale directed synaptic graph without
requiring a Python object per neuron or per synapse:

- neuron state: flat ``array`` buffers (potentials, thresholds,
  refractory counters, spike counts, last-spike times)
- synapses: CSR adjacency (row offsets + target/weight/delay arrays)
- delivery: sparse, event-driven — only fired neurons push current
- stepping: fully deterministic; no RNG inside the step path

Plasticity hooks reuse :mod:`jarvis.neural.plasticity` (bounded STDP +
homeostasis) and are opt-in.
"""

from __future__ import annotations

from array import array
from typing import Any, Iterable, Sequence

from .plasticity import HomeostaticPlasticity, STDPRule


class SparseLIFNetwork:
    """Array-backed deterministic spiking network.

    Parameters mirror :class:`LIFNeuron` defaults so small-scale behaviour
    matches :mod:`jarvis.neural.core`.
    """

    def __init__(self, size: int, *, threshold: float = 1.0,
                 leak: float = 0.9, refractory_steps: int = 0,
                 max_delay: int = 32) -> None:
        if size <= 0:
            raise ValueError("size must be positive")
        if max_delay < 0:
            raise ValueError("max_delay must be non-negative")
        self.size = int(size)
        self.max_delay = int(max_delay)
        self.time = 0
        self.potentials = array("d", [0.0]) * self.size
        self.thresholds = array("d", [float(threshold)]) * self.size
        self.leaks = array("d", [float(leak)]) * self.size
        self.refractory_left = array("l", [0]) * self.size
        self.refractory_steps = int(refractory_steps)
        self.spike_counts = array("l", [0]) * self.size
        self.last_spike = array("l", [-10**9]) * self.size
        # CSR graph (empty until connect_* is called).
        self.row_ptr: list[int] = [0] * (self.size + 1)
        self.targets: array("l") = array("l")
        self.weights: array("d") = array("d")
        self.delays: array("l") = array("l")
        self._pending: list[tuple[int, int, int, float]] = []  # (src, dst, delay, w)
        self._queue: dict[int, list[tuple[int, float]]] = {}
        self.stdp: STDPRule | None = None
        self.homeostasis: HomeostaticPlasticity | None = None

    # -- construction ----------------------------------------------------
    def _check_node(self, node: int) -> None:
        if not 0 <= node < self.size:
            raise IndexError(f"node {node} outside network of size {self.size}")

    def stage_edge(self, source: int, target: int, weight: float,
                   delay: int = 1) -> None:
        """Stage one directed edge; call :meth:`compile` before stepping."""
        self._check_node(source)
        self._check_node(target)
        if not isinstance(weight, (int, float)) or weight != weight:  # NaN check
            raise ValueError(f"invalid weight: {weight!r}")
        if not 0 <= delay <= self.max_delay:
            raise ValueError(f"delay {delay} outside [0, {self.max_delay}]")
        self._pending.append((source, target, int(delay), float(weight)))

    def connect_many(self, edges: Iterable[tuple[int, int, float] |
                                           tuple[int, int, float, int]]) -> None:
        for edge in edges:
            if len(edge) == 3:
                source, target, weight = edge
                self.stage_edge(source, target, weight)
            else:
                source, target, weight, delay = edge
                self.stage_edge(source, target, weight, delay)

    def compile(self) -> None:
        """Build the CSR graph from staged edges (deterministic order)."""
        # Sort by (source, target, delay) so identical edge sets always
        # compile to identical CSR arrays regardless of insertion order.
        staged = sorted(self._pending, key=lambda e: (e[0], e[1], e[2]))
        counts = [0] * self.size
        for source, _t, _d, _w in staged:
            counts[source] += 1
        row_ptr = [0] * (self.size + 1)
        for i in range(self.size):
            row_ptr[i + 1] = row_ptr[i] + counts[i]
        targets: array("l") = array("l", [0]) * len(staged)
        weights: array("d") = array("d", [0.0]) * len(staged)
        delays: array("l") = array("l", [0]) * len(staged)
        cursor = list(row_ptr[:-1])
        for source, target, delay, weight in staged:
            pos = cursor[source]
            targets[pos] = target
            weights[pos] = weight
            delays[pos] = delay
            cursor[source] = pos + 1
        self.row_ptr = row_ptr
        self.targets = targets
        self.weights = weights
        self.delays = delays
        self._pending = []

    # -- stepping ---------------------------------------------------------
    def step(self, inputs: dict[int, float] | None = None) -> list[int]:
        """Advance one tick; return sorted list of fired neuron ids."""
        currents = self._gather(inputs)
        fired = self._update(currents)
        self._deliver(fired)
        if self.stdp is not None:
            self._apply_stdp(fired)
        if self.homeostasis is not None:
            self._apply_homeostasis()
        self.time += 1
        return fired

    def _gather(self, inputs: dict[int, float] | None) -> dict[int, float]:
        currents: dict[int, float] = {}
        for node, current in self._queue.pop(self.time, []):
            currents[node] = currents.get(node, 0.0) + current
        for node, current in (inputs or {}).items():
            self._check_node(node)
            currents[node] = currents.get(node, 0.0) + float(current)
        return currents

    def _update(self, currents: dict[int, float]) -> list[int]:
        fired: list[int] = []
        potentials = self.potentials
        thresholds = self.thresholds
        leaks = self.leaks
        refractory = self.refractory_left
        for node in range(self.size):
            if refractory[node]:
                refractory[node] -= 1
                continue
            potentials[node] = potentials[node] * leaks[node] + currents.get(node, 0.0)
            if potentials[node] >= thresholds[node]:
                potentials[node] = 0.0
                refractory[node] = self.refractory_steps
                self.spike_counts[node] += 1
                self.last_spike[node] = self.time
                fired.append(node)
        fired.sort()
        return fired

    def _edges_from(self, source: int) -> list[tuple[int, float, int]]:
        start, end = self.row_ptr[source], self.row_ptr[source + 1]
        return [(int(self.targets[i]), float(self.weights[i]), int(self.delays[i]))
                for i in range(start, end)]

    def _deliver(self, fired: list[int]) -> None:
        for source in fired:
            for target, weight, delay in self._edges_from(source):
                arrival = self.time + max(1, delay)
                self._queue.setdefault(arrival, []).append((target, weight))

    def _apply_stdp(self, fired: list[int]) -> None:
        assert self.stdp is not None
        fired_set = set(fired)
        for source in fired:
            start, end = self.row_ptr[source], self.row_ptr[source + 1]
            for i in range(start, end):
                target = int(self.targets[i])
                if target in fired_set:
                    continue  # synchronous pair: no ordering info
                new_w = self.stdp.update(
                    float(self.weights[i]),
                    int(self.last_spike[source]),
                    int(self.last_spike[target]),
                )
                self.weights[i] = new_w

    def _apply_homeostasis(self) -> None:
        assert self.homeostasis is not None
        window = max(1, self.time)
        for node in range(self.size):
            rate = float(self.spike_counts[node]) / window
            self.thresholds[node] = self.homeostasis.update_threshold(
                float(self.thresholds[node]), rate)

    # -- inspection -------------------------------------------------------
    def run(self, inputs_by_step: Iterable[dict[int, float]]) -> list[list[int]]:
        return [self.step(inputs) for inputs in inputs_by_step]

    def reset(self) -> None:
        self.time = 0
        self._queue.clear()
        self.potentials = array("d", [0.0]) * self.size
        self.refractory_left = array("l", [0]) * self.size
        self.spike_counts = array("l", [0]) * self.size
        self.last_spike = array("l", [-10**9]) * self.size

    def synapse_count(self) -> int:
        return len(self.weights)

    @property
    def edge_count(self) -> int:
        return len(self.weights)

    @property
    def total_spikes(self) -> int:
        return sum(self.spike_counts)

    def snapshot(self, include_weights: bool = False) -> dict[str, Any]:
        snap: dict[str, Any] = {
            "time": self.time,
            "size": self.size,
            "edge_count": len(self.weights),
            "total_spikes": sum(self.spike_counts),
            "potentials": list(self.potentials),
            "thresholds": list(self.thresholds),
            "refractory_left": list(self.refractory_left),
            "spike_counts": list(self.spike_counts),
            "queue": [[arrival, node, current]
                      for arrival, events in self._queue.items()
                      for node, current in events],
        }
        if include_weights:
            snap["weights"] = list(self.weights)
        return snap

    def restore(self, snap: dict[str, Any]) -> None:
        if snap.get("size") != self.size:
            raise ValueError("snapshot size mismatch")
        self.time = int(snap["time"])
        self.potentials = array("d", snap["potentials"])
        self.thresholds = array("d", snap["thresholds"])
        self.refractory_left = array("l", snap["refractory_left"])
        self.spike_counts = array("l", snap["spike_counts"])
        if "weights" in snap:
            if len(snap["weights"]) != len(self.weights):
                raise ValueError("snapshot weight count mismatch")
            self.weights = array("d", snap["weights"])
        self._queue.clear()
        for arrival, node, current in snap.get("queue", []):
            self._queue.setdefault(int(arrival), []).append((int(node), float(current)))
