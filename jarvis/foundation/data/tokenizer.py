"""Tokenizer Research - M19.

Tokenization implementations for JARVIS foundation models:
- Byte Pair Encoding (BPE)
- WordPiece
- Character-level
- Word-level

All implementations are pure Python, suitable for CPU-based research.
Includes training, encoding, decoding, and vocabulary management.
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class TokenizerSpec:
    """Tokenizer specification."""
    tokenizer_id: str
    name: str
    tokenizer_type: str  # "bpe", "wordpiece", "character", "word"
    vocab_size: int
    vocab: dict[str, int]  # token -> id
    id_to_token: dict[int, str]
    special_tokens: dict[str, int]  # token -> id
    created_at: float
    training_stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tokenizer_id": self.tokenizer_id,
            "name": self.name,
            "tokenizer_type": self.tokenizer_type,
            "vocab_size": self.vocab_size,
            "vocab": self.vocab,
            "special_tokens": self.special_tokens,
            "created_at": self.created_at,
            "training_stats": self.training_stats,
        }


class BaseTokenizer:
    """Base class for all tokenizers."""

    def __init__(self, vocab_size: int = 50000, special_tokens: dict[str, int] | None = None):
        self.vocab_size = vocab_size
        self.special_tokens = special_tokens or {
            "<pad>": 0,
            "<unk>": 1,
            "<bos>": 2,
            "<eos>": 3,
        }
        self.vocab: dict[str, int] = dict(self.special_tokens)
        self.id_to_token: dict[int, str] = {v: k for k, v in self.vocab.items()}
        self.tokenizer_type = "base"
        self.created_at = time.time()
        self.training_stats: dict[str, Any] = {}

    def train(self, texts: list[str]) -> None:
        """Train the tokenizer on a corpus."""
        raise NotImplementedError

    def encode(self, text: str, add_special_tokens: bool = True) -> list[int]:
        """Encode text to token IDs."""
        raise NotImplementedError

    def decode(self, token_ids: list[int], skip_special_tokens: bool = False) -> str:
        """Decode token IDs to text."""
        raise NotImplementedError

    def get_vocab_size(self) -> int:
        return len(self.vocab)

    def save(self, path: str | Path) -> None:
        """Save tokenizer to JSON."""
        output = {
            "tokenizer_type": self.tokenizer_type,
            "vocab_size": self.vocab_size,
            "vocab": self.vocab,
            "special_tokens": self.special_tokens,
            "created_at": self.created_at,
            "training_stats": self.training_stats,
        }
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(output, indent=2, ensure_ascii=False))

    @classmethod
    def load(cls, path: str | Path) -> "BaseTokenizer":
        """Load tokenizer from JSON."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        # This is a simplified loader - subclasses should override
        raise NotImplementedError("Use subclass load method")


class CharacterTokenizer(BaseTokenizer):
    """Character-level tokenizer.

    Simplest tokenizer - each character is a token.
    Good for small vocabularies and robust handling of unseen text.
    """

    def __init__(self, vocab_size: int = 256, special_tokens: dict[str, int] | None = None):
        super().__init__(vocab_size=vocab_size, special_tokens=special_tokens)
        self.tokenizer_type = "character"

    def train(self, texts: list[str]) -> None:
        """Build character vocabulary from corpus."""
        chars = set()
        for text in texts:
            chars.update(text)

        # Sort for determinism
        sorted_chars = sorted(chars)

        # Add characters up to vocab_size limit
        next_id = max(self.special_tokens.values()) + 1
        for ch in sorted_chars:
            if next_id >= self.vocab_size:
                break
            if ch not in self.vocab:
                self.vocab[ch] = next_id
                next_id += 1

        self.id_to_token = {v: k for k, v in self.vocab.items()}
        self.training_stats = {
            "num_chars": len(chars),
            "vocab_size": len(self.vocab),
            "num_texts": len(texts),
        }

    def encode(self, text: str, add_special_tokens: bool = True) -> list[int]:
        ids = []
        if add_special_tokens:
            ids.append(self.special_tokens["<bos>"])
        for ch in text:
            ids.append(self.vocab.get(ch, self.special_tokens["<unk>"]))
        if add_special_tokens:
            ids.append(self.special_tokens["<eos>"])
        return ids

    def decode(self, token_ids: list[int], skip_special_tokens: bool = False) -> str:
        chars = []
        for tid in token_ids:
            token = self.id_to_token.get(tid, "")
            if skip_special_tokens and token in self.special_tokens:
                continue
            chars.append(token)
        return "".join(chars)


