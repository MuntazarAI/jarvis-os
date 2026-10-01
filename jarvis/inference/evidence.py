"""Evidence engine: collection, classification, provenance, conflicts, strength."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from ..core.types import Evidence, Modality, Observation, Provenance, new_id, now


SOURCE_RELIABILITY = {
    "direct_measurement": 0.95,
    "system_log": 0.85,
    "user_stated": 0.7,
    "file": 0.8,
    "sensor": 0.75,
    "inference": 0.4,
    "hearsay": 0.3,
    "unknown": 0.4,
}


@dataclass
class EvidenceItem:
    evidence: Evidence
    strength: float = 0.5
    expires_at: float | None = None
    related: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = self.evidence.to_dict()
        data["strength"] = self.strength
        return data


class EvidenceEngine:
    """Builds an evidence graph with explicit provenance and conflicts."""

    def __init__(self, expire_seconds: float = 86400.0) -> None:
        self.items: dict[str, EvidenceItem] = {}
        self.expire_seconds = expire_seconds

    # -- collection ------------------------------------------------------
    def collect(
        self,
        summary: str,
        source: str = "user",
        modality: str = Modality.TEXT.value,
        locator: str = "",
        reliability: float | None = None,
        expires_in: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Evidence:
        prov = Provenance(
            source=source,
            modality=modality,
            locator=locator,
            reliability=SOURCE_RELIABILITY.get(source, reliability)
            if reliability is None
            else reliability,
        )
        ev = Evidence(
            summary=summary,
            reliability=prov.reliability,
            provenance=prov,
            expires_at=now() + (expires_in if expires_in is not None else self.expire_seconds),
            metadata=metadata or {},
        )
        self.items[ev.evidence_id] = EvidenceItem(
            evidence=ev,
            strength=self.strength(ev),
            expires_at=ev.expires_at,
        )
        return ev

    def from_observation(self, obs: Observation) -> Evidence:
        return self.collect(
            obs.content,
            source=obs.source,
            modality=obs.modality,
            locator=obs.observation_id,
            reliability=obs.confidence,
            metadata=obs.metadata,
        )

    # -- classification --------------------------------------------------
    def classify(self, text: str) -> str:
        lowered = text.lower()
        if re.search(r"\b(because|therefore|caused by|due to|so that)\b", lowered):
            return "causal"
        if re.search(r"\b(always|never|usually|often|every time|tend to)\b", lowered):
            return "pattern"
        if re.search(r"\b(will|would|might|could|should)\b", lowered):
            return "predictive"
        if re.search(r"\b(i think|i believe|in my opinion|probably|maybe)\b", lowered):
            return "subjective"
        return "descriptive"

    def strength(self, ev: Evidence) -> float:
        """Blend provenance reliability, freshness and independence."""
        age = max(0.0, now() - ev.timestamp)
        freshness = 1.0 if age < 300 else (0.5 if age < 86400 else 0.2)
        return round(min(1.0, 0.7 * ev.reliability + 0.3 * freshness), 4)

    def refresh_strengths(self) -> None:
        for item in self.items.values():
            item.strength = self.strength(item.evidence)

    # -- queries ---------------------------------------------------------
    def supporting(self, claim: str) -> list[Evidence]:
        return [i.evidence for i in self.items.values() if claim.lower() in i.evidence.supports]

    def contradicting(self, claim: str) -> list[Evidence]:
        return [i.evidence for i in self.items.values() if claim.lower() in i.evidence.contradicts]

    def link(self, ev_id: str, supports: str | None = None, contradicts: str | None = None) -> None:
        item = self.items.get(ev_id)
        if not item:
            return
        if supports:
            item.evidence.supports.append(supports)
        if contradicts:
            item.evidence.contradicts.append(contradicts)

    def conflicts(self) -> list[tuple[Evidence, Evidence, str]]:
        """Pairs where one item supports a claim another contradicts."""
        found: list[tuple[Evidence, Evidence, str]] = []
        claims: dict[str, list[str]] = {}
        for item in self.items.values():
            for claim in item.evidence.supports:
                claims.setdefault(claim, []).append(item.evidence.evidence_id)
        for claim, supporting_ids in claims.items():
            contradicting_ids = [
                eid
                for eid, item in self.items.items()
                if claim in item.evidence.contradicts
            ]
            for sup_id in supporting_ids:
                for con_id in contradicting_ids:
                    if sup_id == con_id:
                        continue
                    found.append(
                        (self.items[sup_id].evidence, self.items[con_id].evidence, claim)
                    )
        return found

    def missing_evidence(self, hypothesis_supports: list[str]) -> list[str]:
        present = {s for i in self.items.values() for s in i.evidence.supports}
        return [h for h in hypothesis_supports if h not in present]

    def expired(self) -> list[Evidence]:
        ts = now()
        return [i.evidence for i in self.items.values() if i.evidence.expires_at and i.evidence.expires_at <= ts]

    def purge_expired(self) -> int:
        stale = [eid for eid, i in self.items.items() if i.evidence.expires_at and i.evidence.expires_at <= now()]
        for eid in stale:
            del self.items[eid]
        return len(stale)

    def sources(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for item in self.items.values():
            src = item.evidence.provenance.source
            out[src] = out.get(src, 0) + 1
        return out

    def credibility(self, source: str) -> float:
        return SOURCE_RELIABILITY.get(source, 0.4)

    def separated(self) -> tuple[list[str], list[str]]:
        """Explicit split between recorded fact and interpretation."""
        facts: list[str] = []
        interpretations: list[str] = []
        for item in self.items.values():
            ev = item.evidence
            if ev.provenance.reliability >= 0.7:
                facts.append(ev.summary)
            else:
                interpretations.append(ev.summary)
        return facts, interpretations

    def stats(self) -> dict[str, Any]:
        self.refresh_strengths()
        return {
            "count": len(self.items),
            "sources": self.sources(),
            "conflicts": len(self.conflicts()),
            "expired": len(self.expired()),
            "avg_strength": round(
                sum(i.strength for i in self.items.values()) / len(self.items), 4
            )
            if self.items
            else 0.0,
        }
