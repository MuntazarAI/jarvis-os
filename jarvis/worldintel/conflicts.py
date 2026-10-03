"""Deduplication + corroboration + contradiction (World Intelligence).

Three related but distinct operations over claims from many sources:

- dedupe: same normalized claim from several URLs -> one claim, many
  evidence refs (source multiplicity preserved).
- corroborate: independent sources (distinct registrable domains, not
  syndicated copies) supporting one claim.
- contradict: same subject+predicate with materially different objects
  -> explicit conflict; NEVER silently resolved.

Syndication heuristic: same claim text from the same domain family or
with matching canonical URLs counts once, flagged syndicated.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from .claims import Claim


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().lstrip("www.")
    except ValueError:
        return ""


def _base_domain(domain: str) -> str:
    parts = domain.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else domain


def dedupe_claims(entries: list[tuple[Claim, str]]) -> list[dict[str, Any]]:
    """Merge identical claim keys. Returns groups with the claim,
    evidence urls, and source ids. Order: first-seen."""
    groups: dict[str, dict[str, Any]] = {}
    for claim, url in entries:
        key = claim.key()
        group = groups.get(key)
        if group is None:
            groups[key] = {"claim": claim, "urls": [url],
                           "source_ids": [claim.source_id]}
        else:
            if url not in group["urls"]:
                group["urls"].append(url)
            if claim.source_id not in group["source_ids"]:
                group["source_ids"].append(claim.source_id)
    return list(groups.values())


def corroboration(group: dict[str, Any]) -> dict[str, Any]:
    """Independent-source analysis for one deduped claim group."""
    urls: list[str] = group.get("urls", [])
    domains = [_domain(u) for u in urls]
    independent = sorted({_base_domain(d) for d in domains if d})
    syndicated = len(urls) - len(
        {u.split("?")[0] for u in urls}) > 0 or len(urls) > len(
        independent)
    return {"claim_key": group["claim"].key(),
            "evidence_count": len(urls),
            "independent_sources": independent,
            "independent_count": len(independent),
            "possibly_syndicated": syndicated,
            "corroborated": len(independent) >= 2}


def _objects_differ(first: str, second: str) -> bool:
    norm = lambda s: set(re.findall(r"[a-z0-9]+", s.lower()))
    first_words, second_words = norm(first), norm(second)
    if not first_words or not second_words:
        return True
    union = first_words | second_words
    return len(first_words & second_words) / len(union) < 0.5


def detect_conflicts(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Same subject+predicate, materially different objects ->
    explicit conflict with both sides' evidence attached."""
    by_sp: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for group in groups:
        claim = group["claim"]
        norm = lambda s: re.sub(r"\s+", " ", s.strip().lower())
        by_sp.setdefault((norm(claim.subject),
                          norm(claim.predicate)), []).append(group)
    conflicts: list[dict[str, Any]] = []
    for (subject, predicate), members in by_sp.items():
        if len(members) < 2:
            continue
        for i, first in enumerate(members):
            for second in members[i + 1:]:
                obj_a = first["claim"].object
                obj_b = second["claim"].object
                if _objects_differ(obj_a, obj_b):
                    conflicts.append({
                        "subject": subject, "predicate": predicate,
                        "status": "conflicting",
                        "side_a": {"object": obj_a,
                                   "urls": first["urls"],
                                   "qualifiers": first[
                                       "claim"].qualifiers},
                        "side_b": {"object": obj_b,
                                   "urls": second["urls"],
                                   "qualifiers": second[
                                       "claim"].qualifiers},
                    })
    return conflicts


__all__ = ["dedupe_claims", "corroboration", "detect_conflicts"]
