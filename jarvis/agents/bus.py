"""Typed agent message bus. 16 message types, full provenance, replayable."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from ..core.types import new_id, now


class MessageType(str, Enum):
    REQUEST = "request"
    OBSERVATION = "observation"
    HYPOTHESIS = "hypothesis"
    PLAN = "plan"
    ACTION_REQUEST = "action_request"
    ACTION_RESULT = "action_result"
    EVIDENCE = "evidence"
    CRITIQUE = "critique"
    VERIFICATION = "verification"
    CORRECTION = "correction"
    MEMORY_UPDATE = "memory_update"
    WORLD_UPDATE = "world_update"
    ESCALATION = "escalation"
    CANCEL = "cancel"
    FAILURE = "failure"
    COMPLETION = "completion"


class Classification(str, Enum):
    INTERNAL = "internal"      # agent-to-agent reasoning
    OBSERVED = "observed"      # sensor/tool output
    EXTERNAL = "external"      # untrusted web/file content — sanitize downstream
    PRIVILEGED = "privileged"  # approvals, policy decisions


@dataclass
class AgentMessage:
    type: MessageType
    sender: str
    recipient: str = "broadcast"
    task_id: str = ""
    parent_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    provenance: str = ""
    confidence: float = 0.5
    priority: int = 5
    classification: Classification = Classification.INTERNAL
    message_id: str = field(default_factory=lambda: new_id("msg"))
    timestamp: float = field(default_factory=now)

    def reply(self, sender: str, type: MessageType,
              payload: dict[str, Any] | None = None, **kw: Any) -> "AgentMessage":
        return AgentMessage(type=type, sender=sender, recipient=self.sender,
                            task_id=self.task_id, parent_id=self.message_id,
                            payload=payload or {},
                            provenance=self.provenance, **kw)

    def to_dict(self) -> dict[str, Any]:
        data = dict(self.__dict__)
        data["type"] = self.type.value
        data["classification"] = self.classification.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentMessage":
        data = dict(data)
        data["type"] = MessageType(data["type"])
        data["classification"] = Classification(data.get("classification", "internal"))
        return cls(**data)


class MessageBus:
    """In-memory typed pub/sub with full history. Failure-isolated:
    one bad subscriber never breaks delivery to others."""

    def __init__(self, max_history: int = 1000) -> None:
        self._subs: dict[str, list[Callable[[AgentMessage], None]]] = {}
        self._history: list[AgentMessage] = []
        self._max = max_history
        self.dropped: int = 0

    def subscribe(self, recipient: str,
                  handler: Callable[[AgentMessage], None]) -> None:
        self._subs.setdefault(recipient, []).append(handler)

    def publish(self, message: AgentMessage) -> AgentMessage:
        self._history.append(message)
        if len(self._history) > self._max:
            del self._history[:len(self._history) - self._max]
            self.dropped += 1
        targets = list(self._subs.get(message.recipient, []))
        if message.recipient != "broadcast":
            targets += list(self._subs.get("broadcast", []))
        for handler in targets:
            try:
                handler(message)
            except Exception:
                continue  # isolation: subscriber errors are swallowed
        return message

    def history(self, task_id: str = "", type: MessageType | None = None,
                limit: int = 100) -> list[AgentMessage]:
        out = [m for m in self._history
               if (not task_id or m.task_id == task_id)
               and (type is None or m.type == type)]
        return out[-limit:]

    def thread(self, message_id: str) -> list[AgentMessage]:
        """Follow parent_id chain: full causal thread of one message."""
        by_id = {m.message_id: m for m in self._history}
        chain: list[AgentMessage] = []
        current = by_id.get(message_id)
        while current is not None:
            chain.append(current)
            current = by_id.get(current.parent_id) if current.parent_id else None
        chain.reverse()
        return chain

    def stats(self) -> dict[str, Any]:
        return {"messages": len(self._history), "dropped": self.dropped,
                "subscribers": sum(len(h) for h in self._subs.values())}
