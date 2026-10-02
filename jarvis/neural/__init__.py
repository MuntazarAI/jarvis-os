"""Bio-inspired neural nervous system for JARVIS.

This package is an optional event-driven intelligence substrate. It does not
replace the cognitive/LLM stack; it provides temporal, recurrent and
plastic dynamics that can consume sensor events and emit bounded motor events.
"""

from .core import LIFNeuron, SpikingNetwork, Synapse
from .system import NeuralNervousSystem

__all__ = ["LIFNeuron", "Synapse", "SpikingNetwork", "NeuralNervousSystem"]
