"""Sensory encoding and motor decoding for the JARVIS neural substrate.

Deterministic adapters between typed sensory/motor structures and the
sparse spiking network. Encoders map bounded sensory features to input
currents; decoders map output spikes to typed MotorIntents. Neither side
executes anything: intents must pass PolicyEngine via the ActionRouter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .interface import (
    ALLOWED_MOTOR_ACTIONS,
    MotorIntent,
    NeuralObservation,
    SensoryEmbedding,
)


def _clamp01(value: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number != number:  # NaN guard
        return 0.0
    if number < 0.0:
        return 0.0
    if number > 1.0:
        return 1.0
    return number


@dataclass
class ChannelMap:
    """Binds named sensory features to input neuron indices."""

    features: list[str]
    base_index: int = 0

    def __post_init__(self) -> None:
        if not self.features:
            raise ValueError("ChannelMap needs at least one feature")
        if len(set(self.features)) != len(self.features):
            raise ValueError("duplicate feature names in ChannelMap")
        if self.base_index < 0:
            raise ValueError("base_index must be non-negative")

    @property
    def size(self) -> int:
        return len(self.features)

    def index_of(self, feature: str) -> int:
        try:
            return self.base_index + self.features.index(feature)
        except ValueError as exc:
            raise KeyError(f"unknown sensory feature: {feature}") from exc


@dataclass
class SensoryEncoder:
    """Deterministic encoder: feature dict -> sparse input currents.

    Each known feature contributes ``gain * normalized_value`` current to
    its mapped input neuron. Unknown features are ignored (recorded, never
    fatal) so new sensors cannot break the loop.
    """

    channel_map: ChannelMap
    gain: float = 1.2

    def __post_init__(self) -> None:
        if not 0.0 < self.gain <= 10.0:
            raise ValueError("gain must be in (0, 10]")

    def encode(self, features: Mapping[str, float]) -> dict[int, float]:
        currents: dict[int, float] = {}
        for name, raw in features.items():
            if name not in self.channel_map.features:
                continue
            currents[self.channel_map.index_of(name)] = _clamp01(raw) * self.gain
        return currents

    def encode_observation(self, obs: NeuralObservation) -> dict[int, float]:
        return self.encode(obs.features)


@dataclass
class VisualPreprocessor:
    """Coarse visual preprocessor: grids/patches -> bounded feature dict.

    Accepts a flat sequence of 0..1 brightness values (e.g. a downsampled
    patch grid from vision/ or God's Eye thumbnails) and reduces it to a
    fixed number of region-mean features. Never carries raw frames into the
    cognitive loop: only bounded region statistics cross the boundary.
    """

    regions: int = 16

    def __post_init__(self) -> None:
        if self.regions <= 0:
            raise ValueError("regions must be positive")

    def process(self, samples: list[float]) -> dict[str, float]:
        if not samples:
            return {}
        clean = [_clamp01(s) for s in samples]
        # Every sample contributes to exactly one region: distribute as
        # evenly as possible (first `extra` regions get one more sample).
        regions = min(self.regions, len(clean))
        base, extra = divmod(len(clean), regions)
        features: dict[str, float] = {}
        pos = 0
        for region in range(regions):
            size = base + (1 if region < extra else 0)
            part = clean[pos:pos + size]
            pos += size
            features[f"visual_region_{region:02d}"] = sum(part) / len(part)
        return features


@dataclass
class MotorDecoder:
    """Decodes output-layer spikes into typed MotorIntents.

    ``output_map`` binds output neuron indices (relative to the motor
    population base) to (action, confidence) templates. Only actions in the
    MotorIntent allowlist can be produced; anything else raises instead of
    emitting an untyped intent.
    """

    output_map: dict[int, tuple[str, float]]
    population_base: int = 0

    def __post_init__(self) -> None:
        for node, (action, confidence) in self.output_map.items():
            if node < 0:
                raise ValueError(f"negative output node: {node}")
            if action not in ALLOWED_MOTOR_ACTIONS:
                raise ValueError(f"motor action not in allowlist: {action}")
            if not 0.0 <= float(confidence) <= 1.0:
                raise ValueError(f"confidence out of range for {action}")

    def decode(self, fired_absolute: list[int], tick: int = 0) -> list[MotorIntent]:
        intents: list[MotorIntent] = []
        for node in fired_absolute:
            relative = node - self.population_base
            if relative not in self.output_map:
                continue
            action, confidence = self.output_map[relative]
            intents.append(MotorIntent(
                action=action,
                confidence=float(confidence),
                strength=float(confidence),
                provenance={"source": "neural", "tick": tick},
            ))
        return intents


def default_sensor_features() -> list[str]:
    """Stable default feature vocabulary for the encoder."""
    names = [f"visual_region_{i:02d}" for i in range(16)]
    names += ["audio_level", "audio_change", "novelty", "urgency",
              "user_present", "goal_progress", "anomaly", "change_rate"]
    return names


@dataclass
class CodecReport:
    encoded_channels: int = 0
    ignored_features: int = 0
    decoded_intents: int = 0
    detail: dict[str, Any] = field(default_factory=dict)
