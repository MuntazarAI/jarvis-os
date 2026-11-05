"""Decoder-only Transformer model - JARVIS-LLM reference implementation.

Pure Python implementation suitable for CPU inference on development hardware.
Supports causal self-attention, position embeddings, and text generation.
"""

from __future__ import annotations

import math
from typing import Any

from .neural import (
    Embedding,
    LayerNorm,
    Linear,
    MultiHeadAttention,
    Sequential,
    Tensor,
    TransformerBlock,
    dropout,
    zeros,
    ones,
)


class DecoderOnlyTransformer:
    """Decoder-only Transformer language model.

    Architecture: Embedding -> N x TransformerBlock -> LayerNorm -> Linear(vocab)

    Uses causal (masked) self-attention for autoregressive text generation.
    Suitable for small-scale language modeling experiments on CPU.
    """

    def __init__(
        self,
        vocab_size: int,
        d_model: int = 256,
        num_layers: int = 4,
        num_heads: int = 4,
        d_ff: int | None = None,
        max_seq_len: int = 512,
        dropout_rate: float = 0.1,
        seed: int | None = None,
    ):
        self.vocab_size = vocab_size
        self.d_model = d_model
        self.num_layers = num_layers
        self.num_heads = num_heads
        self.d_ff = d_ff or 4 * d_model
        self.max_seq_len = max_seq_len
        self.dropout_rate = dropout_rate

        if seed is not None:
            import random as _random
            _random.seed(seed)

        # Token and position embeddings
        self.token_embedding = Embedding(vocab_size, d_model, seed=seed)
        self.position_embedding = Embedding(max_seq_len, d_model, seed=seed)

        # Transformer blocks
        self.blocks = [
            TransformerBlock(
                d_model=d_model,
                num_heads=num_heads,
                d_ff=self.d_ff,
                dropout_rate=dropout_rate,
                seed=seed,
            )
            for _ in range(num_layers)
        ]

        # Output layers
        self.final_norm = LayerNorm(d_model)
        self.lm_head = Linear(d_model, vocab_size, bias=False, seed=seed)

    def forward(self, input_ids: list[int],
                mask: list[list[bool]] | None = None) -> Tensor:
        """Forward pass through the model.

        Args:
            input_ids: List of token IDs (seq_len,)
            mask: Causal mask (seq_len, seq_len) - True for allowed positions

        Returns:
            Logits tensor of shape (seq_len, vocab_size)
        """
        seq_len = len(input_ids)

        # Build causal mask if not provided
        if mask is None:
            mask = [[i >= j for j in range(seq_len)] for i in range(seq_len)]

        # Token + position embeddings
        token_emb = self.token_embedding(input_ids)
        position_ids = list(range(seq_len))
        pos_emb = self.position_embedding(position_ids)

        # Combine embeddings
        x_data = [
            [a + b for a, b in zip(t_row, p_row)]
            for t_row, p_row in zip(token_emb.tolist(), pos_emb.tolist())
        ]
        x = Tensor(x_data)

        # Apply dropout
        x = dropout(x, self.dropout_rate, training=False)

        # Transformer blocks
        for block in self.blocks:
            x = block(x, mask)

        # Final norm
        x = self.final_norm(x)

        # Language modeling head
        logits = self.lm_head(x)

        return logits

    def generate(self, input_ids: list[int],
                 max_new_tokens: int = 50,
                 temperature: float = 1.0,
                 top_p: float = 0.9,
                 seed: int | None = None) -> dict[str, Any]:
        """Autoregressive text generation.

        Args:
            input_ids: Initial token IDs
            max_new_tokens: Maximum tokens to generate
            temperature: Sampling temperature (1.0 = neutral, lower = more deterministic)
            top_p: Nucleus sampling threshold
            seed: Random seed for reproducibility

        Returns:
            Dict with generated_ids and generated_text
        """
        import random as _random
        if seed is not None:
            _random.seed(seed)

        generated = list(input_ids)
        eos_token = self.vocab_size - 1  # Reserve last token as EOS

        for _ in range(max_new_tokens):
            # Truncate to max_seq_len
            context = generated[-self.max_seq_len:]

            # Forward pass
            logits = self.forward(context)  # (seq_len, vocab_size)
            last_logits = logits.tolist()[-1]  # Last position logits

            # Apply temperature
            if temperature != 1.0:
                last_logits = [v / temperature for v in last_logits]

            # Top-p (nucleus) sampling
            probs = self._softmax(last_logits)
            sorted_indices = sorted(range(len(probs)), key=lambda i: probs[i], reverse=True)
            cumulative = 0.0
            nucleus = []
            for idx in sorted_indices:
                nucleus.append(idx)
                cumulative += probs[idx]
                if cumulative >= top_p:
                    break

            # Sample from nucleus
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

        # Decode tokens to text (simple mapping)
        generated_text = " ".join(f"<t{t}>" for t in generated[len(input_ids):])

        return {
            "generated_ids": generated,
            "generated_text": generated_text,
            "input_ids": input_ids,
            "new_tokens": len(generated) - len(input_ids),
        }

    @staticmethod
    def _softmax(logits: list[float]) -> list[float]:
        """Compute softmax probabilities."""
        m = max(logits)
        exps = [math.exp(v - m) for v in logits]
        s = sum(exps)
        return [e / s for e in exps]

    def get_parameter_count(self) -> int:
        """Estimate total parameter count."""
        count = 0
        # Embeddings
        count += self.vocab_size * self.d_model  # token
        count += self.max_seq_len * self.d_model  # position
        # Transformer blocks
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
        # Final norm
        count += self.d_model * 2  # weight + bias
        # LM head
        count += self.d_model * self.vocab_size
        return count

    def get_memory_footprint(self) -> dict[str, float]:
        """Estimate memory footprint in MB."""
        params = self.get_parameter_count()
        param_bytes = params * 4  # FP32
        return {
            "parameters_mb": param_bytes / (1024 * 1024),
            "gradients_mb": param_bytes / (1024 * 1024),
            "optimizer_mb": param_bytes * 2 / (1024 * 1024),
            "total_mb": param_bytes * 4 / (1024 * 1024),
        }


