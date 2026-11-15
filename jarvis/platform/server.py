"""The public platform server.

`jarvis platform serve` runs the site people use: sign up, sign in,
chat, and hear the answer in the British voice.

It is a separate process from the operator API on purpose. The
operator API is private (localhost, one token, everything visible);
the platform is public (accounts, sessions, one JARVIS per person).
Keeping them apart means a bug in one cannot expose the other.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .routes import Platform

#: The port the public site listens on.
DEFAULT_PORT = 8766

#: The biggest request body the platform accepts.
MAX_BODY_BYTES = 64 * 1024


class PlatformServer:
    """Serves the public site."""

    def __init__(self, root: str | Path | None = None,
                 host: str = "127.0.0.1", port: int = DEFAULT_PORT,
                 template_config: Path | None = None,
                 speak: bool = True) -> None:
        from ..core.config import DEFAULT_HOME
        base = Path(root) if root else Path(DEFAULT_HOME) / "platform"
        self.platform = Platform(base, template_config, speak=speak)
        self.host = host
        self.port = port
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def handle(self, method: str, path: str, body: bytes,
               headers: dict[str, str]) -> tuple[int, dict[str, Any]]:
        """One request. The platform answers; the rest is a 404."""
        return self.platform.handle(method, path, body, headers)

    def serve_forever(self) -> None:
        platform = self.platform

        class Handler(BaseHTTPRequestHandler):
            server_version = "jarvis-platform/1.0"
            protocol_version = "HTTP/1.1"

            def _send(self, code: int, body: bytes, ctype: str,
                      extra: dict[str, str] | None = None) -> None:
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                for key, value in (extra or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                if body:
                    self.wfile.write(body)

            def _read_body(self) -> bytes:
                try:
                    length = int(self.headers.get("Content-Length", "0") or 0)
                except (TypeError, ValueError):
                    return b""
                if length <= 0:
                    return b""
                if length > MAX_BODY_BYTES:
                    return b""
                return self.rfile.read(length)

            def do_GET(self) -> None:  # noqa: N802
                headers = {k.lower(): v for k, v in self.headers.items()}
                code, payload = platform.handle("GET", self.path, b"", headers)
                if isinstance(payload, dict) and "__html__" in payload:
                    self._send(code, payload["__html__"].encode(),
                               "text/html; charset=utf-8")
                    return
                body = json.dumps(payload, default=str).encode()
                self._send(code, body, "application/json")

            def do_POST(self) -> None:  # noqa: N802
                headers = {k.lower(): v for k, v in self.headers.items()}
                body = self._read_body()
                code, payload = platform.handle("POST", self.path, body,
                                                headers)
                extra: dict[str, str] = {}
                if isinstance(payload, dict) and payload.get("set_cookie"):
                    extra["Set-Cookie"] = str(payload.pop("set_cookie"))
                if isinstance(payload, dict) and "__audio__" in payload:
                    self._send(code, payload["__audio__"],
                               str(payload.get("ctype", "audio/wav")), extra)
                    return
                body = json.dumps(payload, default=str).encode()
                self._send(code, body, "application/json", extra)

            def do_DELETE(self) -> None:  # noqa: N802
                headers = {k.lower(): v for k, v in self.headers.items()}
                code, payload = platform.handle("DELETE", self.path, b"",
                                                headers)
                body = json.dumps(payload, default=str).encode()
                self._send(code, body, "application/json")

            def log_message(self, *args: Any) -> None:  # keep quiet
                pass

        self._server = ThreadingHTTPServer((self.host, self.port), Handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
        if self._thread:
            self._thread.join(timeout=5)
        self.platform.close()


__all__ = ["PlatformServer", "DEFAULT_PORT", "MAX_BODY_BYTES"]
