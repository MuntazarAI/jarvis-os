"""Bio-inspired neural nervous system for JARVIS.

This package is an optional event-driven intelligence substrate. It does not
replace the cognitive/LLM stack; it provides temporal, recurrent and
plastic dynamics that can consume sensor events and emit bounded motor events.

PyTorch integration provides hybrid neuro-symbolic architectures combining
deterministic spiking neural networks with gradient-based deep learning.
"""

from .core import LIFNeuron, SpikingNetwork, Synapse
from .system import NeuralNervousSystem
from .fly_brain import (
    FlyBrainNetwork,
    FlyBrainInput,
    FlyBrainOutput,
    FlyBrainState,
    build_fly_brain_network,
    get_fly_brain,
    fly_brain_status,
    fly_brain_step,
)

# PyTorch Integration (optional - requires torch extra)
try:
    from .torch_integration import (
        TorchSNNConfig,
        TorchDeviceManager,
        PolicyGatedTorchModule,
        SNNTorchEncoder,
        TorchSNNDecoder,
        HybridSNNPolicyNetwork,
        ModelRegistryEntry,
        TorchModelRegistry,
        TrainingConfig,
        PolicyGatedTrainer,
        TorchInferenceEngine,
        snn_to_torch_dataset,
        torch_to_snn_weights,
        create_example_hybrid_network,
    )
    _TORCH_AVAILABLE = True
except ImportError:
    _TORCH_AVAILABLE = False

__all__ = [
    "LIFNeuron",
    "Synapse",
    "SpikingNetwork",
    "NeuralNervousSystem",
    "FlyBrainNetwork",
    "FlyBrainInput",
    "FlyBrainOutput",
    "FlyBrainState",
    "build_fly_brain_network",
    "get_fly_brain",
    "fly_brain_status",
    "fly_brain_step",
]

if _TORCH_AVAILABLE:
    __all__.extend([
        "TorchSNNConfig",
        "TorchDeviceManager",
        "PolicyGatedTorchModule",
        "SNNTorchEncoder",
        "TorchSNNDecoder",
        "HybridSNNPolicyNetwork",
        "ModelRegistryEntry",
        "TorchModelRegistry",
        "TrainingConfig",
        "PolicyGatedTrainer",
        "TorchInferenceEngine",
        "snn_to_torch_dataset",
        "torch_to_snn_weights",
        "create_example_hybrid_network",
    ])

def torch_available() -> bool:
    """Check if PyTorch integration is available."""
    return _TORCH_AVAILABLE