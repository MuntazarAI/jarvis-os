"""Mixture of Experts (MoE) architecture - M14/M15.

MoE routes each token to a subset of experts, enabling model scaling
without proportional compute increase. Implements:
- Router network for expert selection
- Top-k expert routing
- Auxiliary load balancing loss
- Shared expert + routed experts (hybrid MoE)
"""

from __future__ import annotations

import math
import random
from typing import Any

from .neural import (
    Linear,
    ReLU,
    Sequential,
    Tensor,
    dropout,
    zeros,
    ones,
    xavier_init,
    Embedding,
    LayerNorm,
)


class MoELayer:
    """Mixture of Experts layer.

    Routes each token to top-k experts using a learned router.
    Each expert is a feed-forward network.
    """

    def __init__(
        self,
        d_model: int,
        num_experts: int = 8,
        expert_top_k: int = 2,
        d_ff: int | None = None,
        dropout_rate: float = 0.1,
        seed: int | None = None,
        capacity_factor: float = 1.25,
    ):
        if seed is not None:
            random.seed(seed)

        self.d_model = d_model
        self.num_experts = num_experts
        self.expert_top_k = min(expert_top_k, num_experts)
        self.d_ff = d_ff or 4 * d_model
        self.dropout_rate = dropout_rate
        self.capacity_factor = capacity_factor

        # Router: maps each token to expert logits
        self.router = Linear(d_model, num_experts, bias=False, seed=seed)

        # Experts: each is a feed-forward network
        self.experts = [
            Sequential([
                Linear(d_model, self.d_ff, seed=seed),
                ReLU(),
                Linear(self.d_ff, d_model, seed=seed),
            ])
            for _ in range(num_experts)
        ]

        # Shared expert (always applied, like in some MoE designs)
        self.shared_expert = Sequential([
            Linear(d_model, self.d_ff, seed=seed),
            ReLU(),
            Linear(self.d_ff, d_model, seed=seed),
        ])

        # Router z-loss coefficient (encourages confident routing)
        self.router_z_loss_coeff = 0.001
        # Load balancing loss coefficient
        self.load_balancing_coeff = 0.01

    def forward(self, x: Tensor) -> Tensor:
        """Forward pass through MoE layer.

        Args:
            x: Tensor of shape (seq_len, d_model)

        Returns:
            Output tensor of shape (seq_len, d_model)
        """
        x_data = x.tolist()
        seq_len = len(x_data)

        # Router logits: (seq_len, num_experts)
        router_logits = self.router(x)  # (seq_len, num_experts)
        router_data = router_logits.tolist()

        # Compute routing probabilities (softmax over experts)
        router_probs = self._softmax_2d(router_data)

        # Top-k routing: select top-k experts per token
        top_k_indices = self._top_k(router_data, self.expert_top_k)

        # Compute capacity per expert
        capacity = max(
            1,
            int(seq_len * self.capacity_factor * self.expert_top_k / self.num_experts),
        )

        # Route tokens to experts
        output_data = [[0.0] * self.d_model for _ in range(seq_len)]

        # Track expert loads for load balancing loss
        expert_loads = [0] * self.num_experts

        for token_idx in range(seq_len):
            token_output = [0.0] * self.d_model
            token_weight_sum = 0.0

            for expert_idx in top_k_indices[token_idx]:
                expert_loads[expert_idx] += 1

                # Get expert output
                expert = self.experts[expert_idx]
                expert_out = expert(Tensor([x_data[token_idx]]))
                expert_out_data = expert_out.tolist()[0]

                # Get routing weight for this expert
                weight = router_probs[token_idx][expert_idx]

                # Weighted sum
                for d in range(self.d_model):
                    token_output[d] += weight * expert_out_data[d]
                token_weight_sum += weight

            # Normalize by sum of selected weights
            if token_weight_sum > 0:
                token_output = [v / token_weight_sum for v in token_output]

            # Add shared expert contribution (residual)
            shared_out = self.shared_expert(Tensor([x_data[token_idx]]))
            shared_out_data = shared_out.tolist()[0]
            shared_weight = 0.1  # Small weight for shared expert
            for d in range(self.d_model):
                token_output[d] += shared_weight * shared_out_data[d]

            output_data[token_idx] = token_output

        # Compute auxiliary losses
        self._compute_aux_losses(router_probs, expert_loads, seq_len)

        return Tensor(output_data)

    def _softmax_2d(self, logits_2d: list[list[float]]) -> list[list[float]]:
        """Softmax over last dimension."""
        result = []
        for row in logits_2d:
            m = max(row)
            exps = [math.exp(v - m) for v in row]
            s = sum(exps)
            result.append([e / s for e in exps])
        return result

    def _top_k(self, logits_2d: list[list[float]], k: int) -> list[list[int]]:
        """Get top-k expert indices per token."""
        result = []
        for row in logits_2d:
            indexed = list(enumerate(row))
            indexed.sort(key=lambda x: x[1], reverse=True)
            result.append([idx for idx, _ in indexed[:k]])
        return result

    def _compute_aux_losses(
        self,
        router_probs: list[list[float]],
        expert_loads: list[int],
        seq_len: int,
    ) -> None:
        """Compute auxiliary losses for load balancing and router z-loss."""
        # Load balancing loss: encourage equal expert utilization
        total_assignments = sum(expert_loads)
        if total_assignments == 0:
            self.load_balancing_loss = 0.0
        else:
            ideal_load = total_assignments / self.num_experts
            lb_loss = sum(
                (load - ideal_load) ** 2 for load in expert_loads
            ) / self.num_experts
            self.load_balancing_loss = lb_loss / (ideal_load ** 2) if ideal_load > 0 else 0.0

        # Router z-loss: encourage confident routing (high logit magnitude)
        z_loss = 0.0
        for row in router_probs:
            # z-loss = log(sum(exp(logits)))^2 averaged
            log_sum = math.log(sum(p + 1e-10 for p in row))
            z_loss += log_sum ** 2
        self.router_z_loss = z_loss / len(router_probs) if router_probs else 0.0

    def get_aux_loss(self) -> float:
        """Get combined auxiliary loss."""
        return (
            self.load_balancing_coeff * self.load_balancing_loss
            + self.router_z_loss_coeff * self.router_z_loss
        )

    def get_stats(self) -> dict[str, Any]:
        """Get MoE layer statistics."""
        return {
            "num_experts": self.num_experts,
            "expert_top_k": self.expert_top_k,
            "d_model": self.d_model,
            "d_ff": self.d_ff,
            "load_balancing_loss": self.load_balancing_loss,
            "router_z_loss": self.router_z_loss,
            "total_expert_params": sum(
                sum(p.tolist().__len__() if not isinstance(p.tolist()[0], list)
                    else len(p.tolist()) * len(p.tolist()[0])
                    for p in expert.parameters())
                for expert in self.experts
            ),
        }

    def parameters(self) -> list[Tensor]:
        """Get all parameters."""
        params = self.router.parameters()
        for expert in self.experts:
            params.extend(expert.parameters())
        params.extend(self.shared_expert.parameters())
        return params

    def __call__(self, x: Tensor) -> Tensor:
        return self.forward(x)


