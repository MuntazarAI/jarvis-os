"""Core neural network building blocks - pure Python, CPU-friendly.

No external ML dependencies (no torch, no numpy). All operations implemented
in pure Python for CPU inference on development hardware (i3-1215U, 8GB RAM).

Research-grade reference implementations suitable for small-scale experiments.
"""

from __future__ import annotations

import math
import random
from typing import Any


class Tensor:
    """Multi-dimensional array backed by nested Python lists.

    Minimal tensor implementation supporting:
    - Basic arithmetic (+, -, *, /)
    - Matrix multiplication (@)
    - Transpose
    - Sum, mean, max
    - Reshape
    - Broadcasting
    """

    def __init__(self, data: list, shape: tuple[int, ...] | None = None):
        if shape is not None:
            self.shape = tuple(shape)
            # Flatten and reshape
            flat = self._flatten(data)
            self.data = self._reshape(flat, self.shape)
        else:
            self.data = data
            self.shape = self._infer_shape(data)

    @staticmethod
    def _flatten(data):
        """Flatten nested lists to 1D."""
        result = []

        def _flat(item):
            if isinstance(item, list):
                for sub in item:
                    _flat(sub)
            else:
                result.append(float(item))

        _flat(data)
        return result

    @staticmethod
    def _reshape(flat: list[float], shape: tuple[int, ...]):
        """Reshape flat list to nested structure."""
        if not shape:
            return flat[0] if flat else 0.0

        size = 1
        for dim in shape[1:]:
            size *= size

        # Actually compute correctly
        def build(idx, remaining_shape):
            if len(remaining_shape) == 1:
                return flat[idx:idx + remaining_shape[0]]
            dim = remaining_shape[0]
            sub_size = 1
            for d in remaining_shape[1:]:
                sub_size *= d
            return [build(idx + i * sub_size, remaining_shape[1:]) for i in range(dim)]

        return build(0, shape)

    @staticmethod
    def _infer_shape(data):
        """Infer shape from nested list structure."""
        shape = []
        current = data
        while isinstance(current, list):
            shape.append(len(current))
            if not current:
                break
            current = current[0]
        return tuple(shape)

    def __add__(self, other):
        if isinstance(other, Tensor):
            return Tensor(self._broadcast_op(self.data, other.data, lambda a, b: a + b))
        return Tensor(self._broadcast_op(self.data, [[other]], lambda a, b: a + b))

    def __sub__(self, other):
        if isinstance(other, Tensor):
            return Tensor(self._broadcast_op(self.data, other.data, lambda a, b: a - b))
        return Tensor(self._broadcast_op(self.data, [[other]], lambda a, b: a - b))

    def __mul__(self, other):
        if isinstance(other, Tensor):
            return Tensor(self._broadcast_op(self.data, other.data, lambda a, b: a * b))
        return Tensor(self._broadcast_op(self.data, [[other]], lambda a, b: a * b))

    def __truediv__(self, other):
        if isinstance(other, Tensor):
            return Tensor(self._broadcast_op(self.data, other.data, lambda a, b: a / b))
        return Tensor(self._broadcast_op(self.data, [[other]], lambda a, b: a / b))

    def __matmul__(self, other):
        """Matrix multiplication."""
        if not isinstance(other, Tensor):
            other = Tensor(other)
        a = self.data
        b = other.data
        return Tensor(self._matmul(a, b))

    @staticmethod
    def _matmul(a, b):
        """Matrix multiply two nested lists."""
        # Get dimensions
        a_rows = len(a)
        a_cols = len(a[0]) if a_rows > 0 else 0
        b_rows = len(b)
        b_cols = len(b[0]) if b_rows > 0 else 0

        # Handle 1D cases
        if not isinstance(a[0], list):
            a = [a]
            a_rows = 1
            a_cols = len(a[0])
        if not isinstance(b[0], list):
            b = [[x] for x in b]
            b_rows = len(b)
            b_cols = 1

        result = [[0.0] * b_cols for _ in range(a_rows)]
        for i in range(a_rows):
            for j in range(b_cols):
                for k in range(a_cols):
                    result[i][j] += a[i][k] * b[k][j]
        return result

    @staticmethod
    def _broadcast_op(a, b, op):
        """Apply op element-wise with broadcasting."""
        # Handle different shapes: broadcast b to match a
        a_is_list = isinstance(a, list)
        b_is_list = isinstance(b, list)

        if not a_is_list and not b_is_list:
            return op(a, b)
        if not a_is_list:
            return [[op(a, yi) for yi in row] for row in b]
        if not b_is_list:
            return [[op(xi, b) for xi in row] for row in a]

        # Both are lists - check if one is 1D and other is 2D
        a_1d = a_is_list and len(a) > 0 and not isinstance(a[0], list)
        b_1d = b_is_list and len(b) > 0 and not isinstance(b[0], list)

        if a_1d and not b_1d:
            # a is 1D, b is 2D - broadcast a across rows of b
            return [[op(ai, bj) for ai, bj in zip(a, row)] for row in b]
        if not a_1d and b_1d:
            # a is 2D, b is 1D - broadcast b across rows of a
            return [[op(ai, bj) for ai, bj in zip(row, b)] for row in a]

        # Both same depth - recurse
        def recurse(x, y):
            if isinstance(x, list):
                return [recurse(xi, yi) for xi, yi in zip(x, y)]
            return op(x, y)

        return recurse(a, b)

    def transpose(self):
        """Transpose a 2D tensor."""
        data = self.data
        if not isinstance(data[0], list):
            return Tensor([data])  # 1D -> row vector
        transposed = [[data[i][j] for i in range(len(data))] for j in range(len(data[0]))]
        return Tensor(transposed)

    def sum(self, axis=None):
        """Sum elements."""

        def recurse(x):
            if isinstance(x, list):
                return sum(recurse(xi) for xi in x)
            return x

        total = recurse(self.data)
        return total if axis is None else Tensor([total])

    def mean(self, axis=None):
        """Mean of elements."""

        def count(x):
            if isinstance(x, list):
                return sum(count(xi) for xi in x)
            return 1

        total = self.sum()
        n = count(self.data)
        return total / n if isinstance(total, (int, float)) else total / n

    def max(self, axis=None):
        """Max element."""

        def recurse(x):
            if isinstance(x, list):
                return max(recurse(xi) for xi in x)
            return x

        return recurse(self.data)

    def exp(self):
        """Element-wise exponential."""

        def recurse(x):
            if isinstance(x, list):
                return [recurse(xi) for xi in x]
            return math.exp(x)

        return Tensor(recurse(self.data))

    def log(self):
        """Element-wise natural log."""

        def recurse(x):
            if isinstance(x, list):
                return [recurse(xi) for xi in x]
            return math.log(max(x, 1e-10))

        return Tensor(recurse(self.data))

    def sqrt(self):
        """Element-wise square root."""

        def recurse(x):
            if isinstance(x, list):
                return [recurse(xi) for xi in x]
            return math.sqrt(max(x, 0.0))

        return Tensor(recurse(self.data))

    def pow(self, n):
        """Element-wise power."""

        def recurse(x):
            if isinstance(x, list):
                return [recurse(xi) for xi in x]
            return x ** n

        return Tensor(recurse(self.data))

    def tanh(self):
        """Element-wise tanh."""

        def recurse(x):
            if isinstance(x, list):
                return [recurse(xi) for xi in x]
            return math.tanh(x)

        return Tensor(recurse(self.data))

    def sigmoid(self):
        """Element-wise sigmoid."""

        def recurse(x):
            if isinstance(x, list):
                return [recurse(xi) for xi in x]
            return 1.0 / (1.0 + math.exp(-x))

        return Tensor(recurse(self.data))

    def relu(self):
        """Element-wise ReLU."""

        def recurse(x):
            if isinstance(x, list):
                return [recurse(xi) for xi in x]
            return max(0.0, x)

        return Tensor(recurse(self.data))

    def softmax(self, axis=-1):
        """Softmax along last axis."""

        def recurse(x):
            if isinstance(x, list) and isinstance(x[0], list):
                return [recurse(xi) for xi in x]
            if isinstance(x, list):
                # 1D - apply softmax
                m = max(x)
                exps = [math.exp(v - m) for v in x]
                sum_exps = sum(exps)
                return [e / sum_exps for e in exps]
            return x

        return Tensor(recurse(self.data))

    def tolist(self):
        """Convert to nested Python list."""
        return self.data

    def __repr__(self):
        return f"Tensor(shape={self.shape})"

    def __getitem__(self, idx):
        return self.data[idx]

    def __setitem__(self, idx, value):
        self.data[idx] = value


