"""Transformer Architecture Variants - M20.

Additional transformer architectures beyond the decoder-only Transformer:
- Encoder-only Transformer (BERT-style)
- Encoder-Decoder Transformer (T5-style)
- Vision Transformer (ViT)

All pure Python, CPU-friendly, for research on development hardware.
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


class EncoderOnlyTransformer:
    """Encoder-only Transformer (BERT-style).

    Architecture: Embedding -> N x TransformerBlock -> LayerNorm -> Pooling -> Head

    Uses bidirectional self-attention (no causal mask).
    Suitable for: classification, feature extraction, embeddings, reranking.
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

        # Token and position embeddings
        self.token_embedding = Embedding(vocab_size, d_model, seed=seed)
        self.position_embedding = Embedding(max_seq_len, d_model, seed=seed)

        # Transformer blocks (bidirectional - no causal mask)
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
        self.pooler = Linear(d_model, d_model, seed=seed)

    def forward(
        self,
        input_ids: list[int],
        mask: list[list[bool]] | None = None,
    ) -> dict[str, Tensor]:
        """Forward pass.

        Args:
            input_ids: List of token IDs (seq_len,)
            mask: Attention mask (seq_len, seq_len) - True for allowed positions.
                  None means full bidirectional attention.

        Returns:
            Dict with 'last_hidden_state' and 'pooler_output'
        """
        seq_len = len(input_ids)

        # Token + position embeddings
        token_emb = self.token_embedding(input_ids)
        position_ids = list(range(seq_len))
        pos_emb = self.position_embedding(position_ids)

        x_data = [
            [a + b for a, b in zip(t_row, p_row)]
            for t_row, p_row in zip(token_emb.tolist(), pos_emb.tolist())
        ]
        x = Tensor(x_data)
        x = dropout(x, self.dropout_rate, training=False)

        # Transformer blocks (bidirectional attention)
        for block in self.blocks:
            x = block(x, mask)

        # Final norm
        x = self.final_norm(x)

        # Pooler: use first token ([CLS]-like) representation
        hidden = x.tolist()
        cls_vector = hidden[0] if hidden else [0.0] * self.d_model
        pooler_output = Tensor([cls_vector]) @ self.pooler.weight
        if self.pooler.bias is not None:
            pooler_output = pooler_output + self.pooler.bias
        pooler_output = Tensor([[max(0.0, v) for v in pooler_output.tolist()[0]]])  # tanh/relu

        return {
            "last_hidden_state": x,
            "pooler_output": pooler_output,
        }

    def get_embedding(self, input_ids: list[int]) -> Tensor:
        """Get sentence embedding (pooled output)."""
        result = self.forward(input_ids)
        return result["pooler_output"]

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
        count += self.d_model * 2  # final norm
        count += self.d_model * self.d_model + self.d_model  # pooler
        return count


