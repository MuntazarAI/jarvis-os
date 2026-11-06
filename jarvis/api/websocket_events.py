"""
WebSocket Events — JARVIS-OS real-time event streaming.

Provides WebSocket endpoints for real-time event streaming from the
JARVIS-OS event bus. Clients can subscribe to specific event types
and receive live updates as agents, DOTS, and subsystems produce events.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler
from typing import Any, Callable


class WebSocketEventHandler:
    """
    Handles WebSocket connections for real-time event streaming.

    Clients connect via WebSocket and can subscribe to event types.
    Events from the JARVIS-OS event bus are broadcast to connected
    clients whose subscriptions match.
    """

    def __init__(self, jarvis: Any) -> None:
        self.jarvis = jarvis
        self._connections: list[Any] = []
        self._subscriptions: dict[Any, set[str]] = {}
        self._lock = threading.Lock()
        self._subscribed_to_bus = False

    def _subscribe_to_bus(self) -> None:
        """Subscribe to the JARVIS-OS event bus."""
        if self._subscribed_to_bus:
            return
        try:
            self.jarvis.bus.subscribe("*", self._on_bus_event, name="ws-fanout")
        except Exception:
            # Bus may not support subscribe; clients poll instead
            pass
        self._subscribed_to_bus = True

    def _on_bus_event(self, event_type: str, event_data: Any) -> None:
        """Handle an event from the JARVIS-OS event bus."""
        message = json.dumps(
            {
                "type": "event",
                "event_type": event_type,
                "data": event_data,
                "timestamp": __import__("time").time(),
            }
        ).encode("utf-8")

        with self._lock:
            dead: list[Any] = []
            for conn in self._connections:
                subscribed_types = self._subscriptions.get(conn, set())
                if event_type == "*" or event_type in subscribed_types:
                    try:
                        conn.send(message)
                    except Exception:
                        dead.append(conn)
            for conn in dead:
                self._remove_connection(conn)

    def add_connection(self, conn: Any, subscribed_types: set[str] | None = None) -> None:
        """Add a WebSocket connection."""
        with self._lock:
            self._connections.append(conn)
            self._subscriptions[conn] = subscribed_types or set()
            self._subscribe_to_bus()

    def remove_connection(self, conn: Any) -> None:
        """Remove a WebSocket connection."""
        self._remove_connection(conn)

    def _remove_connection(self, conn: Any) -> None:
        """Remove a WebSocket connection (internal)."""
        with self._lock:
            if conn in self._connections:
                self._connections.remove(conn)
            self._subscriptions.pop(conn, None)

    def update_subscriptions(self, conn: Any, subscribed_types: set[str]) -> None:
        """Update the subscription types for a connection."""
        with self._lock:
            self._subscriptions[conn] = subscribed_types

    def broadcast(self, message: dict[str, Any]) -> None:
        """Broadcast a message to all connected clients."""
        data = json.dumps(message).encode("utf-8")
        with self._lock:
            dead: list[Any] = []
            for conn in self._connections:
                try:
                    conn.send(data)
                except Exception:
                    dead.append(conn)
            for conn in dead:
                self._remove_connection(conn)

    def get_connection_count(self) -> int:
        """Get the number of connected clients."""
        with self._lock:
            return len(self._connections)


class WebSocketHandler(BaseHTTPRequestHandler):
    """
    Simple WebSocket upgrade handler.

    Handles the WebSocket handshake and delegates to WebSocketEventHandler
    for message routing.
    """

    ws_handler: WebSocketEventHandler | None = None

    def do_GET(self) -> None:
        """Handle WebSocket upgrade requests."""
        if self.path.split("?", 1)[0] != "/api/v1/ws/events":
            self.send_response(404)
            self.end_headers()
            return

        # WebSocket handshake
        key = self.headers.get("Sec-WebSocket-Key", "")
        import base64
        import hashlib

        accept = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
        ).decode()

        self.send_response(101)
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "upgrade")
        self.send_header("Sec-WebSocket-Accept", accept)
        self.end_headers()

        # Subscribe client based on query params
        import urllib.parse
        params = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        subscribed = set(params.get("subscribe", ["*"])[0].split(","))

        if WebSocketHandler.ws_handler:
            WebSocketHandler.ws_handler.add_connection(self, subscribed)

        # Read frames until disconnect
        try:
            while True:
                header = self.rfile.read(2)
                if not header or len(header) < 2:
                    break
                opcode = header[0] & 0x0F
                if opcode == 0x8:  # Close frame
                    break
                elif opcode == 0x9:  # Ping frame
                    self.wfile.write(b"\x8a\x00")  # Pong
                elif opcode == 0x1:  # Text frame
                    length = header[1] & 0x7F
                    if length == 126:
                        length = int.from_bytes(self.rfile.read(2), "big")
                    elif length == 127:
                        length = int.from_bytes(self.rfile.read(8), "big")
                    payload = self.rfile.read(length) if length else b""
                    try:
                        msg = json.loads(payload.decode("utf-8"))
                        if "subscribe" in msg:
                            if WebSocketHandler.ws_handler:
                                WebSocketHandler.ws_handler.update_subscriptions(
                                    self, set(msg["subscribe"])
                                )
                    except Exception:
                        pass
        except Exception:
            pass
        finally:
            if WebSocketHandler.ws_handler:
                WebSocketHandler.ws_handler.remove_connection(self)