def zeros(shape: tuple[int, ...]) -> Tensor:
    """Create tensor of zeros."""
    flat = [0.0] * (1 if not shape else __import__("functools").reduce(lambda a, b: a * b, shape, 1))
    return Tensor(flat, shape)


def ones(shape: tuple[int, ...]) -> Tensor:
    """Create tensor of ones."""
    size = 1 if not shape else __import__("functools").reduce(lambda a, b: a * b, shape, 1)
    flat = [1.0] * size
    return Tensor(flat, shape)


def randn(shape: tuple[int, ...], seed: int | None = None) -> Tensor:
    """Create tensor with random normal values."""
    if seed is not None:
        random.seed(seed)
    size = 1 if not shape else __import__("functools").reduce(lambda a, b: a * b, shape, 1)
    flat = [random.gauss(0, 1) for _ in range(size)]
    return Tensor(flat, shape)


def xavier_init(fan_in: int, fan_out: int) -> Tensor:
    """Xavier/Glorot initialization."""
    limit = math.sqrt(6.0 / (fan_in + fan_out))
    flat = [random.uniform(-limit, limit) for _ in range(fan_in * fan_out)]
    return Tensor(flat, (fan_in, fan_out))


def he_init(fan_in: int, fan_out: int) -> Tensor:
    """He/Kaiming initialization."""
    std = math.sqrt(2.0 / fan_in)
    flat = [random.gauss(0, std) for _ in range(fan_in * fan_out)]
    return Tensor(flat, (fan_in, fan_out))


