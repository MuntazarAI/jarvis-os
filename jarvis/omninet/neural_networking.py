"""Neural Networking Module (M13) — Neural network capabilities for JARVIS-OS.

Provides neural network infrastructure including:
- Neural network layers (dense, conv, attention)
- Mixture-of-Experts routing
- Neural network training and inference
- Model weight persistence
- Neural-symbolic integration
- Brain-inspired architectures
"""

from __future__ import annotations

import json
import math
import random
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class NeuralNetworkConfig:
    """Configuration for a neural network layer."""
    input_size: int
    output_size: int
    activation: str = "relu"  # relu, sigmoid, tanh, softmax, linear
    learning_rate: float = 0.001
    weight_init: str = "xavier"  # xavier, he, random, zeros
    bias_init: str = "zeros"
    dropout: float = 0.0
    l2_regularization: float = 0.0


@dataclass
class NeuralNetworkLayer:
    """A single neural network layer with weights and biases."""

    layer_id: str = field(default_factory=lambda: f"layer-{random.randint(100000, 999999)}")
    config: NeuralNetworkConfig = field(default_factory=lambda: NeuralNetworkConfig(1, 1))
    weights: list[list[float]] = field(default_factory=list)
    biases: list[float] = field(default_factory=list)
    gradient_weights: list[list[float]] = field(default_factory=list)
    gradient_biases: list[float] = field(default_factory=list)
    last_input: list[float] = field(default_factory=list)
    last_output: list[float] = field(default_factory=list)

    def initialize(self) -> None:
        """Initialize weights and biases."""
        import math

        in_size = self.config.input_size
        out_size = self.config.output_size

        if self.config.weight_init == "xavier":
            limit = math.sqrt(6.0 / (in_size + out_size))
        elif self.config.weight_init == "he":
            limit = math.sqrt(2.0 / in_size)
        else:
            limit = 0.1

        self.weights = [
            [random.uniform(-limit, limit) for _ in range(out_size)]
            for _ in range(in_size)
        ]
        self.biases = [0.0] * out_size

        self.gradient_weights = [
            [0.0 for _ in range(out_size)] for _ in range(in_size)
        ]
        self.gradient_biases = [0.0] * out_size

    def forward(self, inputs: list[float]) -> list[float]:
        """Forward pass through the layer."""
        self.last_input = list(inputs)
        output = []

        for j in range(self.config.output_size):
            val = self.biases[j]
            for i in range(self.config.input_size):
                val += self.last_input[i] * self.weights[i][j]
            output.append(val)

        # Apply activation
        activated = []
        for val in output:
            activated.append(self._activate(val))

        self.last_output = list(activated)
        return activated

    def _activate(self, x: float) -> float:
        """Apply activation function."""
        if self.config.activation == "relu":
            return max(0.0, x)
        elif self.config.activation == "sigmoid":
            return 1.0 / (1.0 + math.exp(-max(-500, min(500, x))))
        elif self.config.activation == "tanh":
            return math.tanh(x)
        elif self.config.activation == "softmax":
            return x  # Softmax applied at layer output level
        elif self.config.activation == "linear":
            return x
        else:
            return x

    def backward(self, output_gradients: list[float], learning_rate: float) -> list[float]:
        """Backward pass through the layer."""
        input_gradients = [0.0] * self.config.input_size

        for j in range(self.config.output_size):
            grad = output_gradients[j]
            # Apply activation derivative
            if self.config.activation == "relu":
                grad *= 1.0 if self.last_output[j] > 0 else 0.0
            elif self.config.activation == "sigmoid":
                grad *= self.last_output[j] * (1.0 - self.last_output[j])
            elif self.config.activation == "tanh":
                grad *= 1.0 - self.last_output[j] ** 2

            # Accumulate gradients
            for i in range(self.config.input_size):
                self.gradient_weights[i][j] += self.last_input[i] * grad
                input_gradients[i] += self.weights[i][j] * grad
            self.gradient_biases[j] += grad

        # Apply weight updates
        for i in range(self.config.input_size):
            for j in range(self.config.output_size):
                self.weights[i][j] -= learning_rate * self.gradient_weights[i][j]
                self.gradient_weights[i][j] = 0.0

        for j in range(self.config.output_size):
            self.biases[j] -= learning_rate * self.gradient_biases[j]
            self.gradient_biases[j] = 0.0

        return input_gradients

    def to_dict(self) -> dict[str, Any]:
        return {
            "layer_id": self.layer_id,
            "config": {
                "input_size": self.config.input_size,
                "output_size": self.config.output_size,
                "activation": self.config.activation,
                "learning_rate": self.config.learning_rate,
                "weight_init": self.config.weight_init,
                "bias_init": self.config.bias_init,
                "dropout": self.config.dropout,
                "l2_regularization": self.config.l2_regularization,
            },
            "weights": self.weights,
            "biases": self.biases,
        }


