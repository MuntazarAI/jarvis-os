"""Structured claims (World Intelligence 1.0).

A Claim is (subject, predicate, object) plus the qualifiers the source
actually used — reportedly/alleged/may/planned/... Uncertainty is
preserved, never flattened. Every claim carries provenance (source id,
retrieved_at, published_at) and a confidence that callers must treat
as evidence weight, not truth.

Extraction is deterministic and rule-based (no model calls): sentence
split, qualifier scan, entity-ish subject detection, predicate verb
capture. It under-extracts by design — speculation stays text, only
confident SVO shapes become claims.
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

MAX_TEXT_CHARS = 2000
MAX_SUBJECT_CHARS = 200
MAX_PREDICATE_CHARS = 80
MAX_OBJECT_CHARS = 500

QUALIFIERS = (
    "reportedly", "allegedly", "supposedly", "expected", "planned",
    "according to", "estimated", "may", "might", "could",
    "rumored", "unconfirmed", "likely", "unlikely",
)

# Strong uncertainty markers: never become claims, stay as text.
SPECULATIVE = (
    "what if", "imagine if", "suppose", "hypothetically", "do you think",
    "should we", "please ", "click here", "subscribe",
)

_PREDICATE_HINTS = (
    "released", "announced", "launched", "acquired", "merged",
    "updated", "published", "discovered", "reported", "confirmed",
    "denied", "delayed", "cancelled", "fixed", "patched", "shipped",
    "unveiled", "revealed", "warned", "said", "stated", "claimed",
    "is", "are", "was", "were", "has", "have", "will",
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


@dataclass
class Claim:
    claim_id: str = field(
        default_factory=lambda: _new_id("claim"))
    subject: str = ""
    predicate: str = ""
    object: str = ""
    qualifiers: list[str] = field(default_factory=list)
    confidence: float = 0.5
    source_id: str = ""
    published_at: float = 0.0
    retrieved_at: float = field(default_factory=time.time)
    evidence_ref: str = ""

    def __post_init__(self) -> None:
        self.subject = str(self.subject or "")[:MAX_SUBJECT_CHARS]
        self.predicate = str(self.predicate or "")[:MAX_PREDICATE_CHARS]
        self.object = str(self.object or "")[:MAX_OBJECT_CHARS]
        if not self.subject or not self.predicate:
            raise ValueError("claim needs subject and predicate")
        try:
            confidence = float(self.confidence)
        except (TypeError, ValueError):
            raise ValueError("invalid confidence")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence out of range")
        self.confidence = confidence

    @property
    def qualified(self) -> bool:
        return bool(self.qualifiers)

    def key(self) -> str:
        """Dedupe key: normalized subject+predicate+object."""
        norm = lambda s: re.sub(r"\s+", " ", s.strip().lower())
        return "|".join((norm(self.subject), norm(self.predicate),
                         norm(self.object)))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def find_qualifiers(sentence: str) -> list[str]:
    lowered = sentence.lower()
    return [q for q in QUALIFIERS if q in lowered]


def _is_speculative(sentence: str) -> bool:
    lowered = sentence.lower()
    return any(marker in lowered for marker in SPECULATIVE)


def extract_claims(text: str, *, source_id: str,
                   published_at: float = 0.0,
                   evidence_ref: str = "",
                   base_confidence: float = 0.5) -> list[Claim]:
    """Deterministic SVO-lite extraction. Returns claims only for
    sentences with a recognizable (Entity-ish subject, hinted verb,
    object) shape; everything else stays unclaimed text."""
    claims: list[Claim] = []
    if not text or not source_id:
        return claims
    for raw in _SENTENCE_SPLIT.split(text.strip())[:50]:
        sentence = " ".join(raw.split())
        if len(sentence) < 12 or len(sentence) > 500:
            continue
        if _is_speculative(sentence):
            continue
        lowered = sentence.lower()
        predicate = next((hint for hint in _PREDICATE_HINTS
                          if f" {hint} " in f" {lowered} "), "")
        if not predicate:
            continue
        head, _, tail = sentence.partition(predicate)
        # Subject: trailing run of the head (max 6 words), requiring
        # at least one capitalized anchor so bare verb phrases and
        # pronouns alone never become subjects.
        words = head.strip().split()
        candidate = " ".join(words[-6:]).strip(" ,")
        has_anchor = any(w[:1].isupper() for w in candidate.split())
        subject = candidate if has_anchor else ""
        obj = tail.strip().strip(" .")[:MAX_OBJECT_CHARS]
        if not subject or not obj:
            continue
        qualifiers = find_qualifiers(sentence)
        confidence = base_confidence - (0.15 if qualifiers else 0.0)
        try:
            claims.append(Claim(
                subject=subject, predicate=predicate, object=obj,
                qualifiers=qualifiers,
                confidence=max(0.05, confidence),
                source_id=source_id[:120],
                published_at=float(published_at or 0.0),
                evidence_ref=evidence_ref[:120]))
        except ValueError:
            continue
        if len(claims) >= 20:
            break
    return claims


__all__ = ["Claim", "find_qualifiers", "extract_claims", "QUALIFIERS",
           "MAX_TEXT_CHARS"]