def dropout(tensor: Tensor, rate: float = 0.1, training: bool = True) -> Tensor:
    """Dropout - randomly zero elements during training."""
    if not training or rate <= 0:
        return tensor

    def recurse(x):
        if isinstance(x, list):
            return [recurse(xi) for xi in x]
        if random.random() < rate:
            return 0.0
        return x / (1.0 - rate)  # Scale up remaining

    return Tensor(recurse(tensor.tolist()))


class Linear:
    """Linear (fully connected) layer: y = xW + b."""

    def __init__(self, in_features: int, out_features: int, bias: bool = True,
                 seed: int | None = None):
        self.in_features = in_features
        self.out_features = out_features
        self.weight = xavier_init(in_features, out_features)
        self.bias = zeros((out_features,)) if bias else None

    def forward(self, x: Tensor) -> Tensor:
        output = x @ self.weight
        if self.bias is not None:
            output = output + self.bias
        return output

    def parameters(self) -> list[Tensor]:
        params = [self.weight]
        if self.bias is not None:
            params.append(self.bias)
        return params

    def __call__(self, x: Tensor) -> Tensor:
        return self.forward(x)


class ReLU:
    """ReLU activation."""

    def forward(self, x: Tensor) -> Tensor:
        return x.relu()

    def __call__(self, x: Tensor) -> Tensor:
        return self.forward(x)


class GELU:
    """GELU activation (approximate)."""

    def forward(self, x: Tensor) -> Tensor:
        # GELU approximation: 0.5 * x * (1 + tanh(sqrt(2/pi) * (x + 0.044715 * x^3)))
        def gelu(v):
            return 0.5 * v * (1.0 + math.tanh(
                math.sqrt(2.0 / math.pi) * (v + 0.044715 * v ** 3)
            ))

        def recurse(data):
            if isinstance(data, list):
                return [recurse(d) for d in data]
            return gelu(data)

        return Tensor(recurse(x.tolist()))

    def __call__(self, x: Tensor) -> Tensor:
        return self.forward(x)


class Softmax:
    """Softmax activation."""

    def __init__(self, dim: int = -1):
        self.dim = dim

    def forward(self, x: Tensor) -> Tensor:
        return x.softmax(axis=self.dim)

    def __call__(self, x: Tensor) -> Tensor:
        return self.forward(x)


