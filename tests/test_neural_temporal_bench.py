"""Temporal SNN benchmark tests (#23).

Deterministic (seeded stdlib only): the 3-neuron spiking coincidence
detector scores 1.0 while the non-spiking baselines trail. Fast (<1s).
"""

from __future__ import annotations

from jarvis.neural.temporal_bench import (
    accuracy,
    baseline_instant,
    baseline_moving_average,
    make_trials,
    run_benchmark,
    snn_predict,
    build_coincidence_detector,
)


def test_trials_deterministic_and_balanced():
    first = make_trials(seed=7, n=60)
    assert first == make_trials(seed=7, n=60)
    assert first != make_trials(seed=8, n=60)
    labels = [t["label"] for t in first]
    assert sum(labels) == 30  # alternating construction


def test_snn_solves_coincidence():
    result = run_benchmark(seed=7, n=60)
    assert result["snn_accuracy"] == 1.0
    assert result["instant_accuracy"] < result["snn_accuracy"]
    assert result["moving_average_accuracy"] < result["snn_accuracy"]
    assert result["snn_accuracy"] >= 0.95


def test_snn_generalizes_across_seeds():
    for seed in (1, 99, 1234):
        result = run_benchmark(seed=seed, n=120)
        assert result["snn_accuracy"] == 1.0, seed
        assert result["moving_average_accuracy"] < 1.0, seed


def test_single_trial_predictions():
    net = build_coincidence_detector()
    assert snn_predict(net, 5, 5) == 1  # exact coincidence
    assert snn_predict(net, 5, 7) == 1  # window edge
    assert snn_predict(net, 5, 10) == 0  # separated
    assert snn_predict(net, 10, 5) == 0  # order independent


def test_benchmark_fast_and_reports_spikes():
    result = run_benchmark(seed=7, n=60)
    assert result["snn_ms"] < 1000.0
    assert result["snn_spikes"] > 0
    assert accuracy([], []) == 0.0
