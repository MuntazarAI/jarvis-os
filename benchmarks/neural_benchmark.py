"""Deterministic microbenchmark for the JARVIS neural foundation."""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

from jarvis.neural.core import SpikingNetwork


def run(size: int, steps: int, repeats: int) -> dict[str, float | int]:
    samples = []
    for _ in range(repeats):
        network = SpikingNetwork(size)
        start = time.perf_counter()
        for step in range(steps):
            network.step({step % size: 1.1})
        samples.append(time.perf_counter() - start)
    median = statistics.median(samples)
    return {
        "neurons": size,
        "steps": steps,
        "repeats": repeats,
        "median_seconds": median,
        "min_seconds": min(samples),
        "max_seconds": max(samples),
        "steps_per_second": steps / median,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--size", type=int, default=1000)
    parser.add_argument("--steps", type=int, default=1000)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", default="benchmark-results/neural.json")
    args = parser.parse_args()
    result = run(args.size, args.steps, args.repeats)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
