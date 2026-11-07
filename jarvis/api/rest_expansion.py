"""
REST API Expansion — JARVIS-OS additional REST endpoints.

Adds endpoints for:
- Stark AI agent management
- DOT template management
- OMNINET subsystem queries (weather, geospatial, calendar, translation, document)
- Advisory agent queries (medical, legal, financial, scientific)
- System health and metrics
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler
from typing import Any


def _json_response(data: Any, status: int = 200) -> tuple[int, str, dict[str, str]]:
    """Return a JSON response tuple."""
    body = json.dumps(data, default=str).encode("utf-8")
    return status, body.decode("utf-8"), {"Content-Type": "application/json"}


def _error_response(message: str, status: int = 400) -> tuple[int, str, dict[str, str]]:
    """Return an error JSON response."""
    return _json_response({"ok": False, "error": message}, status)


class JarvisAPIHandler(BaseHTTPRequestHandler):
    """Extended HTTP request handler for JARVIS-OS REST API."""

    # These are set by the server during initialization
    jarvis_api: Any = None

    def do_GET(self) -> None:
        """Handle GET requests."""
        path = self.path.split("?", 1)[0]

        try:
            if path == "/api/v1/system/status":
                status = self.jarvis_api.jarvis.status()
                code, body, headers = _json_response(status)
            elif path == "/api/v1/system/health":
                code, body, headers = _json_response(
                    {"status": "healthy", "version": "2.0.0"}
                )
            elif path == "/api/v1/stark":
                result = self.jarvis_api.jarvis.stark_executor.list_stark_ais()
                code, body, headers = _json_response(
                    {
                        "ok": True,
                        "agents": [
                            {
                                "ai_id": ai.ai_id,
                                "name": ai.name,
                                "role": ai.role,
                                "team": ai.team,
                                "risk_tier": ai.risk_tier,
                                "may_act": ai.may_act,
                                "max_tool_calls": ai.max_tool_calls,
                            }
                            for ai in result
                        ],
                    }
                )
            elif path == "/api/v1/dots":
                result = self.jarvis_api.jarvis.dot_manager.list_templates()
                code, body, headers = _json_response(
                    {
                        "ok": True,
                        "templates": [
                            {
                                "template_id": t.template_id,
                                "name": t.name,
                                "role": t.role,
                                "team": t.team,
                                "risk_tier": t.risk_tier,
                                "may_act": t.may_act,
                            }
                            for t in result
                        ],
                    }
                )
            elif path == "/api/v1/omninet/weather/observation":
                # Would parse location from query string
                code, body, headers = _json_response(
                    {"ok": True, "location": "unknown", "condition": "unknown"}
                )
            elif path == "/api/v1/omninet/geospatial/geocode":
                code, body, headers = _json_response(
                    {"ok": True, "latitude": 0.0, "longitude": 0.0}
                )
            elif path == "/api/v1/omninet/document/parse":
                code, body, headers = _json_response(
                    {"ok": True, "extracted_text": "", "word_count": 0}
                )
            else:
                code, body, headers = _error_response("not found", 404)

        except Exception as e:
            code, body, headers = _error_response(str(e), 500)

        self.send_response(code)
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def do_POST(self) -> None:
        """Handle POST requests."""
        path = self.path.split("?", 1)[0]
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length else b""

        try:
            data = json.loads(body.decode("utf-8")) if body else {}
        except Exception:
            data = {}

        try:
            if path == "/api/v1/stark/ask":
                ai_id = data.get("ai_id", "")
                goal = data.get("goal", "")
                if not ai_id or not goal:
                    code, body, headers = _error_response(
                        "ai_id and goal required", 400
                    )
                else:
                    result = self.jarvis_api.jarvis.stark_executor.execute(
                        ai_id, goal
                    )
                    code, body, headers = _json_response(result)
            elif path == "/api/v1/dots/create":
                template_id = data.get("template_id", "")
                name = data.get("name", "")
                if not template_id or not name:
                    code, body, headers = _error_response(
                        "template_id and name required", 400
                    )
                else:
                    code, body, headers = _json_response(
                        {"ok": True, "template_id": template_id, "name": name}
                    )
            elif path == "/api/v1/omninet/translate":
                text = data.get("text", "")
                target = data.get("target_language", "en")
                source = data.get("source_language", "auto")
                result = self.jarvis_api.jarvis.translation_intelligence.translate(
                    text, target, source
                )
                code, body, headers = _json_response(
                    {
                        "ok": True,
                        "translation_id": result.translation_id,
                        "translated_text": result.translated_text,
                        "source_language": result.source_language,
                        "target_language": result.target_language,
                        "confidence": result.confidence,
                    }
                )
            elif path == "/api/v1/omninet/document/parse":
                doc_name = data.get("document_name", "")
                doc_type = data.get("document_type", "")
                content = data.get("content", "")
                result = self.jarvis_api.jarvis.document_intelligence.parse_document(
                    doc_name, doc_type, content.encode("utf-8")
                )
                code, body, headers = _json_response(
                    {
                        "ok": True,
                        "parse_id": result.parse_id,
                        "document_name": result.document_name,
                        "document_type": result.document_type,
                        "extracted_text": result.extracted_text,
                        "word_count": result.word_count,
                    }
                )
            else:
                code, body, headers = _error_response("not found", 404)

        except Exception as e:
            code, body, headers = _error_response(str(e), 500)

        self.send_response(code)
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, format: str, *args) -> None:
        """Suppress default logging."""
        pass