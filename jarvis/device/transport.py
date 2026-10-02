"""Transport abstraction for the device fabric.

3.8 ships exactly one transport: ``in-process`` — synchronous, in-memory
delivery for the local node and deterministic tests. No sockets, no
listeners, no background threads.

Future transports (LAN, WebSocket, HTTPS, mTLS, QUIC, Tailscale) implement
the ``Transport`` interface and register via ``register_transport``; the
registry, router and protocol never change.
"""

from __future__ import annotations

from typing import Any, Callable

from ..core.types import now
from .protocol import FabricMessage, MessageType, make_error
from .security import scrub


class TransportError(RuntimeError):
    """Raised when delivery fails."""


class Transport:
    """Interface every fabric transport implements."""

    name: str = "abstract"
    network_name: str | None = None

    def send(self, message: FabricMessage) -> FabricMessage | None:
        """Deliver one message. Returns the reply, if any."""
        raise NotImplementedError

    def close(self) -> None:
        """Release transport resources (no-op for in-process)."""

    def status(self) -> dict[str, Any]:
        return {"transport": self.name, "network": self.network_name}


Handler = Callable[[FabricMessage], FabricMessage]


class LocalNode:
    """The node side of a transport: runs explicitly registered handlers.

    A LocalNode executes NOTHING except functions placed in ``handlers``
    under a declared capability name. There is no shell, no eval, no
    fallback execution path.
    """

    def __init__(self, node_id: str) -> None:
        self.node_id = node_id
        self.handlers: dict[str, Handler] = {}
        self.received: list[dict[str, Any]] = []

    def on(self, capability: str, handler: Handler) -> None:
        self.handlers[capability] = handler

    def handle(self, message: FabricMessage) -> FabricMessage:
        message.validate()
        self.received.append({"type": message.message_type, "at": now()})
        if len(self.received) > 200:
            self.received = self.received[-200:]
        if message.message_type == MessageType.COMMAND_REQUEST.value:
            handler = self.handlers.get(message.capability)
            if handler is None:
                return make_error(
                    message.sender_node, self.node_id,
                    f"capability not served by node: {message.capability}",
                    correlation_id=message.message_id,
                )
            try:
                reply = handler(message)
            except Exception as exc:  # handler failure is a result, not a crash
                return make_error(
                    message.sender_node, self.node_id,
                    f"capability handler failed: {exc}",
                    correlation_id=message.message_id,
                )
            reply.correlation_id = reply.correlation_id or message.message_id
            return reply
        # Non-command messages are acknowledged without action.
        ack = FabricMessage(
            sender_node=self.node_id,
            recipient_node=message.sender_node,
            message_type=MessageType.EVENT.value,
            correlation_id=message.message_id,
            payload={"ok": True, "ack": message.message_type},
        )
        return ack


class InProcessTransport(Transport):
    """Synchronous in-memory delivery. Deterministic; no network."""

    name = "in-process"
    network_name = "in-process-loopback"

    def __init__(self) -> None:
        self.nodes: dict[str, LocalNode] = {}
        self.sent: list[dict[str, Any]] = []

    def register_node(self, node: LocalNode) -> None:
        self.nodes[node.node_id] = node

    def unregister_node(self, node_id: str) -> bool:
        return self.nodes.pop(node_id, None) is not None

    def send(self, message: FabricMessage) -> FabricMessage | None:
        message.validate()
        self.sent.append({
            "type": message.message_type,
            "from": message.sender_node,
            "to": message.recipient_node,
            "at": now(),
        })
        if len(self.sent) > 200:
            self.sent = self.sent[-200:]
        node = self.nodes.get(message.recipient_node)
        if node is None:
            raise TransportError(f"unknown recipient node: {message.recipient_node}")
        return node.handle(message)

    def status(self) -> dict[str, Any]:
        info = super().status()
        info["nodes"] = sorted(self.nodes)
        info["sent"] = len(self.sent)
        return info


_TRANSPORTS: dict[str, Callable[[], Transport]] = {
    "in-process": InProcessTransport,
}


def register_transport(name: str, factory: Callable[[], Transport]) -> None:
    _TRANSPORTS[name] = factory


def get_transport(name: str) -> Transport:
    try:
        return _TRANSPORTS[name]()
    except KeyError:
        raise TransportError(
            f"unknown transport: {name} (available: {sorted(_TRANSPORTS)})"
        )


def available_transports() -> list[str]:
    return sorted(_TRANSPORTS)