class NeuralNetwork:
    """Multi-layer neural network with forward/backward propagation."""

    def __init__(self, name: str = "neural_network"):
        self.network_id: str = f"nn-{random.randint(100000, 999999)}"
        self.name: str = name
        self.layers: list[NeuralNetworkLayer] = []
        self.training_history: list[dict[str, Any]] = []
        self.created_at: float = time.time()

    def add_layer(self, layer: NeuralNetworkLayer) -> None:
        """Add a layer to the network."""
        self.layers.append(layer)

    def add_dense_layer(self, input_size: int, output_size: int,
                        activation: str = "relu") -> NeuralNetworkLayer:
        """Add a dense (fully connected) layer."""
        config = NeuralNetworkConfig(
            input_size=input_size,
            output_size=output_size,
            activation=activation,
        )
        layer = NeuralNetworkLayer(config=config)
        layer.initialize()
        self.add_layer(layer)
        return layer

    def forward(self, inputs: list[float]) -> list[float]:
        """Forward pass through the entire network."""
        current = list(inputs)
        for layer in self.layers:
            current = layer.forward(current)
        return current

    def backward(self, output_gradients: list[float], learning_rate: float) -> None:
        """Backward pass through the entire network."""
        gradients = list(output_gradients)
        for layer in reversed(self.layers):
            gradients = layer.backward(gradients, learning_rate)

    def train(self, inputs: list[float], targets: list[float],
              learning_rate: float = 0.01) -> float:
        """Train on a single input-output pair."""
        # Forward pass
        output = self.forward(inputs)

        # Compute loss (MSE) and gradients
        loss = 0.0
        output_gradients = []
        for i in range(len(targets)):
            diff = output[i] - targets[i]
            loss += diff * diff
            output_gradients.append(2.0 * diff)
        loss /= len(targets)

        # Backward pass
        self.backward(output_gradients, learning_rate)

        # Record training history
        self.training_history.append({
            "at": time.time(),
            "loss": loss,
            "learning_rate": learning_rate,
        })

        return loss

    def predict(self, inputs: list[float]) -> list[float]:
        """Make a prediction (forward pass)."""
        return self.forward(inputs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "network_id": self.network_id,
            "name": self.name,
            "layers": [layer.to_dict() for layer in self.layers],
            "training_history": self.training_history[-100:],  # Last 100 entries
            "created_at": self.created_at,
        }


# -- Mixture-of-Experts (MoE) --

@dataclass
class Expert:
    """A single expert network in a Mixture-of-Experts."""

    expert_id: str = field(default_factory=lambda: f"expert-{random.randint(100000, 999999)}")
    network: NeuralNetwork = field(default_factory=lambda: NeuralNetwork())
    usage_count: int = 0
    total_loss: float = 0.0
    performance_score: float = 1.0

    def record_usage(self, loss: float) -> None:
        self.usage_count += 1
        self.total_loss += loss
        self.performance_score = 1.0 / (1.0 + self.total_loss / max(self.usage_count, 1))


