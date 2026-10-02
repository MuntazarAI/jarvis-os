"""Shared task blackboard: structured state, not prompt-passing.

Sections mirror the mission spec: goal/constraints/state/observations/
hypotheses/evidence/plans/actions/results/conflicts/decisions/verification/
final answer. Every entry carries author/timestamp/provenance/confidence/
lifecycle; corrections supersede instead of deleting.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..core.types import new_id, now

SECTIONS = ("goal", "constraints", "state", "observations", "hypotheses",
            "evidence", "plans", "actions", "results", "conflicts",
            "decisions", "verification", "answer")


class EntryState(str, Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    RETRACTED = "retracted"


@dataclass
class BoardEntry:
    section: str
    content: Any
    author: str
    provenance: str = ""
    confidence: float = 0.5
    state: EntryState = EntryState.ACTIVE
    supersedes: str = ""
    entry_id: str = field(default_factory=lambda: new_id("bb"))
    timestamp: float = field(default_factory=now)
    version: int = 1
    links: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = dict(self.__dict__)
        data["state"] = self.state.value
        return data


class VersionConflict(Exception):
    """Raised when a correction targets a stale entry version."""


class Blackboard:
    def __init__(self, goal: str = "") -> None:
        self.goal = goal
        self._entries: dict[str, BoardEntry] = {}
        self._order: list[str] = []

    def write(self, section: str, content: Any, author: str,
              provenance: str = "", confidence: float = 0.5) -> BoardEntry:
        if section not in SECTIONS:
            raise ValueError(f"unknown section: {section}")
        entry = BoardEntry(section=section, content=content, author=author,
                           provenance=provenance, confidence=confidence)
        self._entries[entry.entry_id] = entry
        self._order.append(entry.entry_id)
        return entry

    def correct(self, entry_id: str, content: Any, author: str,
                provenance: str = "",
                expected_version: int | None = None) -> BoardEntry:
        old = self._entries.get(entry_id)
        if old is None:
            raise KeyError(f"unknown entry: {entry_id}")
        if old.state != EntryState.ACTIVE:
            raise VersionConflict(
                f"entry {entry_id} is {old.state.value}, not active")
        if expected_version is not None and old.version != expected_version:
            raise VersionConflict(
                f"entry {entry_id} is at version {old.version}, "
                f"caller expected {expected_version}")
        old.state = EntryState.SUPERSEDED
        new = self.write(old.section, content, author, provenance,
                         confidence=old.confidence)
        new.supersedes = entry_id
        new.version = old.version + 1
        return new

    def current(self, entry_id: str) -> BoardEntry | None:
        """Follow the supersession chain forward to the live entry.

        History is never deleted: superseded entries remain readable.
        """
        entry = self._entries.get(entry_id)
        if entry is None:
            return None
        seen = {entry_id}
        while True:
            child = next((e for e in self._entries.values()
                          if e.supersedes == entry.entry_id
                          and e.entry_id not in seen), None)
            if child is None:
                return entry
            seen.add(child.entry_id)
            entry = child
        return entry

    def link_evidence(self, entry_id: str, relation: str, target: str,
                      author: str) -> BoardEntry:
        """Link entries: supports / refutes / derives. Conflicts stay visible."""
        if relation not in ("supports", "refutes", "derives"):
            raise ValueError(f"unknown relation: {relation}")
        entry = self._entries.get(entry_id)
        if entry is None:
            raise KeyError(f"unknown entry: {entry_id}")
        entry.links.append({"relation": relation, "target": target,
                            "author": author, "at": now()})
        return entry

    def evidence_for(self, subject: str) -> dict[str, list[dict[str, Any]]]:
        """Supporting vs conflicting evidence for a subject. Both stay visible."""
        supporting, conflicting = [], []
        for entry in self.read(active_only=False):
            text = str(entry.content)
            if subject.lower() not in text.lower():
                continue
            record = entry.to_dict()
            if entry.state != EntryState.ACTIVE:
                record["note"] = f"superseded/retracted but preserved"
            refs = [l for l in entry.links if l["relation"] == "refutes"]
            (conflicting if refs else supporting).append(record)
        for entry in self.read(active_only=False):
            for link in entry.links:
                if link["relation"] == "refutes" and subject.lower() in str(
                        self._entries.get(link["target"], "")).lower():
                    conflicting.append(entry.to_dict())
        return {"supporting": supporting, "conflicting": conflicting}

    def retract(self, entry_id: str) -> bool:
        entry = self._entries.get(entry_id)
        if entry is None:
            return False
        entry.state = EntryState.RETRACTED
        return True

    def read(self, section: str = "", active_only: bool = True) -> list[BoardEntry]:
        out = [self._entries[eid] for eid in self._order]
        if section:
            out = [e for e in out if e.section == section]
        if active_only:
            out = [e for e in out if e.state == EntryState.ACTIVE]
        return out

    def conflicts(self) -> list[dict[str, Any]]:
        """Pairs of active claims that contradict (explicit contradiction
        entries + opposing verification verdicts on the same subject)."""
        found: list[dict[str, Any]] = []
        claims = [e for e in self.read("results") if isinstance(e.content, dict)]
        for i, first in enumerate(claims):
            for second in claims[i + 1:]:
                if (first.content.get("subject") and
                        first.content.get("subject") == second.content.get("subject")
                        and first.content.get("verdict") != second.content.get("verdict")):
                    found.append({"a": first.to_dict(), "b": second.to_dict(),
                                  "subject": first.content["subject"]})
        return found

    def summary(self) -> dict[str, Any]:
        return {"goal": self.goal,
                "sections": {s: len(self.read(s)) for s in SECTIONS},
                "conflicts": len(self.conflicts())}

    def to_dict(self) -> dict[str, Any]:
        return {"goal": self.goal,
                "entries": [self._entries[eid].to_dict() for eid in self._order]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Blackboard":
        board = cls(goal=data.get("goal", ""))
        for raw in data.get("entries", []):
            entry = BoardEntry(
                section=raw["section"], content=raw["content"],
                author=raw["author"], provenance=raw.get("provenance", ""),
                confidence=raw.get("confidence", 0.5),
                state=EntryState(raw.get("state", "active")),
                supersedes=raw.get("supersedes", ""),
                entry_id=raw.get("entry_id", new_id("bb")),
                timestamp=raw.get("timestamp", now()),
                version=int(raw.get("version", 1)),
                links=[dict(link) for link in raw.get("links", [])])
            board._entries[entry.entry_id] = entry
            board._order.append(entry.entry_id)
        return board