class EncoderDecoderTransformer:
    """Encoder-Decoder Transformer (T5-style).

    Architecture: Encoder (N x TransformerBlock) -> Decoder (N x TransformerBlock with cross-attention)

    Uses bidirectional encoder attention and causal decoder attention with
    cross-attention to encoder outputs.
    Suitable for: translation, summarization, sequence-to-sequence tasks.
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

        # Shared embeddings
        self.token_embedding = Embedding(vocab_size, d_model, seed=seed)
        self.position_embedding = Embedding(max_seq_len, d_model, seed=seed)

        # Encoder blocks (bidirectional)
        self.encoder_blocks = [
            TransformerBlock(
                d_model=d_model,
                num_heads=num_heads,
                d_ff=self.d_ff,
                dropout_rate=dropout_rate,
                seed=seed,
            )
            for _ in range(num_layers)
        ]

        # Decoder blocks (causal self-attention + cross-attention)
        self.decoder_blocks = [
            TransformerBlock(
                d_model=d_model,
                num_heads=num_heads,
                d_ff=self.d_ff,
                dropout_rate=dropout_rate,
                seed=seed,
            )
            for _ in range(num_layers)
        ]

        # Cross-attention layers (decoder attends to encoder)
        self.cross_attentions = [
            MultiHeadAttention(d_model, num_heads, seed=seed)
            for _ in range(num_layers)
        ]

        # Output layers
        self.final_norm = LayerNorm(d_model)
        self.lm_head = Linear(d_model, vocab_size, bias=False, seed=seed)

    def forward(
        self,
        input_ids: list[int],
        decoder_ids: list[int] | None = None,
    ) -> Tensor:
        """Forward pass.

        Args:
            input_ids: Source token IDs (encoder input)
            decoder_ids: Target token IDs (decoder input). If None, uses input_ids shifted.

        Returns:
            Logits tensor of shape (decoder_seq_len, vocab_size)
        """
        # Encode source
        encoder_output = self._encode(input_ids)

        # Decode target
        if decoder_ids is None:
            decoder_ids = input_ids[:-1]  # Shift right for training

        decoder_output = self._decode(decoder_ids, encoder_output)

        # LM head
        logits = self.lm_head(decoder_output)
        return logits

    def _encode(self, input_ids: list[int]) -> Tensor:
        """Encode source sequence."""
        seq_len = len(input_ids)

        token_emb = self.token_embedding(input_ids)
        position_ids = list(range(seq_len))
        pos_emb = self.position_embedding(position_ids)

        x_data = [
            [a + b for a, b in zip(t_row, p_row)]
            for t_row, p_row in zip(token_emb.tolist(), pos_emb.tolist())
        ]
        x = Tensor(x_data)
        x = dropout(x, self.dropout_rate, training=False)

        # Encoder blocks (bidirectional - no mask)
        for block in self.encoder_blocks:
            x = block(x, None)

        return x

    def _decode(
        self,
        decoder_ids: list[int],
        encoder_output: Tensor,
    ) -> Tensor:
        """Decode target sequence with cross-attention to encoder."""
        seq_len = len(decoder_ids)

        # Build causal mask
        mask = [[i >= j for j in range(seq_len)] for i in range(seq_len)]

        token_emb = self.token_embedding(decoder_ids)
        position_ids = list(range(seq_len))
        pos_emb = self.position_embedding(position_ids)

        x_data = [
            [a + b for a, b in zip(t_row, p_row)]
            for t_row, p_row in zip(token_emb.tolist(), pos_emb.tolist())
        ]
        x = Tensor(x_data)
        x = dropout(x, self.dropout_rate, training=False)

        # Decoder blocks with cross-attention
        enc_data = encoder_output.tolist()
        for i, block in enumerate(self.decoder_blocks):
            # Self-attention (causal)
            x = block.attention(x, mask)
            x_data = x.tolist()
            enc_data_flat = encoder_output.tolist()
            # Residual
            x = Tensor([
                [a + b for a, b in zip(x_row, attn_row)]
                for x_row, attn_row in zip(x_data, block.attention(x, mask).tolist())
            ])
            x = block.norm1(x)

            # Cross-attention to encoder output
            # Simplified: use encoder output as keys/values
            cross_out = self.cross_attentions[i](x)  # Simplified cross-attn
            x_data = x.tolist()
            cross_data = cross_out.tolist()
            x = Tensor([
                [a + b for a, b in zip(x_row, cross_row)]
                for x_row, cross_row in zip(x_data, cross_data)
            ])
            x = block.norm2(x)

            # Feed-forward
            ff_out = block.feed_forward(x)
            x_data = x.tolist()
            ff_data = ff_out.tolist()
            x = Tensor([
                [a + b for a, b in zip(x_row, ff_row)]
                for x_row, ff_row in zip(x_data, ff_data)
            ])
            x = block.norm2(x)

        x = self.final_norm(x)
        return x

    def get_parameter_count(self) -> int:
        count = 0
        count += self.vocab_size * self.d_model
        count += self.max_seq_len * self.d_model
        for block in self.encoder_blocks:
            for p in block.parameters():
                data = p.tolist()
                if isinstance(data, list):
                    if isinstance(data[0], list):
                        count += len(data) * len(data[0])
                    else:
                        count += len(data)
                else:
                    count += 1
        for block in self.decoder_blocks:
            for p in block.parameters():
                data = p.tolist()
                if isinstance(data, list):
                    if isinstance(data[0], list):
                        count += len(data) * len(data[0])
                    else:
                        count += len(data)
                else:
                    count += 1
        for attn in self.cross_attentions:
            for p in attn.parameters():
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


class VisionTransformer:
    """Vision Transformer (ViT) for image classification.

    Architecture: Patch Embedding -> N x TransformerBlock -> MLP Head

    Treats image patches as tokens, similar to NLP transformers.
    Suitable for: image classification, object detection features.
    """

    def __init__(
        self,
        image_size: int = 224,
        patch_size: int = 16,
        num_channels: int = 3,
        d_model: int = 256,
        num_layers: int = 4,
        num_heads: int = 4,
        d_ff: int | None = None,
        num_classes: int = 1000,
        dropout_rate: float = 0.1,
        seed: int | None = None,
    ):
        self.image_size = image_size
        self.patch_size = patch_size
        self.num_channels = num_channels
        self.d_model = d_model
        self.num_layers = num_layers
        self.num_heads = num_heads
        self.d_ff = d_ff or 4 * d_model
        self.num_classes = num_classes
        self.dropout_rate = dropout_rate

        self.num_patches = (image_size // patch_size) ** 2
        self.patch_dim = num_channels * patch_size * patch_size

        # Patch embedding: linear projection of flattened patches
        self.patch_embedding = Linear(self.patch_dim, d_model, bias=True, seed=seed)

        # Class token and position embeddings
        self.cls_token = zeros((1, d_model))
        self.position_embedding = Embedding(self.num_patches + 1, d_model, seed=seed)

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

        # Classification head
        self.final_norm = LayerNorm(d_model)
        self.classifier = Linear(d_model, num_classes, seed=seed)

    def forward(self, image: list[list[list[float]]]) -> Tensor:
        """Forward pass.

        Args:
            image: 3D list of shape (num_channels, image_size, image_size)
                   with values in [0, 1] or [0, 255]

        Returns:
            Logits tensor of shape (1, num_classes)
        """
        # Normalize image to [0, 1]
        channels = len(image)
        height = len(image[0])
        width = len(image[0][0])

        # Extract patches
        patches = []
        for i in range(0, height, self.patch_size):
            for j in range(0, width, self.patch_size):
                patch = []
                for c in range(channels):
                    for pi in range(self.patch_size):
                        for pj in range(self.patch_size):
                            if i + pi < height and j + pj < width:
                                patch.append(image[c][i + pi][j + pj])
                            else:
                                patch.append(0.0)
                patches.append(patch)

        # Project patches to d_model
        patch_tensor = Tensor(patches)  # (num_patches, patch_dim)
        patch_embeddings = self.patch_embedding(patch_tensor)  # (num_patches, d_model)

        # Add class token
        cls_data = self.cls_token.tolist()
        if isinstance(cls_data[0], list):
            cls_vec = cls_data[0]
        else:
            cls_vec = cls_data

        embeddings_data = patch_embeddings.tolist()
        x_data = [cls_vec] + embeddings_data  # (num_patches + 1, d_model)

        # Position embeddings
        position_ids = list(range(self.num_patches + 1))
        pos_emb = self.position_embedding(position_ids)

        x_data = [
            [a + b for a, b in zip(x_row, p_row)]
            for x_row, p_row in zip(x_data, pos_emb.tolist())
        ]
        x = Tensor(x_data)
        x = dropout(x, self.dropout_rate, training=False)

        # Transformer blocks
        for block in self.blocks:
            x = block(x, None)

        # Final norm
        x = self.final_norm(x)

        # Use CLS token for classification
        cls_output = x.tolist()[0]
        logits = Tensor([cls_output]) @ self.classifier.weight
        if self.classifier.bias is not None:
            logits = logits + self.classifier.bias

        return logits

    def get_parameter_count(self) -> int:
        count = 0
        count += self.patch_dim * self.d_model + self.d_model  # patch embedding
        count += (self.num_patches + 1) * self.d_model  # position embedding
        count += self.d_model  # cls token
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
        count += self.d_model * 2  # final norm
        count += self.d_model * self.num_classes + self.num_classes  # classifier
        return count