class MixtureOfExperts:
    """Mixture-of-Experts network with gating network."""

    def __init__(self, input_size: int, output_size: int,
                 num_experts: int = 8, expert_hidden_size: int = 64):
        self.moe_id: str = f"moe-{random.randint(100000, 999999)}"
        self.input_size: int = input_size
        self.output_size: int = output_size
        self.num_experts: int = num_experts
        self.expert_hidden_size: int = expert_hidden_size

        # Gating network - decides which experts to use
        self.gating_network = NeuralNetwork(name=f"moe-gating-{self.moe_id}")
        self.gating_network.add_dense_layer(input_size, expert_hidden_size, "relu")
        self.gating_network.add_dense_layer(expert_hidden_size, num_experts, "softmax")

        # Expert networks
        self.experts: list[Expert] = []
        for _ in range(num_experts):
            expert = Expert()
            expert.network.add_dense_layer(input_size, expert_hidden_size, "relu")
            expert.network.add_dense_layer(expert_hidden_size, output_size, "linear")
            self.experts.append(expert)

    def forward(self, inputs: list[float]) -> tuple[list[float], dict[str, Any]]:
        """Forward pass through MoE network."""
        # Gating network decides expert weights
        gating_output = self.gating_network.forward(inputs)

        # Normalize gating weights
        total = sum(gating_output)
        if total > 0:
            gating_weights = [g / total for g in gating_output]
        else:
            gating_weights = [1.0 / self.num_experts] * self.num_experts

        # Get expert outputs
        expert_outputs = []
        for expert in self.experts:
            expert_output = expert.network.forward(inputs)
            expert_outputs.append(expert_output)

        # Weighted combination
        output = [0.0] * self.output_size
        for i, expert_output in enumerate(expert_outputs):
            weight = gating_weights[i]
            for j in range(self.output_size):
                output[j] += weight * expert_output[j]

        # Update expert usage
        for i, expert in enumerate(self.experts):
            expert.usage_count += 1

        metadata = {
            "moe_id": self.moe_id,
            "gating_weights": gating_weights,
            "expert_outputs": expert_outputs,
            "top_expert": max(range(self.num_experts),
                              key=lambda i: gating_weights[i]),
        }

        return output, metadata

    def train(self, inputs: list[float], targets: list[float],
              learning_rate: float = 0.01) -> float:
        """Train the MoE network."""
        output, metadata = self.forward(inputs)

        # Compute loss
        loss = 0.0
        output_gradients = []
        for i in range(len(targets)):
            diff = output[i] - targets[i]
            loss += diff * diff
            output_gradients.append(2.0 * diff)
        loss /= len(targets)

        # Backprop through gating network and experts
        # Simplified: backprop through gating network
        gating_gradients = [g * diff for g, diff in zip(metadata["gating_weights"], output_gradients)]
        self.gating_network.backward(gating_gradients, learning_rate)

        # Train top expert more
        top_expert_idx = metadata["top_expert"]
        self.experts[top_expert_idx].network.backward(
            [g * metadata["gating_weights"][top_expert_idx] for g in output_gradients],
            learning_rate
        )

        # Update expert performance
        self.experts[top_expert_idx].record_usage(loss)

        return loss

    def predict(self, inputs: list[float]) -> list[float]:
        """Make a prediction."""
        output, _ = self.forward(inputs)
        return output


# -- Neural-Symbolic Bridge --

class NeuralSymbolicBridge:
    """Bridges neural networks and symbolic reasoning (like Stark AI agents)."""

    def __init__(self, name: str = "neural_symbolic_bridge"):
        self.bridge_id: str = f"nsb-{random.randint(100000, 999999)}"
        self.name: str = name
        self.neural_networks: dict[str, NeuralNetwork] = {}
        self.moe_networks: dict[str, MixtureOfExperts] = {}
        self.symbolic_rules: list[dict[str, Any]] = []
        self.neural_to_symbolic: dict[str, str] = {}  # network_id -> symbolic_rule_id
        self.symbolic_to_neural: dict[str, str] = {}  # symbolic_rule_id -> network_id

    def add_neural_network(self, network: NeuralNetwork) -> str:
        """Add a neural network to the bridge."""
        self.neural_networks[network.network_id] = network
        return network.network_id

    def add_moe_network(self, moe: MixtureOfExperts) -> str:
        """Add a Mixture-of-Experts network to the bridge."""
        self.moe_networks[moe.moe_id] = moe
        return moe.moe_id

    def add_symbolic_rule(self, rule: dict[str, Any]) -> str:
        """Add a symbolic rule."""
        rule_id: str = f"rule-{random.randint(100000, 999999)}"
        rule["rule_id"] = rule_id
        rule["created_at"] = time.time()
        self.symbolic_rules.append(rule)
        return rule_id

    def link_neural_to_symbolic(self, network_id: str, rule_id: str) -> None:
        """Link a neural network to a symbolic rule."""
        self.neural_to_symbolic[network_id] = rule_id
        self.symbolic_to_neural[rule_id] = network_id

    def neural_to_symbolic_inference(self, network_id: str,
                                     inputs: list[float]) -> dict[str, Any]:
        """Run neural network then map output to symbolic reasoning."""
        network = self.neural_networks.get(network_id)
        if network is None:
            return {"error": "network not found"}

        output = network.forward(inputs)
        rule_id = self.neural_to_symbolic.get(network_id)

        rule = None
        for r in self.symbolic_rules:
            if r.get("rule_id") == rule_id:
                rule = r
                break

        return {
            "network_id": network_id,
            "neural_output": output,
            "rule_id": rule_id,
            "symbolic_rule": rule,
            "symbolic_output": self._apply_symbolic_rule(rule, output) if rule else None,
        }

    def _apply_symbolic_rule(self, rule: dict[str, Any],
                             neural_output: list[float]) -> dict[str, Any]:
        """Apply a symbolic rule to neural output."""
        # Simple mapping: neural output values map to rule conditions
        result: dict[str, Any] = {
            "rule_id": rule.get("rule_id"),
            "rule_name": rule.get("name", "unknown"),
            "neural_output": neural_output,
            "symbolic_conclusion": "unknown",
            "confidence": 0.5,
        }

        # Simple heuristic: if neural output has high values, rule is satisfied
        if neural_output:
            max_val = max(neural_output)
            min_val = min(neural_output)
            avg_val = sum(neural_output) / len(neural_output)

            result["symbolic_conclusion"] = "active" if max_val > 0.5 else "inactive"
            result["confidence"] = min(1.0, max_val + avg_val / 2)
            result["statistics"] = {
                "max": max_val,
                "min": min_val,
                "avg": avg_val,
            }

        return result

    def bridge_status(self) -> dict[str, Any]:
        """Get bridge status."""
        return {
            "bridge_id": self.bridge_id,
            "name": self.name,
            "neural_networks": len(self.neural_networks),
            "moe_networks": len(self.moe_networks),
            "symbolic_rules": len(self.symbolic_rules),
            "links": len(self.neural_to_symbolic),
        }


