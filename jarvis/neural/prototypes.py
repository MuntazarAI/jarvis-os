"""Connectome-inspired topology prototypes (#24).

Three documented structural sketches for spike-propagation experiments
on :class:`SparseLIFNetwork`:

- small_world: ring lattice with rewired shortcuts (local clustering +
  short paths).
- layered: feedforward stages with lateral inhibition inside stages.
- hub: a few high-degree nodes relaying between otherwise sparse pools
  (rich-club sketch).

These are wiring patterns for benchmarks, not models of any brain.
No biological equivalence is claimed; names describe graph structure
only. Deterministic under a fixed seed (stdlib random only).
"""

from __future__ import annotations

import random
import time
from typing import Any

from .scale import SparseLIFNetwork

Edge = tuple[int, int, float, int]

MAX_PROTOTYPE_NEURONS = 512
MAX_PROTOTYPE_EDGES = 8192


def _check(n: int) -> None:
    if not 4 <= n <= MAX_PROTOTYPE_NEURONS:
        raise ValueError("prototype size must be 4..512")


def small_world(n: int = 64, degree: int = 4, rewire_p: float = 0.15,
                seed: int = 0) -> list[Edge]:
    """Ring where each node links to degree/2 neighbours per side, then
    each edge rewires to a random target with probability rewire_p."""
    _check(n)
    if degree < 2 or degree % 2:
        raise ValueError("degree must be even and >= 2")
    rng = random.Random(seed)
    edges: set[tuple[int, int]] = set()
    half = degree // 2
    for src in range(n):
        for offset in range(1, half + 1):
            edges.add((src, (src + offset) % n))
    rewired: set[tuple[int, int]] = set()
    for src, dst in sorted(edges):
        if rng.random() < rewire_p:
            cand = rng.randrange(n)
            if cand != src and (src, cand) not in edges:
                rewired.add((src, cand))
                continue
        rewired.add((src, dst))
    out = [(s, d, round(rng.uniform(0.3, 0.7), 4),
            rng.randint(1, 3)) for s, d in sorted(rewired)]
    return out[:MAX_PROTOTYPE_EDGES]


def layered(sizes: tuple[int, ...] = (8, 12, 12, 4),
            lateral_p: float = 0.2, seed: int = 0) -> list[Edge]:
    """Feedforward stages (full bipartite between consecutive stages)
    plus sparse inhibitory laterals inside hidden stages."""
    if not sizes or sum(sizes) > MAX_PROTOTYPE_NEURONS or min(sizes) < 1:
        raise ValueError("bad layer sizes")
    rng = random.Random(seed)
    bounds: list[tuple[int, int]] = []
    base = 0
    for size in sizes:
        bounds.append((base, base + size))
        base += size
    edges: list[Edge] = []
    for (lo_a, hi_a), (lo_b, hi_b) in zip(bounds, bounds[1:]):
        for src in range(lo_a, hi_a):
            for dst in range(lo_b, hi_b):
                edges.append((src, dst,
                              round(rng.uniform(0.3, 0.7), 4),
                              rng.randint(1, 2)))
    for lo, hi in bounds[1:-1]:
        for src in range(lo, hi):
            for dst in range(lo, hi):
                if src != dst and rng.random() < lateral_p:
                    edges.append((src, dst,
                                  round(-rng.uniform(0.1, 0.3), 4), 1))
    edges.sort()
    return edges[:MAX_PROTOTYPE_EDGES]


def hub(n: int = 64, hubs: int = 4, pool_p: float = 0.05,
        seed: int = 0) -> list[Edge]:
    """Sparse pools where `hubs` central nodes connect densely to
    everyone and pools barely connect to each other."""
    _check(n)
    if not 1 <= hubs < n:
        raise ValueError("hub count must be 1..n-1")
    rng = random.Random(seed)
    edges: set[tuple[int, int, float, int]] = set()
    for hub_id in range(hubs):
        for node in range(hubs, n):
            w = round(rng.uniform(0.3, 0.7), 4)
            edges.add((hub_id, node, w, 1))
            edges.add((node, hub_id, w, 2))
    for src in range(hubs, n):
        for dst in range(hubs, n):
            if src != dst and rng.random() < pool_p:
                edges.add((src, dst,
                           round(rng.uniform(0.2, 0.5), 4), 2))
    out = sorted(edges)
    return [(s, d, w, dl) for s, d, w, dl in out[:MAX_PROTOTYPE_EDGES]]


def build(edges: list[Edge], n: int) -> SparseLIFNetwork:
    net = SparseLIFNetwork(n, threshold=1.0, leak=0.9)
    net.connect_many(edges)
    net.compile()
    return net


def propagation_stats(edges: list[Edge], n: int, sources: list[int],
                      ticks: int = 30) -> dict[str, Any]:
    """Drive `sources` every tick; report reach, latency, spike cost."""
    started = time.perf_counter()
    net = build(edges, n)
    first_seen: dict[int, int] = {}
    for tick in range(ticks):
        fired = net.step({s: 1.5 for s in sources})
        for node in fired:
            first_seen.setdefault(node, tick)
    reached = len(first_seen)
    latency = (sum(first_seen.values()) / reached) if reached else -1.0
    return {"neurons": n, "edges": len(edges), "sources": list(sources),
            "ticks": ticks, "reached": reached,
            "reach_ratio": round(reached / n, 4),
            "mean_first_spike_tick": round(latency, 2),
            "total_spikes": int(net.total_spikes),
            "ms": round((time.perf_counter() - started) * 1000.0, 2)}


def compare(seed: int = 0) -> dict[str, Any]:
    """Run all three sketches at matched size; report side by side."""
    specs = {"small_world": (small_world(64, seed=seed), 64),
             "layered": (layered((8, 16, 16, 8, 4), seed=seed),
                         8 + 16 + 16 + 8 + 4),
             "hub": (hub(64, hubs=4, seed=seed), 64)}
    out: dict[str, Any] = {"seed": seed, "prototypes": {}}
    for name, (edges, n) in specs.items():
        sources = list(range(min(4, n)))
        out["prototypes"][name] = propagation_stats(
            edges, n, sources)
    return out


__all__ = ["small_world", "layered", "hub", "build",
           "propagation_stats", "compare"]
