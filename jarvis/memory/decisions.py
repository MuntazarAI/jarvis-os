"""Memory 2.0: decisions, preferences, corrections with strength tracking."""

from __future__ import annotations

from typing import Any

from ..core.types import now


class DecisionLog:
    """Records decisions with reasons and rejected alternatives."""

    def __init__(self, palace: Any) -> None:
        self.palace = palace

    def decide(self, decision: str, reasons: list[str] | None = None,
               alternatives: list[str] | None = None,
               room: str = "Future Plans") -> Any:
        text = f"DECISION: {decision}"
        if reasons:
            text += " because " + "; ".join(reasons[:3])
        if alternatives:
            text += " (rejected: " + "; ".join(alternatives[:3]) + ")"
        return self.palace.remember(text, tier="long_term", room=room,
                                    kind="decision", source="user",
                                    confidence=0.85, importance=0.8,
                                    metadata={"decided_at": now()})

    def decisions(self, limit: int = 20) -> list[Any]:
        return [m for m in self.palace.all(tier="long_term", limit=500)
                if m.kind == "decision"][:limit]

    def recall(self, topic: str, limit: int = 5) -> list[Any]:
        return [m for m, _ in self.palace.search(topic, limit=limit * 3)
                if m.kind == "decision"][:limit]


class PreferenceStore:
    """Likes/dislikes with reinforcement: repeats strengthen, corrections flip."""

    def __init__(self, palace: Any) -> None:
        self.palace = palace

    def prefer(self, text: str, polarity: str = "like") -> Any:
        existing = self.find(text)
        if existing is None:
            return self.palace.remember(
                f"PREFERENCE ({polarity}): {text}", tier="long_term",
                room="Home", kind="preference", source="user",
                confidence=0.8, importance=0.75,
                metadata={"polarity": polarity})
        if existing.metadata.get("polarity") != polarity:
            # Polarity flip: replace so the old leaning cannot resurface.
            self.palace.forget(existing.id)
            return self.prefer(text, polarity)
        # Repeat: strengthen.
        self.palace.update(existing.id,
                           importance=min(1.0, existing.importance + 0.1))
        return self.palace.get(existing.id)

    def find(self, text: str) -> Any | None:
        import re
        keywords = set(re.findall(r"[a-z]{4,}", text.lower()))
        best: Any | None = None
        best_score = 0
        for mem in self.palace.all(tier="long_term", limit=500):
            if mem.kind != "preference":
                continue
            overlap = len(keywords & set(re.findall(r"[a-z]{4,}", mem.content.lower())))
            if overlap > best_score:
                best, best_score = mem, overlap
        return best if best_score >= 2 else None

    def all(self) -> list[Any]:
        return [m for m in self.palace.all(tier="long_term", limit=500)
                if m.kind == "preference"]

    def correct(self, old: str, new: str, polarity: str = "like") -> Any:
        found = self.find(old)
        if found:
            self.palace.forget(found.id)
        return self.prefer(new, polarity)