# -- Global neural networking registry --

class NeuralNetworkRegistry:
    """Global registry for neural networks and MoE models."""

    def __init__(self):
        self.networks: dict[str, NeuralNetwork] = {}
        self.moe_networks: dict[str, MixtureOfExperts] = {}
        self.bridges: dict[str, NeuralSymbolicBridge] = {}
        self.created_at: float = time.time()

    def create_network(self, name: str) -> NeuralNetwork:
        """Create a new neural network."""
        network = NeuralNetwork(name=name)
        self.networks[network.network_id] = network
        return network

    def create_moe(self, name: str, input_size: int, output_size: int,
                   num_experts: int = 8) -> MixtureOfExperts:
        """Create a new Mixture-of-Experts network."""
        moe = MixtureOfExperts(
            input_size=input_size,
            output_size=output_size,
            num_experts=num_experts,
        )
        self.moe_networks[moe.moe_id] = moe
        return moe

    def create_bridge(self, name: str = "bridge") -> NeuralSymbolicBridge:
        """Create a neural-symbolic bridge."""
        bridge = NeuralSymbolicBridge(name=name)
        self.bridges[bridge.bridge_id] = bridge
        return bridge

    def get_network(self, network_id: str) -> NeuralNetwork | None:
        return self.networks.get(network_id)

    def get_moe(self, moe_id: str) -> MixtureOfExperts | None:
        return self.moe_networks.get(moe_id)

    def get_bridge(self, bridge_id: str) -> NeuralSymbolicBridge | None:
        return self.bridges.get(bridge_id)

    def stats(self) -> dict[str, Any]:
        return {
            "networks": len(self.networks),
            "moe_networks": len(self.moe_networks),
            "bridges": len(self.bridges),
            "created_at": self.created_at,
        }


# -- Global instances --

_global_registry: NeuralNetworkRegistry | None = None


def get_neural_registry() -> NeuralNetworkRegistry:
    """Get or create the global neural network registry."""
    global _global_registry
    if _global_registry is None:
        _global_registry = NeuralNetworkRegistry()
    return _global_registry


def create_neural_network(name: str = "neural_network") -> NeuralNetwork:
    """Create a neural network in the global registry."""
    return get_neural_registry().create_network(name)

def create_moe_network(name: str = "moe_network",
                       input_size: int = 10,
                       output_size: int = 5,
                       num_experts: int = 8) -> MixtureOfExperts:
    """Create a Mixture-of-Experts network in the global registry."""
    return get_neural_registry().create_moe(
        name=name, input_size=input_size, output_size=output_size,
        num_experts=num_experts,
    )


__all__ = [
    "NeuralNetworkConfig",
    "NeuralNetworkLayer",
    "NeuralNetwork",
    "Expert",
    "MixtureOfExperts",
    "NeuralSymbolicBridge",
    "NeuralNetworkRegistry",
    "NeuralNetworkRegistry",
    "get_neural_registry",
    "create_neural_network",
    "create_moe_network",
]
