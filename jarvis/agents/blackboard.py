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

    def to_dict(self) -> dict[str, Any]:
        data = dict(self.__dict__)
        data["state"] = self.state.value
        return data


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
                provenance: str = "") -> BoardEntry:
        old = self._entries.get(entry_id)
        if old is None:
            raise KeyError(f"unknown entry: {entry_id}")
        old.state = EntryState.SUPERSEDED
        new = self.write(old.section, content, author, provenance,
                         confidence=old.confidence)
        new.supersedes = entry_id
        return new

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
                timestamp=raw.get("timestamp", now()))
            board._entries[entry.entry_id] = entry
            board._order.append(entry.entry_id)
        return board
