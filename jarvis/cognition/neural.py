"""Bounded neural learning signal (4.4 experiment).

Feeds experience features through the existing deterministic spiking
substrate and returns a small adaptive nudge. This is explicitly an
experiment, not a brain:

- fixed 32-neuron network, fixed seed, fixed edges (no training,
  no plasticity, no RNG in the step path);
- input: a fixed 8-feature vector (outcome, confidence, evidence,
  reliability, staleness, novelty, ambiguity, verification);
- output: spike activity mapped to a bounded [-0.03, +0.03]
  confidence adjustment plus the raw counts for inspection;
- deterministic: same features always give the same signal;
- fallback: when the neural substrate is unavailable, the signal is
  exactly 0.0 with ``available: False`` (learning proceeds without it).

A comparison benchmark (4.2 tests + report) measures whether the
signal improves calibration or not. If it does not, it stays optional.
"""

from __future__ import annotations

from typing import Any

NETWORK_SIZE = 32
NETWORK_SEED = 7
SIGNAL_CAP = 0.03

_FEATURES = (
    "outcome_ok",
    "confidence",
    "evidence",
    "reliability",
    "freshness",
    "novelty",
    "ambiguity",
    "verified",
)


def feature_vector(outcome_ok: bool, confidence: float,
                   evidence_count: int, reliability: float,
                   fresh: bool, novel: bool, ambiguous: bool,
                   verified: bool) -> dict[str, float]:
    """Fixed 8-feature encoding in 0..1. Pure function."""
    clamp = lambda v: max(0.0, min(1.0, float(v)))
    return {
        "outcome_ok": 1.0 if outcome_ok else 0.0,
        "confidence": clamp(confidence),
        "evidence": clamp(evidence_count / 5.0),
        "reliability": clamp(reliability),
        "freshness": 1.0 if fresh else 0.0,
        "novelty": 1.0 if novel else 0.0,
        "ambiguity": 1.0 if ambiguous else 0.0,
        "verified": 1.0 if verified else 0.0,
    }


class NeuralSignal:
    """Deterministic spiking read-out. No training, ever."""

    def __init__(self, *, size: int = NETWORK_SIZE,
                 seed: int = NETWORK_SEED) -> None:
        self.size = size
        self.seed = seed
        self.available = False
        self._network = None
        self._calls = 0
        try:
            from ..neural.scale import SparseLIFNetwork
            from ..neural.codec import ChannelMap, SensoryEncoder
            network = SparseLIFNetwork(size)
            import random
            rng = random.Random(seed)
            for _ in range(size * 3):
                network.stage_edge(rng.randrange(size),
                                   rng.randrange(size),
                                   rng.uniform(0.2, 0.8),
                                   rng.randrange(1, 4))
            network.compile()
            features = [f"exp_{name}" for name in _FEATURES]
            encoder = SensoryEncoder(ChannelMap(features))
            self._network = (network, encoder)
            self.available = True
        except Exception:
            self._network = None
            self.available = False

    def compute(self, features: dict[str, float]) -> dict[str, Any]:
        """Map features to a bounded adjustment. Deterministic."""
        self._calls += 1
        if not self.available or self._network is None:
            return {"signal": 0.0, "spikes": 0, "available": False,
                    "calls": self._calls}
        network, encoder = self._network
        try:
            currents = encoder.encode(
                {f"exp_{k}": v for k, v in features.items()
                 if k in _FEATURES})
            fired = network.step(currents)
            activity = len(fired) / max(1, self.size)
            # Signed nudge: successful outcomes excite, failures inhibit,
            # scaled by activity so quiet networks change nothing.
            direction = 1.0 if features.get("outcome_ok", 0.0) >= 0.5 \
                else -1.0
            signal = max(-SIGNAL_CAP, min(
                SIGNAL_CAP, direction * activity * SIGNAL_CAP * 4.0))
            return {"signal": round(signal, 5), "spikes": len(fired),
                    "available": True, "calls": self._calls}
        except Exception:
            return {"signal": 0.0, "spikes": 0, "available": True,
                    "calls": self._calls, "error": "step failed"}

    def adjust(self, confidence: float, signal: float) -> float:
        """Apply a bounded nudge, clamped to [0.05, 0.95]. Never NaN."""
        try:
            value = float(confidence) + float(signal)
        except (TypeError, ValueError):
            return confidence
        if value != value:  # NaN guard
            return confidence
        return max(0.05, min(0.95, value))

    def status(self) -> dict[str, Any]:
        return {"available": self.available, "size": self.size,
                "seed": self.seed, "calls": self._calls}


__all__ = ["NeuralSignal", "feature_vector"]
