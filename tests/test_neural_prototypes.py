"""Connectome-inspired topology prototype tests (#24).

Deterministic structural sketches only: same seed gives identical
edges; sizes/edges bounded; every sketch propagates spikes; invalid
inputs rejected. No biological claims anywhere.
"""

from __future__ import annotations

import pytest

from jarvis.neural.prototypes import (
    build,
    compare,
    hub,
    layered,
    propagation_stats,
    small_world,
)


def test_prototypes_deterministic():
    assert small_world(64, seed=3) == small_world(64, seed=3)
    assert layered(seed=3) == layered(seed=3)
    assert hub(64, seed=3) == hub(64, seed=3)
    assert small_world(64, seed=3) != small_world(64, seed=4)


def test_prototypes_bounded_and_valid():
    for edges, n in ((small_world(64), 64), (layered(), 52),
                     (hub(64), 64)):
        assert len(edges) <= 8192
        for src, dst, weight, delay in edges:
            assert 0 <= src < n and 0 <= dst < n
            assert -1.0 <= weight <= 1.0
            assert 1 <= delay <= 32
        net = build(edges, n)  # compiles without error
        assert net.size == n


def test_prototypes_propagate():
    assert propagation_stats(
        small_world(32), 32, [0, 1])["reached"] > 0
    assert propagation_stats(
        layered((4, 8, 4)), 16, [0])["reached"] > 0
    assert propagation_stats(hub(32), 32, [0])["reached"] > 0


def test_compare_reports_all_three():
    result = compare(seed=0)
    assert sorted(result["prototypes"]) == ["hub", "layered",
                                            "small_world"]
    for stats in result["prototypes"].values():
        assert 0.0 <= stats["reach_ratio"] <= 1.0
        assert stats["total_spikes"] >= 0
        assert stats["ms"] >= 0.0


def test_invalid_inputs_rejected():
    with pytest.raises(ValueError):
        small_world(2)
    with pytest.raises(ValueError):
        small_world(64, degree=3)
    with pytest.raises(ValueError):
        layered(())
    with pytest.raises(ValueError):
        hub(64, hubs=0)
    with pytest.raises(ValueError):
        hub(8, hubs=8)
