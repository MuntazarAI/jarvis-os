"""Temporal benchmark: spiking coincidence detector vs baselines (#23).

Task: two input pulses arrive at times t_a, t_b. Label = 1 iff the
pulses are coincident (|t_a - t_b| <= WINDOW). A spiking network with
synaptic delays + leak solves this with 3 neurons; the baselines show
what you lose without spikes/time:

- instant: memoryless threshold on the current tick only (misses
  near-misses inside the window).
- moving_average: mean input over the last W ticks (catches clusters
  but false-alarms on dense non-coincident barrages).

Deterministic under a fixed seed (stdlib random only). No claims
beyond the measured numbers.
"""

from __future__ import annotations

import random
import time
from typing import Any

from .scale import SparseLIFNetwork

WINDOW = 2
GAP_LO = 4
GAP_HI = 8
HORIZON = 24
PULSE = 1.0


def make_trials(seed: int = 7, n: int = 60) -> list[dict[str, Any]]:
    """Half coincident (|dt| <= WINDOW), half separated (GAP_LO..GAP_HI)."""
    rng = random.Random(seed)
    trials: list[dict[str, Any]] = []
    for i in range(n):
        coincident = (i % 2 == 0)
        t_a = rng.randint(2, HORIZON - GAP_HI - 2)
        if coincident:
            t_b = t_a + rng.randint(-WINDOW, WINDOW)
        else:
            gap = rng.randint(GAP_LO, GAP_HI)
            t_b = t_a + gap * rng.choice((-1, 1))
            t_b = max(0, min(HORIZON - 1, t_b))
        trials.append({"t_a": t_a, "t_b": t_b,
                       "label": 1 if abs(t_a - t_b) <= WINDOW else 0})
    return trials


def build_coincidence_detector() -> SparseLIFNetwork:
    """3-neuron SNN: relays 0,1 -> output 2 (delay 1, w 2/3, threshold
    1.0, leak 0.75). Coincident arrivals (|dt| <= 2) sum past threshold;
    separated pulses (gap >= 4) decay below it."""
    net = SparseLIFNetwork(3, threshold=1.0, leak=0.75)
    net.stage_edge(0, 2, 2.0 / 3.0, 1)
    net.stage_edge(1, 2, 2.0 / 3.0, 1)
    net.compile()
    return net


def snn_predict(net: SparseLIFNetwork, t_a: int, t_b: int) -> int:
    net.reset()
    fired_out = False
    for tick in range(HORIZON):
        inputs: dict[int, float] = {}
        if tick == t_a:
            inputs[0] = PULSE
        if tick == t_b:
            inputs[1] = PULSE
        # Direct drive: relays pass pulses through (threshold crossed
        # by the pulse itself), output integrates delayed arrivals.
        if tick in (t_a, t_b):
            fired = net.step({0: PULSE} if tick == t_a and tick != t_b
                             else {1: PULSE} if tick == t_b and tick != t_a
                             else {0: PULSE, 1: PULSE})
        else:
            fired = net.step(inputs)
        if 2 in fired:
            fired_out = True
    return 1 if fired_out else 0


def baseline_instant(trials: list[dict[str, Any]]) -> list[int]:
    """Memoryless: fires only when both pulses share a tick."""
    return [1 if t["t_a"] == t["t_b"] else 0 for t in trials]


def baseline_moving_average(trials: list[dict[str, Any]],
                            width: int = 5,
                            threshold: float = 0.3) -> list[int]:
    """Rate window: fires when recent pulse density is high. Catches
    clusters but false-alarms on dense non-coincident barrages."""
    out = []
    for t in trials:
        signal = [0.0] * HORIZON
        signal[t["t_a"]] += 1.0
        signal[t["t_b"]] += 1.0
        hit = 0
        for tick in range(HORIZON):
            window = signal[max(0, tick - width + 1):tick + 1]
            if sum(window) / width >= threshold:
                hit = 1
                break
        out.append(hit)
    return out


def accuracy(predicted: list[int], trials: list[dict[str, Any]]) -> float:
    if not trials:
        return 0.0
    hits = sum(1 for p, t in zip(predicted, trials)
               if p == t["label"])
    return hits / len(trials)


def run_benchmark(seed: int = 7, n: int = 60) -> dict[str, Any]:
    trials = make_trials(seed=seed, n=n)
    net = build_coincidence_detector()
    started = time.perf_counter()
    snn_preds = [snn_predict(net, t["t_a"], t["t_b"]) for t in trials]
    snn_ms = (time.perf_counter() - started) * 1000.0
    total_spikes = 0
    probe = build_coincidence_detector()
    for t in trials:
        snn_predict(probe, t["t_a"], t["t_b"])
        total_spikes += probe.total_spikes
        probe.reset()
        probe._queue.clear()
    return {
        "seed": seed, "trials": n, "window": WINDOW,
        "snn_accuracy": round(accuracy(snn_preds, trials), 4),
        "instant_accuracy": round(
            accuracy(baseline_instant(trials), trials), 4),
        "moving_average_accuracy": round(
            accuracy(baseline_moving_average(trials), trials), 4),
        "snn_spikes": total_spikes,
        "snn_ms": round(snn_ms, 2),
    }


__all__ = ["make_trials", "build_coincidence_detector", "snn_predict",
           "baseline_instant", "baseline_moving_average", "accuracy",
           "run_benchmark", "WINDOW"]