class WordTokenizer(BaseTokenizer):
    """Word-level tokenizer.

    Splits text on whitespace and punctuation.
    Good for languages with clear word boundaries.
    """

    def __init__(self, vocab_size: int = 30000, special_tokens: dict[str, int] | None = None):
        super().__init__(vocab_size=vocab_size, special_tokens=special_tokens)
        self.tokenizer_type = "word"
        self.word_pattern = re.compile(r"\w+|[^\w\s]+")

    def train(self, texts: list[str]) -> None:
        """Build word vocabulary from corpus."""
        word_counts = Counter()
        for text in texts:
            tokens = self.word_pattern.findall(text)
            word_counts.update(tokens)

        # Sort by frequency (descending)
        sorted_words = [w for w, _ in word_counts.most_common()]

        next_id = max(self.special_tokens.values()) + 1
        for word in sorted_words:
            if next_id >= self.vocab_size:
                break
            if word not in self.vocab:
                self.vocab[word] = next_id
                next_id += 1

        self.id_to_token = {v: k for k, v in self.vocab.items()}
        self.training_stats = {
            "num_unique_words": len(word_counts),
            "vocab_size": len(self.vocab),
            "num_texts": len(texts),
        }

    def encode(self, text: str, add_special_tokens: bool = True) -> list[int]:
        tokens = self.word_pattern.findall(text)
        ids = []
        if add_special_tokens:
            ids.append(self.special_tokens["<bos>"])
        for token in tokens:
            ids.append(self.vocab.get(token, self.special_tokens["<unk>"]))
        if add_special_tokens:
            ids.append(self.special_tokens["<eos>"])
        return ids

    def decode(self, token_ids: list[int], skip_special_tokens: bool = False) -> str:
        tokens = []
        for tid in token_ids:
            token = self.id_to_token.get(tid, "")
            if skip_special_tokens and token in self.special_tokens:
                continue
            tokens.append(token)
        return " ".join(tokens)


