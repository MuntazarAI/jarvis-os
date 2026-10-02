"""Typed neural ↔ cognitive interfaces.

The spiking substrate NEVER executes actions. It produces bounded typed
signals; the cognitive loop (and ultimately PolicyEngine) decides what, if
anything, happens. All signals carry provenance and confidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class NeuralObservation:
    """What the network saw, in cognitive terms."""

    summary: str
    active_populations: dict[str, int] = field(default_factory=dict)
    total_spikes: int = 0
    novelty: float = 0.0
    confidence: float = 0.5
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass
class NeuralState:
    """Observable network state snapshot reference."""

    time: int
    neurons: int
    synapses: int
    total_spikes: int
    mean_rate: float
    saturated: bool = False
    silent: bool = False


@dataclass
class NeuralIntent:
    """A bounded decision signal from the network (not an action)."""

    kind: str  # attend | approach | avoid | select | signal | none
    strength: float = 0.0
    target: str = ""
    confidence: float = 0.5
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in ("attend", "approach", "avoid", "select", "signal", "none"):
            raise ValueError(f"unknown neural intent kind: {self.kind!r}")
        self.strength = max(0.0, min(1.0, float(self.strength)))
        self.confidence = max(0.0, min(1.0, float(self.confidence)))


@dataclass
class SensoryEmbedding:
    """Encoded sensory input ready for injection into input populations."""

    currents: dict[int, float] = field(default_factory=dict)
    source: str = ""
    encoding: str = "rate"  # rate | onehot | graded
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass
class MotorIntent:
    """Abstract motor output. NEVER executes anything by itself.

    Flow: MotorIntent → PolicyEngine.evaluate → ActionRouter → real action.
    """

    action: str  # MOVE | TURN | LOOK | FOCUS | ATTEND | APPROACH | AVOID | SELECT | SIGNAL
    parameters: dict[str, Any] = field(default_factory=dict)
    strength: float = 0.0
    confidence: float = 0.5
    provenance: dict[str, Any] = field(default_factory=dict)

    ALLOWED = frozenset({"MOVE", "TURN", "LOOK", "FOCUS", "ATTEND",
                         "APPROACH", "AVOID", "SELECT", "SIGNAL"})

    def __post_init__(self) -> None:
        if self.action not in self.ALLOWED:
            raise ValueError(f"motor action not in allowlist: {self.action!r}")
        self.strength = max(0.0, min(1.0, float(self.strength)))
        self.confidence = max(0.0, min(1.0, float(self.confidence)))

    def to_dict(self) -> dict[str, Any]:
        return {"action": self.action, "parameters": dict(self.parameters),
                "strength": self.strength, "confidence": self.confidence}


ALLOWED_MOTOR_ACTIONS = MotorIntent.ALLOWED


@dataclass
class AttentionSignal:
    population: str
    salience: float
    reason: str = ""
    confidence: float = 0.5


@dataclass
class NoveltySignal:
    score: float  # 0..1, 1 == completely novel
    signature: str = ""
    confidence: float = 0.5


@dataclass
class ConfidenceSignal:
    value: float  # 0..1
    basis: str = ""