class MoETransformerBlock:
    """Transformer block with MoE feed-forward instead of dense FFN."""

    def __init__(
        self,
        d_model: int,
        num_heads: int,
        num_experts: int = 8,
        expert_top_k: int = 2,
        d_ff: int | None = None,
        dropout_rate: float = 0.1,
        seed: int | None = None,
    ):
        self.d_model = d_model
        self.num_heads = num_heads

        from .neural import MultiHeadAttention, LayerNorm

        self.attention = MultiHeadAttention(d_model, num_heads, seed=seed)
        self.moe = MoELayer(
            d_model=d_model,
            num_experts=num_experts,
            expert_top_k=expert_top_k,
            d_ff=d_ff,
            dropout_rate=dropout_rate,
            seed=seed,
        )
        self.norm1 = LayerNorm(d_model)
        self.norm2 = LayerNorm(d_model)

    def forward(self, x: Tensor, mask: list[list[bool]] | None = None) -> Tensor:
        # Self-attention with residual
        attn_out = self.attention(x, mask)
        x_data = x.tolist()
        attn_data = attn_out.tolist()
        x = Tensor([
            [a + b for a, b in zip(x_row, attn_row)]
            for x_row, attn_row in zip(x_data, attn_data)
        ])
        x = self.norm1(x)

        # MoE with residual
        moe_out = self.moe(x)
        x_data = x.tolist()
        moe_data = moe_out.tolist()
        x = Tensor([
            [a + b for a, b in zip(x_row, moe_row)]
            for x_row, moe_row in zip(x_data, moe_data)
        ])
        x = self.norm2(x)

        return x

    def get_aux_loss(self) -> float:
        return self.moe.get_aux_loss()

    def parameters(self) -> list[Tensor]:
        params = []
        params.extend(self.attention.parameters())
        params.extend(self.moe.parameters())
        params.extend(self.norm1.parameters())
        params.extend(self.norm2.parameters())
        return params

    def __call__(self, x: Tensor, mask: list[list[bool]] | None = None) -> Tensor:
        return self.forward(x, mask)


