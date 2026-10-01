"""Conversation runtime: sessions, timeouts, compression, ambiguity handling."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from .core.types import new_id, now
from .inference.analysis import QuestionStrategy
from .memory.consolidation import summarize_text


@dataclass
class Turn:
    input: str
    response: str
    intent: str
    at: float = field(default_factory=now)

    def to_dict(self) -> dict[str, Any]:
        return {"input": self.input, "response": self.response,
                "intent": self.intent, "at": self.at}


@dataclass
class ConversationSession:
    session_id: str = field(default_factory=lambda: new_id("conv"))
    turns: list[Turn] = field(default_factory=list)
    summary: str = ""
    created: float = field(default_factory=now)
    last_active: float = field(default_factory=now)
    timeout_s: float = 900.0
    max_turns: int = 100

    def add(self, text: str, response: str, intent: str) -> Turn:
        turn = Turn(input=text, response=response, intent=intent)
        self.turns.append(turn)
        self.last_active = now()
        if len(self.turns) > self.max_turns:
            self.compress(keep=20)
        return turn

    @property
    def expired(self) -> bool:
        return now() - self.last_active >= self.timeout_s

    def reset(self) -> None:
        self.turns.clear()
        self.summary = ""
        self.last_active = now()

    def compress(self, keep: int = 20) -> str:
        """Fold older turns into a rolling summary, keep recent verbatim."""
        if len(self.turns) <= keep:
            return self.summary
        older = self.turns[:-keep]
        material = [f"User: {t.input} JARVIS: {t.response}" for t in older]
        addition = summarize_text(material, limit=3)
        self.summary = (self.summary + " " + addition).strip() if self.summary else addition
        self.turns = self.turns[-keep:]
        return self.summary

    def context(self, recent: int = 6) -> dict[str, Any]:
        return {"summary": self.summary,
                "recent": [t.to_dict() for t in self.turns[-recent:]],
                "turns": len(self.turns)}

    def history(self) -> list[dict[str, Any]]:
        return [t.to_dict() for t in self.turns]


class ConversationManager:
    def __init__(self, timeout_s: float = 900.0) -> None:
        self.timeout_s = timeout_s
        self._sessions: dict[str, ConversationSession] = {}
        self._lock = threading.RLock()
        self.questions = QuestionStrategy()

    def get_or_create(self, session_id: str = "") -> ConversationSession:
        with self._lock:
            existing = self._sessions.get(session_id) if session_id else None
            if existing and not existing.expired:
                return existing
            session = ConversationSession(timeout_s=self.timeout_s)
            self._sessions[session.session_id] = session
            return session

    def get(self, session_id: str) -> ConversationSession | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session and session.expired:
                del self._sessions[session_id]
                return None
            return session

    def reset(self, session_id: str) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return False
            session.reset()
            return True

    def prune(self) -> int:
        with self._lock:
            dead = [sid for sid, s in self._sessions.items() if s.expired]
            for sid in dead:
                del self._sessions[sid]
            return len(dead)

    def active(self) -> list[str]:
        self.prune()
        with self._lock:
            return list(self._sessions)

    def turn(self, jarvis: Any, session_id: str, text: str) -> dict[str, Any]:
        """One managed turn: cycle → record → clarify when ambiguous."""
        session = self.get_or_create(session_id)
        result = jarvis.cycle_once(text)
        session.add(text, result.response, result.intent)
        response = result.response
        if self.needs_clarification(result.intent,
                                    result.confidence.numeric
                                    if hasattr(result.confidence, "numeric")
                                    else 0.5,
                                    response):
            question = self.clarify("carry out your request",
                                    "what you want me to do",
                                    [text])
            response = response + " " + question
        return {"response": response, "intent": result.intent,
                "session": session.session_id,
                "context": session.context(),
                "confidence": result.confidence.value}

    def needs_clarification(self, intent: str, confidence: float,
                            response: str) -> bool:
        """Ambiguous-command detection: low-confidence statement that ended
        in a generic 'what would you like' deflection."""
        return (intent == "statement" and confidence < 0.55
                and "What would you like" in response)

    def clarify(self, goal: str, unknown: str, known: list[str]) -> str:
        plan = self.questions.generate(goal, [unknown], known)
        return plan["best_question"]