class BytePairTokenizer(BaseTokenizer):
    """Byte Pair Encoding (BPE) tokenizer.

    Iteratively merges the most frequent adjacent byte pairs.
    Good balance between vocabulary size and sequence length.
    """

    def __init__(
        self,
        vocab_size: int = 8000,
        special_tokens: dict[str, int] | None = None,
        min_freq: int = 2,
    ):
        super().__init__(vocab_size=vocab_size, special_tokens=special_tokens)
        self.tokenizer_type = "bpe"
        self.min_freq = min_freq
        self.merges: list[tuple[str, str]] = []
        self.byte_to_id: dict[int, int] = {}

    def train(self, texts: list[str]) -> None:
        """Train BPE on corpus."""
        # Start with byte-level vocabulary (256 bytes)
        next_id = max(self.special_tokens.values()) + 1
        for i in range(256):
            byte_token = f"<byte_{i}>"
            self.vocab[byte_token] = next_id
            self.byte_to_id[i] = next_id
            next_id += 1

        self.id_to_token = {v: k for k, v in self.vocab.items()}

        # Count word frequencies
        word_freqs: Counter[str] = Counter()
        for text in texts:
            # Split into words
            words = re.findall(r"\S+", text)
            for word in words:
                word_freqs[word] += 1

        # Represent each word as tuple of byte tokens
        word_splits: dict[str, list[str]] = {}
        for word, freq in word_freqs.items():
            # Convert word to bytes, then to byte tokens
            byte_tokens = [f"<byte_{b}>" for b in word.encode("utf-8")]
            word_splits[word] = byte_tokens

        # Count adjacent pairs
        def get_pairs(split: list[str]) -> Counter[tuple[str, str]]:
            pairs = Counter()
            for i in range(len(split) - 1):
                pairs[(split[i], split[i + 1])] += 1
            return pairs

        pair_freqs: Counter[tuple[str, str]] = Counter()
        for word, split in word_splits.items():
            freq = word_freqs[word]
            pairs = get_pairs(split)
            for pair, count in pairs.items():
                pair_freqs[pair] += freq * count

        # Iteratively merge most frequent pairs
        while len(self.vocab) < self.vocab_size:
            # Filter pairs by min frequency
            valid_pairs = {p: c for p, c in pair_freqs.items() if c >= self.min_freq}
            if not valid_pairs:
                break

            # Get most frequent pair
            best_pair = max(valid_pairs, key=valid_pairs.get)
            self.merges.append(best_pair)

            # Create merged token
            merged_token = best_pair[0] + best_pair[1]
            if merged_token not in self.vocab:
                self.vocab[merged_token] = len(self.vocab)
                self.id_to_token[len(self.vocab) - 1] = merged_token

            # Update word splits
            for word in word_splits:
                split = word_splits[word]
                new_split = []
                i = 0
                while i < len(split):
                    if i < len(split) - 1 and split[i] == best_pair[0] and split[i + 1] == best_pair[1]:
                        new_split.append(merged_token)
                        i += 2
                    else:
                        new_split.append(split[i])
                        i += 1
                word_splits[word] = new_split

            # Recompute pair frequencies
            pair_freqs = Counter()
            for word, split in word_splits.items():
                freq = word_freqs[word]
                pairs = get_pairs(split)
                for pair, count in pairs.items():
                    pair_freqs[pair] += freq * count

        self.training_stats = {
            "vocab_size": len(self.vocab),
            "num_merges": len(self.merges),
            "min_freq": self.min_freq,
            "num_texts": len(texts),
        }

    def encode(self, text: str, add_special_tokens: bool = True) -> list[int]:
        """Encode text using learned BPE merges."""
        words = re.findall(r"\S+", text)
        ids = []
        if add_special_tokens:
            ids.append(self.special_tokens["<bos>"])

        for word in words:
            # Start with byte tokens
            split = [f"<byte_{b}>" for b in word.encode("utf-8")]

            # Apply merges in order
            for pair in self.merges:
                new_split = []
                i = 0
                while i < len(split):
                    if i < len(split) - 1 and split[i] == pair[0] and split[i + 1] == pair[1]:
                        new_split.append(pair[0] + pair[1])
                        i += 2
                    else:
                        new_split.append(split[i])
                        i += 1
                split = new_split

            # Convert to IDs
            for token in split:
                ids.append(self.vocab.get(token, self.special_tokens["<unk>"]))

        if add_special_tokens:
            ids.append(self.special_tokens["<eos>"])
        return ids

    def decode(self, token_ids: list[int], skip_special_tokens: bool = False) -> str:
        tokens = []
        for tid in token_ids:
            token = self.id_to_token.get(tid, "")
            if skip_special_tokens and token in self.special_tokens:
                continue
            tokens.append(token)

        # Reconstruct text from tokens
        # Byte tokens need to be converted back
        text = ""
        for token in tokens:
            if token.startswith("<byte_") and token.endswith(">"):
                try:
                    byte_val = int(token[6:-1])
                    text += bytes([byte_val]).decode("utf-8", errors="replace")
                except (ValueError, IndexError):
                    text += token
            else:
                text += token
        return text


class TokenizerRegistry:
    """Registry for trained tokenizers."""

    def __init__(self):
        self.tokenizers: dict[str, BaseTokenizer] = {}
        self.created_at = time.time()

    def register(self, tokenizer: BaseTokenizer) -> str:
        """Register a tokenizer and return its ID."""
        tid = tokenizer.tokenizer_id if hasattr(tokenizer, 'tokenizer_id') else f"tok-{time.time()}"
        self.tokenizers[tid] = tokenizer
        return tid

    def get(self, tokenizer_id: str) -> BaseTokenizer | None:
        """Get a tokenizer by ID."""
        return self.tokenizers.get(tokenizer_id)

    def list_tokenizers(self) -> list[dict[str, Any]]:
        """List all registered tokenizers."""
        return [
            {
                "tokenizer_id": tid,
                "name": t.name,
                "type": t.tokenizer_type,
                "vocab_size": t.get_vocab_size(),
                "created_at": t.created_at,
            }
            for tid, t in self.tokenizers.items()
        ]


# Global registry
_tokenizer_registry: TokenizerRegistry | None = None


def get_tokenizer_registry() -> TokenizerRegistry:
    """Get or create the global tokenizer registry."""
    global _tokenizer_registry
    if _tokenizer_registry is None:
        _tokenizer_registry = TokenizerRegistry()
    return _tokenizer_registry


__all__ = [
    "TokenizerSpec",
    "BaseTokenizer",
    "CharacterTokenizer",
    "WordTokenizer",
    "BytePairTokenizer",
    "TokenizerRegistry",
    "get_tokenizer_registry",
]
