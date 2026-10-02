"""Versioned internal protocol model for the device fabric.

Every fabric message is a typed ``FabricMessage`` with protocol version,
sender/recipient, category, correlation ids, capability, auth context and
provenance. Validation is strict on send; parsing is tolerant on receive
(unknown fields are ignored so older cores keep working with newer nodes).

This protocol has NO remote-execution message: COMMAND_REQUEST names a
declared capability and the node side only runs explicitly registered
handler functions. There is deliberately no ``run_shell`` / ``run_python``
/ ``eval`` message type.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from ..core.types import new_id, now
from .model import PROTOCOL_VERSION

MAX_PAYLOAD_BYTES = 64 * 1024


class MessageType(str, Enum):
    HELLO = "hello"
    REGISTER = "register"
    HEARTBEAT = "heartbeat"
    CAPABILITY_ADVERTISEMENT = "capability_advertisement"
    CAPABILITY_QUERY = "capability_query"
    STATE_UPDATE = "state_update"
    COMMAND_REQUEST = "command_request"
    COMMAND_RESULT = "command_result"
    EVENT = "event"
    ERROR = "error"
    GOODBYE = "goodbye"


class ProtocolError(ValueError):
    """Raised when a fabric message fails validation."""


@dataclass
class FabricMessage:
    message_id: str = field(default_factory=lambda: new_id("msg"))
    protocol_version: int = PROTOCOL_VERSION
    sender_node: str = ""
    recipient_node: str = ""
    message_type: str = MessageType.EVENT.value
    timestamp: float = field(default_factory=now)
    request_id: str = ""
    correlation_id: str = ""
    capability: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    auth: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.message_type, MessageType):
            self.message_type = self.message_type.value

    def validate(self) -> "FabricMessage":
        if not self.message_id or not isinstance(self.message_id, str):
            raise ProtocolError("message missing message_id")
        if not isinstance(self.protocol_version, int) or self.protocol_version < 1:
            raise ProtocolError("message has invalid protocol_version")
        if self.protocol_version > PROTOCOL_VERSION:
            raise ProtocolError(
                f"unsupported protocol_version {self.protocol_version} "
                f"(core speaks {PROTOCOL_VERSION})"
            )
        if not self.sender_node or not isinstance(self.sender_node, str):
            raise ProtocolError("message missing sender_node")
        try:
            MessageType(self.message_type)
        except ValueError:
            raise ProtocolError(f"unknown message_type: {self.message_type!r}")
        if not isinstance(self.payload, dict):
            raise ProtocolError("message payload must be an object")
        if len(repr(self.payload)) > MAX_PAYLOAD_BYTES:
            raise ProtocolError("message payload exceeds size bound")
        if self.message_type == MessageType.COMMAND_REQUEST.value and not self.capability:
            raise ProtocolError("command_request requires a capability")
        return self

    @property
    def type(self) -> MessageType:
        return MessageType(self.message_type)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FabricMessage":
        """Tolerant parse: unknown fields are ignored (forward compatibility)."""
        if not isinstance(data, dict):
            raise ProtocolError("message must be an object")
        known = {f for f in cls.__dataclass_fields__}
        clean = {k: v for k, v in data.items() if k in known}
        for required in ("message_id", "sender_node", "message_type"):
            if required not in clean:
                raise ProtocolError(f"message missing {required}")
        if not isinstance(clean.get("payload", {}), dict):
            raise ProtocolError("message payload must be an object")
        return cls(**clean)


def make_error(to: str, frm: str, reason: str, *,
               correlation_id: str = "") -> FabricMessage:
    return FabricMessage(
        sender_node=frm,
        recipient_node=to,
        message_type=MessageType.ERROR.value,
        correlation_id=correlation_id,
        payload={"ok": False, "error": reason[:500]},
    )