class JARVIS_LLM_Model:
    """JARVIS-LLM wrapper with StarkAI compatibility.

    Provides a high-level interface for the JARVIS-LLM foundation model
    with tokenization, inference, and evaluation support.
    """

    def __init__(self, model: DecoderOnlyTransformer,
                 tokenizer=None, config=None):
        self.model = model
        self.tokenizer = tokenizer
        self.config = config or {}
        self.created_at = None
        import time
        self.created_at = time.time()
        self.training_step = 0
        self.total_tokens = 0
        self.is_trained = False
        self.is_deployed = False

    def forward(self, input_ids: list[int]) -> Tensor:
        """Run inference on token IDs."""
        return self.model.forward(input_ids)

    def generate(
            self,
            prompt_or_ids: str | list[int],
            max_new_tokens: int = 50,
            temperature: float = 0.7,
            top_p: float = 0.9,
            seed: int | None = None,
        ) -> dict[str, Any]:
        """Generate text from a prompt string or token IDs."""
        if isinstance(prompt_or_ids, str):
            prompt = prompt_or_ids
            # Simple character-level tokenization
            if self.tokenizer:
                input_ids = self.tokenizer.encode(prompt)
            else:
                input_ids = [ord(c) % self.model.vocab_size for c in prompt]
        else:
            input_ids = list(prompt_or_ids)

        result = self.model.generate(
            input_ids, max_new_tokens=max_new_tokens,
            temperature=temperature, top_p=top_p, seed=seed
        )

        # Simple detokenization
        if self.tokenizer:
            result["generated_text"] = self.tokenizer.decode(result["generated_ids"])
        else:
            result["generated_text"] = "".join(
                chr(t % 128) for t in result["generated_ids"] if t < 128
            )

        return result

    def encode(self, text: str) -> list[int]:
        """Encode text to token IDs."""
        if self.tokenizer:
            return self.tokenizer.encode(text)
        return [ord(c) % self.model.vocab_size for c in text]

    def decode(self, token_ids: list[int]) -> str:
        """Decode token IDs to text."""
        if self.tokenizer:
            return self.tokenizer.decode(token_ids)
        return "".join(chr(t % 128) for t in token_ids if t < 128)

    def get_parameter_count(self) -> int:
        return self.model.get_parameter_count()

    def get_memory_footprint(self) -> dict[str, float]:
        return self.model.get_memory_footprint()

    def to_dict(self) -> dict[str, Any]:
        return {
            "vocab_size": self.model.vocab_size,
            "d_model": self.model.d_model,
            "num_layers": self.model.num_layers,
            "num_heads": self.model.num_heads,
            "max_seq_len": self.model.max_seq_len,
            "parameter_count": self.get_parameter_count(),
            "memory_footprint": self.get_memory_footprint(),
            "is_trained": self.is_trained,
            "is_deployed": self.is_deployed,
        }
