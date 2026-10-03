"""Bounded research orchestrator (World Intelligence 1.0).

Pipeline (every stage bounded, every failure contained):

plan -> route -> retrieve -> normalize -> dedupe -> claims -> events
-> conflicts -> freshness -> synthesize -> verify -> answer

Built by composing existing systems: ResearchEngine (plan/credibility/
wiki), BrowserAgent (guarded fetch), live providers (geo/data),
SourceRegistry + EvidenceCache, claims/conflicts/freshness modules.
Nothing here browses on its own; budgets cap searches, pages, bytes,
time, and steps. Partial results + limitations are always reported.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

from .cache import EvidenceCache, cache_key
from .claims import Claim, extract_claims
from .conflicts import corroboration, dedupe_claims, detect_conflicts
from .freshness import assess
from .routing import route
from .sources import EvidenceItem, SourceRegistry, bounded_get, fetch_hn

MAX_SEARCHES = 4
MAX_EVIDENCE = 12
MAX_STEPS = 12
BUDGET_BYTES = 2 * 1024 * 1024
BUDGET_SECONDS = 90.0


@dataclass
class Answer:
    question: str = ""
    scope: str = "static"
    currentness: str = "static"
    summary: str = ""
    claims: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    freshness: dict[str, Any] = field(default_factory=dict)
    conclusion: str = ""
    uncertainty: list[str] = field(default_factory=list)
    provenance: list[dict[str, Any]] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    steps_used: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


EVENT_PREDICATES = ("released", "announced", "launched", "acquired",
                    "merged", "published", "discovered", "confirmed",
                    "delayed", "cancelled", "patched", "shipped",
                    "unveiled")


class Researcher:
    """Bounded evidence-driven research over registered sources."""

    def __init__(self, registry: SourceRegistry | None = None,
                 cache: EvidenceCache | None = None,
                 max_searches: int = MAX_SEARCHES,
                 max_evidence: int = MAX_EVIDENCE,
                 budget_s: float = BUDGET_SECONDS) -> None:
        self.registry = registry or SourceRegistry()
        self.cache = cache
        self.max_searches = max(1, max_searches)
        self.max_evidence = max(1, max_evidence)
        self.budget_s = max(1.0, budget_s)
        self.stats: dict[str, int] = {"searches": 0, "fetches": 0,
                                      "bytes": 0, "cache_hits": 0}

    def research(self, question: str, *,
                 active_project: str = "",
                 topics: list[str] | None = None,
                 now: float = 0.0) -> Answer:
        started = time.monotonic()
        stamp = now or time.time()
        routed = route(question, active_project=active_project,
                       topics=topics)
        answer = Answer(question=question[:500],
                        scope=routed["route"].lower(),
                        currentness=routed["time_scope"])
        if routed["route"] in ("STATIC", "CLARIFY"):
            answer.summary = ("No live retrieval needed: " +
                              "; ".join(routed["reasons"]))
            answer.limitations.append(
                "answered from static knowledge only")
            return answer
        evidence = self._gather(question, routed, answer, started,
                                stamp)
        if not evidence and answer.limitations:
            answer.summary = ("Could not retrieve current evidence: "
                              + "; ".join(answer.limitations))
            answer.uncertainty.append("unverified: no live evidence")
            return answer
        self._analyze(evidence, answer, routed, stamp)
        answer.steps_used = (self.stats["searches"]
                             + len(evidence))
        return answer

    def _gather(self, question: str, routed: dict[str, Any],
                answer: Answer, started: float,
                stamp: float) -> list[EvidenceItem]:
        evidence: list[EvidenceItem] = []
        domains = routed.get("domains", [])
        searches = 0

        def _budget_left() -> bool:
            return (time.monotonic() - started < self.budget_s
                    and self.stats["bytes"] < BUDGET_BYTES
                    and searches < self.max_searches
                    and len(evidence) < self.max_evidence)

        if "news" in domains:
            for source in self.registry.enabled("hn"):
                if not _budget_left():
                    break
                if not self.registry.can_fetch(source.source_id,
                                               stamp):
                    answer.limitations.append(
                        "hn rate-limited: using cache only")
                    continue
                key = cache_key("hn", question)
                cached = self.cache.get(key) if self.cache else None
                if cached is not None:
                    self.stats["cache_hits"] += 1
                    for item in cached["payload"].get("items", []):
                        evidence.append(EvidenceItem(**item))
                    continue
                try:
                    found = fetch_hn(top_n=10)
                    self.stats["searches"] += 1
                    searches += 1
                    self.registry.mark_fetched(source.source_id,
                                               stamp)
                    self.stats["bytes"] += sum(
                        len(e.text.encode("utf-8")) for e in found)
                    if self.cache is not None:
                        self.cache.put(
                            key, {"items": [e.to_dict()
                                            for e in found]},
                            source_id=source.source_id,
                            freshness_domain=
                            source.freshness_domain, at=stamp)
                    evidence.extend(found)
                except (ValueError, OSError) as exc:
                    answer.limitations.append(
                        f"hn unavailable: {type(exc).__name__}")
        if "reference" in domains and _budget_left():
            evidence.extend(self._wiki(question, routed, answer,
                                       stamp))
        return evidence[:self.max_evidence]

    def _wiki(self, question: str, routed: dict[str, Any],
              answer: Answer, stamp: float) -> list[EvidenceItem]:
        try:
            from ..research.engine import ResearchEngine
        except ImportError:
            answer.limitations.append("research engine unavailable")
            return []
        try:
            engine = ResearchEngine()
            hits = engine.wiki_search(question, count=3)
            self.stats["searches"] += 1
        except Exception as exc:
            answer.limitations.append(
                f"wikipedia unavailable: {type(exc).__name__}")
            return []
        out: list[EvidenceItem] = []
        for hit in hits:
            url = str(hit.get("url", ""))
            title = str(hit.get("title", ""))
            out.append(EvidenceItem(
                source_id="wiki", title=title, url=url,
                published_at=0.0, retrieved_at=stamp,
                text=f"{title}\n{hit.get('snippet', '')}".strip()))
        return out

    def _analyze(self, evidence: list[EvidenceItem], answer: Answer,
                 routed: dict[str, Any], stamp: float) -> None:
        entries: list[tuple[Claim, str]] = []
        for item in evidence:
            domain = "tech-news" if item.source_id.startswith("hn") \
                else "reference" if item.source_id == "wiki" \
                else "general"
            for claim in extract_claims(
                    item.text, source_id=item.source_id,
                    published_at=item.published_at,
                    evidence_ref=item.evidence_id):
                entries.append((claim, item.url or item.source_id))
            answer.provenance.append({
                "evidence_id": item.evidence_id,
                "source_id": item.source_id, "url": item.url,
                "title": item.title,
                "published_at": item.published_at,
                "retrieved_at": item.retrieved_at,
                "freshness": assess(
                    item.published_at, item.retrieved_at,
                    domain=domain, now=stamp),
                "injection_flags": item.injection_flags})
        groups = dedupe_claims(entries)
        answer.claims = [{
            "subject": g["claim"].subject,
            "predicate": g["claim"].predicate,
            "object": g["claim"].object,
            "qualifiers": g["claim"].qualifiers,
            "confidence": g["claim"].confidence,
            "evidence_count": len(g["urls"]),
            "corroboration": corroboration(g)} for g in groups[:20]]
        answer.conflicts = detect_conflicts(groups)
        answer.events = [{
            "subject": g["claim"].subject,
            "action": g["claim"].predicate,
            "object": g["claim"].object,
            "sources": len(g["urls"]),
            "qualified": bool(g["claim"].qualifiers)}
            for g in groups
            if g["claim"].predicate in EVENT_PREDICATES][:10]
        fresh_states = [p["freshness"]["state"]
                        for p in answer.provenance]
        answer.freshness = {
            "states": fresh_states,
            "newest": min(fresh_states) if fresh_states else "unknown",
            "evidence_count": len(evidence)}
        corroborated = sum(1 for c in answer.claims
                           if c["corroboration"]["corroborated"])
        parts = [f"{len(evidence)} evidence items",
                 f"{len(answer.claims)} claims "
                 f"({corroborated} corroborated)",
                 f"{len(answer.conflicts)} conflicts"]
        answer.summary = ("Evidence: " + "; ".join(parts) + ". " +
                          (answer.claims[0]["subject"] + " "
                           + answer.claims[0]["predicate"] + " "
                           + answer.claims[0]["object"]
                           if answer.claims else "no claims extracted"))
        if answer.conflicts:
            answer.uncertainty.append(
                f"{len(answer.conflicts)} conflicting claim(s) "
                "unresolved: see conflicts")
        if any(c["corroboration"]["possibly_syndicated"]
               for c in answer.claims):
            answer.uncertainty.append(
                "some evidence may be syndicated copies, not "
                "independent sources")
        if not any(c["corroboration"]["corroborated"]
                   for c in answer.claims):
            answer.uncertainty.append(
                "no claim corroborated by 2+ independent sources")
        answer.conclusion = (
            answer.summary
            + (f" Conflicts: {len(answer.conflicts)} unresolved."
               if answer.conflicts else " No conflicts detected."))


__all__ = ["Answer", "Researcher", "EVENT_PREDICATES", "MAX_SEARCHES",
           "MAX_EVIDENCE", "BUDGET_BYTES", "BUDGET_SECONDS"]