class LayerNorm:
    """Layer normalization."""

    def __init__(self, normalized_shape: int, eps: float = 1e-5,
                 seed: int | None = None):
        self.normalized_shape = normalized_shape
        self.eps = eps
        self.weight = ones((normalized_shape,))
        self.bias = zeros((normalized_shape,))

    def forward(self, x: Tensor) -> Tensor:
        data = x.tolist()

        def recurse(d):
            if isinstance(d, list) and isinstance(d[0], list):
                return [recurse(sub) for sub in d]
            if isinstance(d, list):
                mean = sum(d) / len(d)
                var = sum((v - mean) ** 2 for v in d) / len(d)
                return [(v - mean) / math.sqrt(var + self.eps) for v in d]
            return d

        normalized = Tensor(recurse(data))
        # Apply weight and bias
        if isinstance(normalized.tolist(), list) and isinstance(normalized.tolist()[0], list):
            result = []
            for row in normalized.tolist():
                result.append([w * v + b for w, v, b in
                               zip(self.weight.tolist(), row, self.bias.tolist())])
            return Tensor(result)
        else:
            flat = normalized.tolist()
            return Tensor([w * v + b for w, v, b in
                          zip(self.weight.tolist(), flat, self.bias.tolist())])

    def parameters(self) -> list[Tensor]:
        return [self.weight, self.bias]

    def __call__(self, x: Tensor) -> Tensor:
        return self.forward(x)


class Embedding:
    """Token embedding layer."""

    def __init__(self, num_embeddings: int, embedding_dim: int,
                 seed: int | None = None):
        self.num_embeddings = num_embeddings
        self.embedding_dim = embedding_dim
        self.weight = xavier_init(num_embeddings, embedding_dim)

    def forward(self, input_ids: list[int]) -> Tensor:
        """Convert token indices to embeddings."""
        weight_data = self.weight.tolist()
        embedded = [weight_data[idx] for idx in input_ids]
        return Tensor(embedded)

    def parameters(self) -> list[Tensor]:
        return [self.weight]

    def __call__(self, input_ids: list[int]) -> Tensor:
        return self.forward(input_ids)


class MultiHeadAttention:
    """Multi-head self-attention."""

    def __init__(self, d_model: int, num_heads: int,
                 seed: int | None = None):
        assert d_model % num_heads == 0, "d_model must be divisible by num_heads"
        self.d_model = d_model
        self.num_heads = num_heads
        self.head_dim = d_model // num_heads

        self.w_q = Linear(d_model, d_model, bias=False, seed=seed)
        self.w_k = Linear(d_model, d_model, bias=False, seed=seed)
        self.w_v = Linear(d_model, d_model, bias=False, seed=seed)
        self.w_o = Linear(d_model, d_model, bias=False, seed=seed)

    def forward(self, x: Tensor, mask: list[list[bool]] | None = None) -> Tensor:
        # x shape: (seq_len, d_model)
        seq_len = len(x.tolist())
        d_model = self.d_model

        # Linear projections
        q = self.w_q(x)  # (seq_len, d_model)
        k = self.w_k(x)
        v = self.w_v(x)

        # Reshape to (num_heads, seq_len, head_dim)
        q_data = q.tolist()
        k_data = k.tolist()
        v_data = v.tolist()

        def split_heads(data):
            """Split (seq_len, d_model) into (num_heads, seq_len, head_dim)."""
            heads = []
            for h in range(self.num_heads):
                head = []
                for i in range(seq_len):
                    start = h * self.head_dim
                    end = start + self.head_dim
                    head.append(data[i][start:end])
                heads.append(head)
            return Tensor(heads, (self.num_heads, seq_len, self.head_dim))

        q_h = split_heads(q_data)
        k_h = split_heads(k_data)
        v_h = split_heads(v_data)

        # Scaled dot-product attention
        # scores = Q @ K^T / sqrt(head_dim) -> (num_heads, seq_len, seq_len)
        scores_data = []
        for h in range(self.num_heads):
            q_h_data = q_h.tolist()[h]
            k_h_data = k_h.tolist()[h]
            scores = [[0.0] * seq_len for _ in range(seq_len)]
            for i in range(seq_len):
                for j in range(seq_len):
                    dot = sum(q_h_data[i][d] * k_h_data[j][d] for d in range(self.head_dim))
                    scores[i][j] = dot / math.sqrt(self.head_dim)
            scores_data.append(scores)

        if mask is not None:
            for h in range(self.num_heads):
                for i in range(seq_len):
                    for j in range(seq_len):
                        if not mask[i][j]:
                            scores_data[h][i][j] = -1e9

        # Softmax
        attn_weights_data = []
        for h in range(self.num_heads):
            row_weights = []
            for i in range(seq_len):
                row = scores_data[h][i]
                m = max(row)
                exps = [math.exp(v - m) for v in row]
                s = sum(exps)
                row_weights.append([e / s for e in exps])
            attn_weights_data.append(row_weights)

        # Weighted sum of values
        v_h_data = v_h.tolist()
        output_data = []
        for h in range(self.num_heads):
            head_out = []
            for i in range(seq_len):
                out_dim = [0.0] * self.head_dim
                for j in range(seq_len):
                    for d in range(self.head_dim):
                        out_dim[d] += attn_weights_data[h][i][j] * v_h_data[h][j][d]
                head_out.append(out_dim)
            output_data.append(head_out)

        # Concatenate heads: (num_heads, seq_len, head_dim) -> (seq_len, d_model)
        concat = []
        for i in range(seq_len):
            row = []
            for h in range(self.num_heads):
                row.extend(output_data[h][i])
            concat.append(row)

        # Output projection
        result = self.w_o(Tensor(concat))
        return result

    def parameters(self) -> list[Tensor]:
        params = []
        for layer in [self.w_q, self.w_k, self.w_v, self.w_o]:
            params.extend(layer.parameters())
        return params

    def __call__(self, x: Tensor, mask: list[list[bool]] | None = None) -> Tensor:
        return self.forward(x, mask)