class MoETransformer:
    """Transformer with MoE layers - scalable architecture.

    Uses MoE feed-forward networks in each block instead of dense FFNs,
    enabling parameter scaling without proportional compute increase.
    """

    def __init__(
        self,
        vocab_size: int,
        d_model: int = 256,
        num_layers: int = 4,
        num_heads: int = 4,
        num_experts: int = 8,
        expert_top_k: int = 2,
        d_ff: int | None = None,
        max_seq_len: int = 512,
        dropout_rate: float = 0.1,
        seed: int | None = None,
    ):
        self.vocab_size = vocab_size
        self.d_model = d_model
        self.num_layers = num_layers
        self.num_heads = num_heads
        self.num_experts = num_experts
        self.expert_top_k = expert_top_k
        self.d_ff = d_ff or 4 * d_model
        self.max_seq_len = max_seq_len
        self.dropout_rate = dropout_rate

        # Token and position embeddings
        self.token_embedding = Embedding(vocab_size, d_model, seed=seed)
        self.position_embedding = Embedding(max_seq_len, d_model, seed=seed)

        # MoE transformer blocks
        self.blocks = [
            MoETransformerBlock(
                d_model=d_model,
                num_heads=num_heads,
                num_experts=num_experts,
                expert_top_k=expert_top_k,
                d_ff=self.d_ff,
                dropout_rate=dropout_rate,
                seed=seed,
            )
            for _ in range(num_layers)
        ]

        # Output layers
        self.final_norm = LayerNorm(d_model)
        self.lm_head = Linear(d_model, vocab_size, bias=False, seed=seed)

        # Track total aux loss across all blocks
        self.total_aux_loss = 0.0

    def forward(self, input_ids: list[int],
                mask: list[list[bool]] | None = None) -> Tensor:
        seq_len = len(input_ids)

        if mask is None:
            mask = [[i >= j for j in range(seq_len)] for j in range(seq_len) for i in range(seq_len)]
            mask = [mask[i * seq_len:(i + 1) * seq_len] for i in range(seq_len)]

        # Embeddings
        token_emb = self.token_embedding(input_ids)
        position_ids = list(range(seq_len))
        pos_emb = self.position_embedding(position_ids)

        x_data = [
            [a + b for a, b in zip(t_row, p_row)]
            for t_row, p_row in zip(token_emb.tolist(), pos_emb.tolist())
        ]
        x = Tensor(x_data)
        x = dropout(x, self.dropout_rate, training=False)

        # MoE blocks
        self.total_aux_loss = 0.0
        for block in self.blocks:
            x = block(x, mask)
            self.total_aux_loss += block.get_aux_loss()

        # Final norm
        x = self.final_norm(x)

        # LM head
        logits = self.lm_head(x)

        return logits

    def generate(self, input_ids: list[int],
                 max_new_tokens: int = 50,
                 temperature: float = 1.0,
                 top_p: float = 0.9,
                 seed: int | None = None) -> dict[str, Any]:
        import random as _random
        if seed is not None:
            _random.seed(seed)

        generated = list(input_ids)
        eos_token = self.vocab_size - 1

        for _ in range(max_new_tokens):
            context = generated[-self.max_seq_len:]
            logits = self.forward(context)
            last_logits = logits.tolist()[-1]

            if temperature != 1.0:
                last_logits = [v / temperature for v in last_logits]

            probs = self._softmax(last_logits)
            sorted_indices = sorted(range(len(probs)), key=lambda i: probs[i], reverse=True)
            cumulative = 0.0
            nucleus = []
            for idx in sorted_indices:
                nucleus.append(idx)
                cumulative += probs[idx]
                if cumulative >= top_p:
                    break

            nucleus_probs = [probs[i] for i in nucleus]
            nucleus_total = sum(nucleus_probs)
            nucleus_probs = [p / nucleus_total for p in nucleus_probs]

            r = _random.random()
            cumulative = 0.0
            next_token = nucleus[0]
            for idx, p in zip(nucleus, nucleus_probs):
                cumulative += p
                if r <= cumulative:
                    next_token = idx
                    break

            generated.append(next_token)
            if next_token == eos_token:
                break

        generated_text = " ".join(f"<t{t}>" for t in generated[len(input_ids):])

        return {
            "generated_ids": generated,
            "generated_text": generated_text,
            "input_ids": input_ids,
            "new_tokens": len(generated) - len(input_ids),
        }

    @staticmethod
    def _softmax(logits: list[float]) -> list[float]:
        m = max(logits)
        exps = [math.exp(v - m) for v in logits]
        s = sum(exps)
        return [e / s for e in exps]

    def get_parameter_count(self) -> int:
        count = 0
        count += self.vocab_size * self.d_model
        count += self.max_seq_len * self.d_model
        for block in self.blocks:
            for p in block.parameters():
                data = p.tolist()
                if isinstance(data, list):
                    if isinstance(data[0], list):
                        count += len(data) * len(data[0])
                    else:
                        count += len(data)
                else:
                    count += 1
        count += self.d_model * 2
        count += self.d_model * self.vocab_size
        return count

    def get_aux_loss(self) -> float:
        return self.total_aux_loss

    def get_stats(self) -> dict[str, Any]:
        return {
            "vocab_size": self.vocab_size,
            "d_model": self.d_model,
            "num_layers": self.num_layers,
            "num_heads": self.num_heads,
            "num_experts": self.num_experts,
            "expert_top_k": self.expert_top_k,
            "parameter_count": self.get_parameter_count(),
            "aux_loss": self.get_aux_loss(),
        }
