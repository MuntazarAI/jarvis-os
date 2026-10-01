"""Memory consolidation: dedup, merge, summarize, archive, staleness."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core.config import JarvisConfig
from ..core.types import Confidence, now
from .palace import MemoryPalace, cosine, tokenize


@dataclass
class ConsolidationReport:
    reviewed: int = 0
    duplicates: int = 0
    merged: int = 0
    summarized: int = 0
    archived: int = 0
    expired: int = 0
    contradictions: list[dict[str, Any]] = field(default_factory=list)
    facts_extracted: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "reviewed": self.reviewed,
            "duplicates": self.duplicates,
            "merged": self.merged,
            "summarized": self.summarized,
            "archived": self.archived,
            "expired": self.expired,
            "contradictions": self.contradictions,
            "facts_extracted": self.facts_extracted,
        }


def summarize_text(items: list[str], limit: int = 3) -> str:
    """Extract the most representative sentences without an LLM."""
    if not items:
        return ""
    sentences: list[str] = []
    for text in items:
        for part in text.replace("\n", " ").split(". "):
            part = part.strip()
            if len(part) > 15:
                sentences.append(part if part.endswith(".") else part + ".")
    if len(sentences) <= limit:
        return " ".join(sentences)
    freq: dict[str, int] = {}
    for s in sentences:
        for tok in set(tokenize(s)):
            freq[tok] = freq.get(tok, 0) + 1
    scored = sorted(
        sentences,
        key=lambda s: sum(freq.get(t, 0) for t in tokenize(s)) / max(1, len(tokenize(s))),
        reverse=True,
    )
    return " ".join(scored[:limit])


class MemoryConsolidator:
    """Runs the periodic consolidation pass over the palace."""

    def __init__(self, palace: MemoryPalace, config: JarvisConfig | None = None) -> None:
        self.palace = palace
        self.config = config or JarvisConfig()

    def run(self, room: str | None = None, tier: str | None = None) -> ConsolidationReport:
        report = ConsolidationReport()
        mems = self.palace.all(tier=tier, room=room, limit=2000)
        report.reviewed = len(mems)

        report.duplicates += self._dedup(mems, report)
        report.merged += self._merge_similar(mems, report)
        report.summarized += self._summarize_tier(report)
        report.archived += self._archive_cold(report)
        report.expired += self._expire_stale()
        report.contradictions = self._detect_contradictions()
        report.facts_extracted = self._extract_facts(report)
        return report

    # -- dedup -----------------------------------------------------------
    def _dedup(self, mems: list, report: ConsolidationReport) -> int:
        threshold = self.config.memory.dedup_similarity
        seen: dict[str, str] = {}
        removed = 0
        for mem in sorted(mems, key=lambda m: -m.importance):
            key = " ".join(sorted(tokenize(mem.content)[:40]))
            if key in seen:
                self.palace.archive(mem.id, reason="duplicate")
                report.duplicates += 1
                removed += 1
            else:
                seen[key] = mem.id
        return removed

    # -- merge -----------------------------------------------------------
    def _merge_similar(self, mems: list, report: ConsolidationReport) -> int:
        threshold = self.config.memory.dedup_similarity
        merged = 0
        handled: set[str] = set()
        for i, a in enumerate(mems):
            if a.id in handled:
                continue
            group = [a.id]
            for b in mems[i + 1:]:
                if b.id in handled:
                    continue
                if a.room != b.room:
                    continue
                if cosine(a.vector, b.vector) >= threshold:
                    group.append(b.id)
                    handled.add(b.id)
            if len(group) > 1:
                out = self.palace.merge(group)
                if out:
                    handled.add(out.id)
                    merged += 1
                    report.merged += 1
            handled.add(a.id)
        return merged

    # -- summarize -------------------------------------------------------
    def _summarize_tier(self, report: ConsolidationReport) -> int:
        count = 0
        by_room: dict[str, list] = {}
        for mem in self.palace.all(tier="episodic", limit=1000):
            by_room.setdefault(mem.room, []).append(mem)
        for room, mems in by_room.items():
            if len(mems) < 5:
                continue
            summary = summarize_text([m.content for m in mems])
            if summary:
                self.palace.compress([m.id for m in mems], f"[summary:{room}] {summary}")
                count += 1
                report.summarized += 1
        return count

    # -- archive / expire ------------------------------------------------
    def _archive_cold(self, report: ConsolidationReport) -> int:
        cutoff_days = self.config.memory.archive_after_days
        stale = [m for m in self.palace.all(limit=3000) if m.room in ("Archive", "Trash")]
        stale += self.palace.stale(cutoff_days)
        count = 0
        for mem in stale:
            if mem.tier in ("working", "conversation", "observation"):
                continue
            if mem.importance >= 0.9:
                continue
            if self.palace.archive(mem.id, reason="cold-storage"):
                count += 1
                report.archived += 1
        return count

    def _expire_stale(self) -> int:
        due = self.palace.expired_since(now())
        for mem in due:
            self.palace.expire(mem.id)
        return len(due)

    # -- contradictions / facts -----------------------------------------
    def _detect_contradictions(self) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        for a, b in self.palace.contradictions_candidates():
            found.append(
                {
                    "a": a.content,
                    "b": b.content,
                    "a_id": a.id,
                    "b_id": b.id,
                    "shared_entities": sorted(set(a.related_entities) & set(b.related_entities)),
                }
            )
        return found

    def _extract_facts(self, report: ConsolidationReport) -> list[str]:
        """Promote high-confidence, highly-accessed episodic notes to semantic facts."""
        facts: list[str] = []
        for mem in self.palace.all(tier="episodic", limit=500):
            score = Confidence.from_score(mem.confidence)
            if score in (Confidence.MEDIUM, Confidence.HIGH) and mem.importance >= 0.7:
                facts.append(mem.content)
                self.palace.remember(
                    mem.content,
                    tier="semantic",
                    room=mem.room,
                    kind="fact",
                    source="consolidation",
                    confidence=mem.confidence,
                    importance=mem.importance,
                    related_entities=mem.related_entities,
                    metadata={"promoted_from": mem.id},
                )
        return facts
