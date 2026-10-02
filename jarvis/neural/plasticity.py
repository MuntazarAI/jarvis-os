"""Bounded learning rules for the JARVIS neural substrate."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class STDPRule:
    """Pair-based spike-timing-dependent plasticity.

    The rule is deliberately bounded: neural plasticity can alter a connection
    but cannot bypass JARVIS policy or directly execute an external action.
    """

    potentiation: float = 0.02
    depression: float = 0.025
    window: int = 20
    min_weight: float = -2.0
    max_weight: float = 2.0

    def update(self, weight: float, pre_time: int, post_time: int) -> float:
        delta = post_time - pre_time
        if abs(delta) > self.window or delta == 0:
            return max(self.min_weight, min(self.max_weight, weight))
        amount = self.potentiation if delta > 0 else -self.depression
        return max(self.min_weight, min(self.max_weight, weight + amount))


@dataclass
class HomeostaticPlasticity:
    """Slowly nudges neurons toward a target firing rate."""

    target_rate: float = 0.05
    learning_rate: float = 0.01
    min_threshold: float = 0.1
    max_threshold: float = 5.0

    def update_threshold(self, threshold: float, observed_rate: float) -> float:
        error = observed_rate - self.target_rate
        updated = threshold + self.learning_rate * error
        return max(self.min_threshold, min(self.max_threshold, updated))


def exponential_decay(value: float, tau: float, dt: float = 1.0) -> float:
    """Decay a trace by one time step."""
    if tau <= 0:
        raise ValueError("tau must be positive")
    return value * exp(-dt / tau)