class TransformerBlock:
    """Transformer block: Multi-head attention + feed-forward."""

    def __init__(self, d_model: int, num_heads: int,
                 d_ff: int | None = None,
                 dropout_rate: float = 0.1,
                 seed: int | None = None):
        self.d_model = d_model
        self.num_heads = num_heads
        self.d_ff = d_ff or 4 * d_model
        self.dropout_rate = dropout_rate

        self.attention = MultiHeadAttention(d_model, num_heads, seed=seed)
        self.feed_forward = Sequential([
            Linear(d_model, self.d_ff, seed=seed),
            ReLU(),
            Linear(self.d_ff, d_model, seed=seed),
        ])
        self.norm1 = LayerNorm(d_model)
        self.norm2 = LayerNorm(d_model)

    def forward(self, x: Tensor, mask: list[list[bool]] | None = None) -> Tensor:
        # Self-attention with residual connection
        attn_out = self.attention(x, mask)
        x = Tensor([[a + b for a, b in zip(x_row, attn_row)]
                    for x_row, attn_row in zip(x.tolist(), attn_out.tolist())])
        x = self.norm1(x)

        # Feed-forward with residual connection
        ff_out = self.feed_forward(x)
        x = Tensor([[a + b for a, b in zip(x_row, ff_row)]
                    for x_row, ff_row in zip(x.tolist(), ff_out.tolist())])
        x = self.norm2(x)

        return x

    def parameters(self) -> list[Tensor]:
        params = []
        params.extend(self.attention.parameters())
        params.extend(self.feed_forward.parameters())
        params.extend(self.norm1.parameters())
        params.extend(self.norm2.parameters())
        return params

    def __call__(self, x: Tensor, mask: list[list[bool]] | None = None) -> Tensor:
        return self.forward(x, mask)


class Sequential:
    """Sequential container of layers."""

    def __init__(self, layers: list):
        self.layers = layers

    def forward(self, x: Tensor) -> Tensor:
        for layer in self.layers:
            x = layer(x)
        return x

    def parameters(self) -> list[Tensor]:
        params = []
        for layer in self.layers:
            if hasattr(layer, 'parameters'):
                params.extend(layer.parameters())
        return params

    def __call__(self, x: Tensor) -> Tensor:
        return self.forward(x)
