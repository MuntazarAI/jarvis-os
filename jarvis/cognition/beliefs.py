"""Bounded belief model (4.4).

A belief is NOT a fact: it is a statement plus separate confidence,
evidence, and status. Later evidence changes confidence or status —
history is never rewritten; revisions append. Contradictory evidence
is preserved on the record, never silently resolved.

Statuses: ACTIVE | WEAKENED | CONTRADICTED | SUPERSEDED | EXPIRED.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

BELIEFS_FILENAME = "cognitive-beliefs.json"
MAX_BELIEFS = 500
MAX_EVIDENCE = 20
SCHEMA_VERSION = 1


class BeliefStatus(str, Enum):
    ACTIVE = "active"
    WEAKENED = "weakened"
    CONTRADICTED = "contradicted"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"


class BeliefError(ValueError):
    """Malformed belief or store misuse."""


def _utcnow() -> float:
    return time.time()


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def clamp_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        raise BeliefError(f"invalid confidence: {value!r}")
    if confidence != confidence or confidence in (float("inf"),
                                                  float("-inf")):
        raise BeliefError("confidence must be finite, not NaN")
    if not 0.0 <= confidence <= 1.0:
        raise BeliefError(f"confidence out of range: {value!r}")
    return confidence


@dataclass
class Belief:
    belief_id: str = field(default_factory=lambda: _new_id("blf"))
    statement: str = ""
    confidence: float = 0.5
    evidence_refs: list[str] = field(default_factory=list)
    source_refs: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=_utcnow)
    updated_at: float = field(default_factory=_utcnow)
    status: BeliefStatus = BeliefStatus.ACTIVE
    provenance: dict[str, Any] = field(default_factory=dict)
    contradictions: list[str] = field(default_factory=list)
    revision: int = 0
    expires_at: float = 0.0  # 0 = no expiry
    privacy_class: str = "local"
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if isinstance(self.status, str):
            try:
                self.status = BeliefStatus(self.status)
            except ValueError:
                raise BeliefError(f"invalid status: {self.status!r}")
        if not self.statement or len(self.statement) > 500:
            raise BeliefError("statement must be 1..500 chars")
        self.confidence = clamp_confidence(self.confidence)
        if len(self.evidence_refs) > MAX_EVIDENCE:
            raise BeliefError("too many evidence refs")
        if self.privacy_class not in ("public", "local", "sensitive",
                                      "private"):
            raise BeliefError(
                f"invalid privacy class: {self.privacy_class!r}")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Belief":
        if not isinstance(data, dict):
            raise BeliefError("belief must be an object")
        known = set(cls.__dataclass_fields__)
        clean = {k: v for k, v in data.items() if k in known}
        return cls(**clean)


class BeliefStore:
    """Durable bounded beliefs + source reliability. Atomic, merge-load."""

    def __init__(self, home: str | Path | None) -> None:
        self.home = Path(home) if home else None
        self._beliefs: dict[str, Belief] = {}
        self._reliability: dict[str, float] = {}
        self._loaded_mtime: float = 0.0
        self.load()

    @property
    def path(self) -> Path | None:
        if self.home is None:
            return None
        return self.home / BELIEFS_FILENAME

    # -- persistence -----------------------------------------------------

    def load(self) -> int:
        path = self.path
        self._loaded_mtime = 0.0
        if path is None or not path.exists():
            return 0
        try:
            self._loaded_mtime = path.stat().st_mtime
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return 0
        if not isinstance(raw, dict):
            return 0
        loaded = 0
        for bid, item in (raw.get("beliefs") or {}).items():
            if not isinstance(item, dict):
                continue
            try:
                belief = Belief.from_dict(item)
            except (BeliefError, TypeError):
                continue
            if belief.belief_id != bid:
                continue
            self._beliefs[bid] = belief
            loaded += 1
        for source, score in (raw.get("reliability") or {}).items():
            try:
                self._reliability[str(source)] = clamp_confidence(score)
            except BeliefError:
                continue
        return loaded

    def save(self) -> None:
        path = self.path
        if path is None:
            return
        payload = {"version": 1,
                   "beliefs": {bid: belief.to_dict()
                               for bid, belief in self._beliefs.items()},
                   "reliability": self._reliability}
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".cognitive-beliefs-",
                                       dir=str(path.parent))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, indent=2, sort_keys=True,
                              default=str)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp, path)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            try:
                self._loaded_mtime = path.stat().st_mtime
            except OSError:
                pass
        except OSError:
            pass

    def _maybe_reload(self) -> None:
        path = self.path
        if path is None:
            return
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return
        if mtime != self._loaded_mtime:
            self.load()

    def _prune(self) -> None:
        while len(self._beliefs) > MAX_BELIEFS:
            oldest = min(self._beliefs.values(),
                         key=lambda b: (b.updated_at, b.belief_id))
            del self._beliefs[oldest.belief_id]

    # -- beliefs -----------------------------------------------------------

    def upsert(self, statement: str, confidence: float, *,
               evidence: list[str] | None = None,
               sources: list[str] | None = None,
               provenance: dict[str, Any] | None = None,
               ttl_s: float = 0.0,
               privacy_class: str = "local") -> Belief:
        """Create, or revise the live belief with the same statement."""
        self._maybe_reload()
        if privacy_class not in ("public", "local", "sensitive",
                                 "private"):
            raise BeliefError(
                f"invalid privacy class: {privacy_class!r}")
        stamp = _utcnow()
        for belief in self._beliefs.values():
            if belief.statement == statement and belief.status in (
                    BeliefStatus.ACTIVE, BeliefStatus.WEAKENED,
                    BeliefStatus.CONTRADICTED):
                belief.confidence = clamp_confidence(confidence)
                for ref in (evidence or []):
                    if ref not in belief.evidence_refs:
                        belief.evidence_refs.append(ref[:128])
                del belief.evidence_refs[MAX_EVIDENCE:]
                for source in (sources or []):
                    if source not in belief.source_refs:
                        belief.source_refs.append(source[:80])
                belief.updated_at = stamp
                belief.revision += 1
                if provenance:
                    belief.provenance.update(
                        {str(k)[:80]: str(v)[:200]
                         for k, v in provenance.items()})
                if ttl_s and ttl_s > 0:
                    belief.expires_at = stamp + ttl_s
                self._prune()
                self.save()
                return belief
        belief = Belief(
            statement=statement[:500], confidence=confidence,
            evidence_refs=[str(r)[:128] for r in (evidence or [])]
            [:MAX_EVIDENCE],
            source_refs=[str(s)[:80] for s in (sources or [])],
            provenance={str(k)[:80]: str(v)[:200]
                        for k, v in (provenance or {}).items()},
            expires_at=(stamp + ttl_s) if ttl_s and ttl_s > 0 else 0.0,
            privacy_class=privacy_class)
        self._beliefs[belief.belief_id] = belief
        self._prune()
        self.save()
        return belief

    def get(self, belief_id: str) -> Belief | None:
        self._maybe_reload()
        return self._beliefs.get(belief_id)

    def set_status(self, belief_id: str, status: BeliefStatus, *,
                   reason: str = "", by: str = "") -> bool:
        self._maybe_reload()
        belief = self._beliefs.get(belief_id)
        if belief is None:
            return False
        if isinstance(status, str):
            status = BeliefStatus(status)
        belief.status = status
        belief.updated_at = _utcnow()
        belief.revision += 1
        if reason:
            belief.provenance[f"status_{status.value}"] = reason[:200]
        if by:
            belief.provenance["decided_by"] = by[:64]
        self.save()
        return True

    def contradict(self, belief_id: str, counter_evidence: str, *,
                   by: str = "") -> bool:
        """Attach counter-evidence; preserve both sides, mark status."""
        self._maybe_reload()
        belief = self._beliefs.get(belief_id)
        if belief is None:
            return False
        if counter_evidence not in belief.contradictions:
            belief.contradictions.append(counter_evidence[:200])
        belief.status = BeliefStatus.CONTRADICTED
        belief.updated_at = _utcnow()
        belief.revision += 1
        if by:
            belief.provenance["contradicted_by"] = by[:64]
        self.save()
        return True

    def adjust(self, belief_id: str, new_confidence: float, *,
               reason: str = "", evidence: str = "", by: str = "") -> bool:
        """Bounded confidence update with reason + evidence recorded."""
        self._maybe_reload()
        belief = self._beliefs.get(belief_id)
        if belief is None:
            return False
        old = belief.confidence
        belief.confidence = clamp_confidence(new_confidence)
        belief.updated_at = _utcnow()
        belief.revision += 1
        if evidence and evidence not in belief.evidence_refs:
            belief.evidence_refs.append(evidence[:128])
            del belief.evidence_refs[MAX_EVIDENCE:]
        belief.provenance["last_adjustment"] = (
            f"{old:.3f}->{belief.confidence:.3f} {reason}"[:200])
        if by:
            belief.provenance["adjusted_by"] = by[:64]
        self.save()
        return True

    def find(self, *, status: str = "", limit: int = 50,
             min_confidence: float = 0.0) -> list[Belief]:
        self._maybe_reload()
        out = [b for b in self._beliefs.values()
               if (not status or b.status.value == status)
               and b.confidence >= min_confidence]
        out.sort(key=lambda b: (b.updated_at, b.belief_id), reverse=True)
        return out[:max(1, limit)]

    def search(self, query: str, *, limit: int = 10,
               min_confidence: float = 0.0) -> list[Belief]:
        """Substring belief lookup for context enrichment. Bounded."""
        self._maybe_reload()
        terms = [t.lower() for t in str(query).split() if len(t) > 2][:8]
        if not terms:
            return []
        scored: list[tuple[int, Belief]] = []
        for belief in self._beliefs.values():
            if belief.confidence < min_confidence:
                continue
            text = belief.statement.lower()
            hits = sum(1 for term in terms if term in text)
            if hits:
                scored.append((hits, belief))
        scored.sort(key=lambda pair: (pair[0], pair[1].confidence,
                                      pair[1].updated_at), reverse=True)
        return [belief for _, belief in scored[:max(1, limit)]]

    def sweep_expired(self, at: float = 0.0) -> int:
        """Mark past-TTL beliefs EXPIRED. Returns count changed."""
        stamp = at or _utcnow()
        changed = 0
        self._maybe_reload()
        for belief in self._beliefs.values():
            if belief.status not in (BeliefStatus.ACTIVE,
                                     BeliefStatus.WEAKENED):
                continue
            if belief.expires_at and stamp >= belief.expires_at:
                belief.status = BeliefStatus.EXPIRED
                belief.updated_at = stamp
                belief.revision += 1
                changed += 1
        if changed:
            self.save()
        return changed

    # -- source reliability (weighting only, never authorization) ------------

    def reliability(self, source: str) -> float:
        self._maybe_reload()
        return self._reliability.get(source, 0.5)

    def note_reliability(self, source: str, score: float) -> None:
        self._reliability[str(source)[:80]] = clamp_confidence(score)
        self.save()


__all__ = [
    "Belief",
    "BeliefError",
    "BeliefStatus",
    "BeliefStore",
    "clamp_confidence",
]
