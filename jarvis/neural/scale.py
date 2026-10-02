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

    def topology_digest(self) -> str:
        return _digest_topology(self.row_ptr, self.targets, self.delays)

    def snapshot(self, include_weights: bool = False,
                 mode: str = "full") -> dict[str, Any]:
        """Capture network state.

        Contract:
        - mode="full" (default): everything needed for bit-exact
          deterministic continuation, including weights, last-spike times,
          leaks, the pending delivery queue, and plasticity configuration.
        - mode="diagnostic": same membrane state but weights replaced by a
          digest. Restoring a diagnostic snapshot resumes dynamics but NOT
          learned weights; restore() refuses it when exact=True.
        include_weights=True is kept as a legacy alias for mode="full".
        """
        if include_weights:
            mode = "full"
        if mode not in ("full", "diagnostic"):
            raise SnapshotError(f"unknown snapshot mode: {mode!r}")
        snap: dict[str, Any] = {
            "version": SNAPSHOT_VERSION,
            "mode": mode,
            "time": self.time,
            "size": self.size,
            "edge_count": len(self.weights),
            "topology_digest": self.topology_digest(),
            "total_spikes": sum(self.spike_counts),
            "refractory_steps": self.refractory_steps,
            "max_delay": self.max_delay,
            "potentials": list(self.potentials),
            "thresholds": list(self.thresholds),
            "leaks": list(self.leaks),
            "refractory_left": list(self.refractory_left),
            "spike_counts": list(self.spike_counts),
            "last_spike": list(self.last_spike),
            "queue": [[arrival, node, current]
                      for arrival, events in self._queue.items()
                      for node, current in events],
            "stdp": ({
                "enabled": True,
                "potentiation": self.stdp.potentiation,
                "depression": self.stdp.depression,
                "window": self.stdp.window,
                "min_weight": self.stdp.min_weight,
                "max_weight": self.stdp.max_weight,
            } if self.stdp is not None else {"enabled": False}),
            "homeostasis": ({
                "enabled": True,
                "target_rate": self.homeostasis.target_rate,
                "learning_rate": self.homeostasis.learning_rate,
                "min_threshold": self.homeostasis.min_threshold,
                "max_threshold": self.homeostasis.max_threshold,
            } if self.homeostasis is not None else {"enabled": False}),
        }
        if mode == "full":
            snap["weights"] = list(self.weights)
        else:
            snap["weights_digest"] = _digest_weights(self.weights)
        return snap

    def restore(self, snap: dict[str, Any], *, exact: bool = True) -> None:
        """Restore state from :meth:`snapshot`. Validates everything
        explicitly and raises SnapshotError (never bare KeyError) on any
        malformed or incompatible snapshot.

        exact=True (default): requires mode="full", matching topology
        digest, and matching plasticity presence, so the future trajectory
        is bit-identical. exact=False allows diagnostic snapshots and
        missing-plasticity restores for inspection/debugging.
        """
        if not isinstance(snap, dict):
            raise SnapshotError(f"snapshot must be a mapping, got {type(snap).__name__}")
        if snap.get("version") != SNAPSHOT_VERSION:
            raise SnapshotError(
                f"unsupported snapshot version: {snap.get('version')!r} "
                f"(expected {SNAPSHOT_VERSION})")
        if snap.get("size") != self.size:
            raise SnapshotError(
                f"snapshot size mismatch: snapshot has {snap.get('size')}, "
                f"network has {self.size}")
        if snap.get("edge_count") != len(self.weights):
            raise SnapshotError(
                f"snapshot edge count mismatch: snapshot has {snap.get('edge_count')}, "
                f"network has {len(self.weights)}")
        if snap.get("topology_digest") != self.topology_digest():
            raise SnapshotError(
                "snapshot topology digest mismatch: snapshot was taken from a "
                "differently-wired network")
        mode = snap.get("mode", "full")
        if exact and mode != "full":
            raise SnapshotError(
                f"exact restore requires a full snapshot, got mode={mode!r}")
        for key in ("potentials", "thresholds", "leaks", "refractory_left",
                    "spike_counts", "last_spike"):
            values = snap.get(key)
            if not isinstance(values, list) or len(values) != self.size:
                raise SnapshotError(
                    f"snapshot key {key!r} must be a list of length {self.size}")
        weights = snap.get("weights")
        if mode == "full":
            if not isinstance(weights, list) or len(weights) != len(self.weights):
                raise SnapshotError("full snapshot needs a weights list matching edge count")
        queue = snap.get("queue", [])
        if not isinstance(queue, list):
            raise SnapshotError("snapshot queue must be a list")
        parsed_queue: dict[int, list[tuple[int, float]]] = {}
        for entry in queue:
            try:
                arrival, node, current = entry
                arrival_i, node_i, current_f = int(arrival), int(node), float(current)
            except (TypeError, ValueError):
                raise SnapshotError(f"malformed queue entry: {entry!r}")
            if not 0 <= node_i < self.size:
                raise SnapshotError(f"queue entry targets unknown node {node_i}")
            parsed_queue.setdefault(arrival_i, []).append((node_i, current_f))

        stdp_cfg = snap.get("stdp", {"enabled": False})
        home_cfg = snap.get("homeostasis", {"enabled": False})
        if exact and bool(stdp_cfg.get("enabled")) and self.stdp is None:
            raise SnapshotError("snapshot requires STDP but this network has none enabled")
        if exact and bool(home_cfg.get("enabled")) and self.homeostasis is None:
            raise SnapshotError(
                "snapshot requires homeostasis but this network has none enabled")

        # All validation passed: commit the restore.
        self.time = int(snap["time"])
        self.refractory_steps = int(snap.get("refractory_steps", self.refractory_steps))
        self.potentials = array("d", snap["potentials"])
        self.thresholds = array("d", snap["thresholds"])
        self.leaks = array("d", snap["leaks"])
        self.refractory_left = array("l", snap["refractory_left"])
        self.spike_counts = array("l", snap["spike_counts"])
        self.last_spike = array("l", snap["last_spike"])
        if mode == "full" and isinstance(weights, list):
            self.weights = array("d", weights)
        self._queue = parsed_queue
        if self.stdp is not None and bool(stdp_cfg.get("enabled")):
            for field in ("potentiation", "depression", "window",
                          "min_weight", "max_weight"):
                if field in stdp_cfg:
                    setattr(self.stdp, field, stdp_cfg[field])
        if self.homeostasis is not None and bool(home_cfg.get("enabled")):
            for field in ("target_rate", "learning_rate",
                          "min_threshold", "max_threshold"):
                if field in home_cfg:
                    setattr(self.homeostasis, field, home_cfg[field])

class SnapshotError(ValueError):
    """Raised when a neural snapshot is malformed or incompatible."""


SNAPSHOT_VERSION = 1


def _digest_topology(row_ptr: list[int], targets: array, delays: array) -> str:
    import hashlib
    h = hashlib.sha256()
    h.update(str(list(row_ptr)).encode())
    h.update(b"|")
    h.update(str(list(targets)).encode())
    h.update(b"|")
    h.update(str(list(delays)).encode())
    return h.hexdigest()[:32]


def _digest_weights(weights: array) -> str:
    import hashlib
    return hashlib.sha256(str(list(weights)).encode()).hexdigest()[:32]
