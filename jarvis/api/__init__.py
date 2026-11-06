"""
API — JARVIS-OS REST API and WebSocket event streaming.

Provides REST endpoints plus WebSocket event streaming for real-time
communication with JARVIS-OS subsystems.
"""

from .rest_expansion import JarvisAPIHandler
from .websocket_events import WebSocketEventHandler, WebSocketHandler

__all__ = [
    "JarvisAPIHandler",
    "WebSocketEventHandler",
    "WebSocketHandler",
]