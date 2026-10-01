"""Benchmarks: latency, retrieval, resources. `jarvis benchmark`."""

from __future__ import annotations

import time
from typing import Any

from .core.loop import Jarvis


def _timed(fn: Any, *args: Any, **kw: Any) -> tuple[Any, float]:
    start = time.perf_counter()
    out = fn(*args, **kw)
    return out, (time.perf_counter() - start) * 1000.0


def run(jarvis: Jarvis, samples: int = 3) -> dict[str, Any]:
    results: dict[str, Any] = {"samples": samples}
    # cycle latency (memory-backed question: no LLM involved)
    jarvis.cycle_once("remember benchmark probe alpha")
    latencies = []
    for _ in range(samples):
        result, ms = _timed(jarvis.cycle_once, "what is benchmark probe alpha?")
        latencies.append(ms)
    results["cycle_ms"] = round(sum(latencies) / len(latencies), 1)
    # memory retrieval latency
    _, search_ms = _timed(jarvis.palace.search, "benchmark probe", limit=10)
    results["memory_search_ms"] = round(search_ms, 1)
    # embed latency (hashed, local)
    from .memory.palace import embed
    _, embed_ms = _timed(embed, "benchmark probe text " * 20,
                         jarvis.config.models.embedding_dim)
    results["embed_ms"] = round(embed_ms, 2)
    # model routing latency (no generation)
    _, route_ms = _timed(jarvis.router.route, "write a function")
    results["route_ms"] = round(route_ms, 2)
    # resource footprint
    state = jarvis.world.system_state()
    results["memory"] = state.get("memory", {})
    results["disk"] = state.get("disk", {})
    results["store"] = jarvis.palace.stats()
    results["verdict"] = ("SLOW" if results["cycle_ms"] > 5000 else
                          "OK" if results["cycle_ms"] < 1000 else "WARM")
    return results
