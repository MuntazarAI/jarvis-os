"""
API — JARVIS-OS REST API and WebSocket event streaming.

Provides REST endpoints plus WebSocket event streaming for real-time
communication with JARVIS-OS subsystems.

The WebSocket lives in `server.py`, next to the server that serves it:
one handshake, one implementation.
"""

from .rest_expansion import JarvisAPIHandler
from .server import JarvisAPI, ws_accept_key

__all__ = [
    "JarvisAPIHandler",
    "JarvisAPI",
    "ws_accept_key",
]
