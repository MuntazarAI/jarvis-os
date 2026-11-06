"""
JARVIS-OS Python SDK — jarvis-sdk package.

Provides a high-level Python client library for external programs to connect
to JARVIS-OS through the API server. Supports agent dispatch, DOT creation,
OMNINET subsystem queries, and real-time event streaming.

Usage:
    from jarvis_sdk import JarvisClient
    
    client = JarvisClient(base_url="http://localhost:8765", token="my-token")
    result = client.stark.dispatch("friday", "check system health")
    print(result)
"""

from __future__ import annotations

import json
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import Any


@dataclass
class JarvisClientConfig:
    """Configuration for the JarvisClient."""
    base_url: str = "http://localhost:8765"
    token: str | None = None
    timeout: float = 30.0
    max_retries: int = 3


class JarvisClientError(Exception):
    """Base exception for JarvisClient errors."""
    pass


class JarvisClient:
    """
    Python client for JARVIS-OS API server.

    Provides typed methods for interacting with JARVIS-OS subsystems:
    Stark AI agents, DOTS, OMNINET, and system status.
    """

    def __init__(self, config: JarvisClientConfig | None = None) -> None:
        self.config = config or JarvisClientConfig()
        self._session_id: str | None = None

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.token:
            headers["Authorization"] = f"Bearer {self.config.token}"
        return headers

    def _request(
        self,
        method: str,
        path: str,
        data: Any = None,
    ) -> dict[str, Any]:
        """Make an HTTP request to the JARVIS-OS API."""
        url = f"{self.config.base_url.rstrip('/')}{path}"
        body = None
        if data is not None:
            body = json.dumps(data).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=body,
            headers=self._headers(),
            method=method,
        )

        last_error: Exception | None = None
        for attempt in range(self.config.max_retries):
            try:
                with urllib.request.urlopen(
                    req, timeout=self.config.timeout
                ) as resp:
                    raw = resp.read()
                    if not raw:
                        return {"ok": True}
                    return json.loads(raw.decode("utf-8"))
            except urllib.error.HTTPError as e:
                body_text = e.read().decode("utf-8", errors="replace")
                raise JarvisClientError(
                    f"HTTP {e.code}: {body_text}"
                ) from e
            except Exception as e:
                last_error = e
                if attempt < self.config.max_retries - 1:
                    time.sleep(0.5 * (attempt + 1))

        raise JarvisClientError(
            f"Request failed after {self.config.max_retries} attempts: {last_error}"
        )

    # -- Stark AI Agents ---------------------------------------------------

    def stark_list(self) -> dict[str, Any]:
        """List all Stark AI agents."""
        return self._request("GET", "/api/v1/stark")

    def stark_ask(self, ai_id: str, goal: str) -> dict[str, Any]:
        """Dispatch a goal to a Stark AI agent."""
        return self._request(
            "POST",
            "/api/v1/stark/ask",
            {"ai_id": ai_id, "goal": goal},
        )

    def stark_status(self) -> dict[str, Any]:
        """Get Stark AI system status."""
        return self._request("GET", "/api/v1/stark/status")

    # -- DOTS --------------------------------------------------------------

    def dots_list(self) -> dict[str, Any]:
        """List all DOT templates."""
        return self._request("GET", "/api/v1/dots")

    def dots_create(self, template_id: str, name: str) -> dict[str, Any]:
        """Create a DOT from a template."""
        return self._request(
            "POST",
            "/api/v1/dots/create",
            {"template_id": template_id, "name": name},
        )

    # -- OMNINET Subsystems ------------------------------------------------

    def weather_observation(self, location: str) -> dict[str, Any]:
        """Get weather observation for a location."""
        return self._request(
            "GET",
            f"/api/v1/omninet/weather/observation?location={location}",
        )

    def geocode(self, address: str) -> dict[str, Any]:
        """Convert address to coordinates."""
        return self._request(
            "GET",
            f"/api/v1/omninet/geospatial/geocode?address={address}",
        )

    def translate(
        self,
        text: str,
        target_language: str,
        source_language: str = "en",
    ) -> dict[str, Any]:
        """Translate text between languages."""
        return self._request(
            "POST",
            "/api/v1/omninet/translate",
            {
                "text": text,
                "target_language": target_language,
                "source_language": source_language,
            },
        )

    def parse_document(
        self,
        document_name: str,
        document_type: str,
        content: str,
    ) -> dict[str, Any]:
        """Parse a document and extract text."""
        return self._request(
            "POST",
            "/api/v1/omninet/document/parse",
            {
                "document_name": document_name,
                "document_type": document_type,
                "content": content,
            },
        )

    # -- System Status -----------------------------------------------------

    def system_status(self) -> dict[str, Any]:
        """Get overall JARVIS-OS system status."""
        return self._request("GET", "/api/v1/system/status")

    def health(self) -> dict[str, Any]:
        """Get system health check."""
        return self._request("GET", "/api/v1/system/health")


# Convenience function for quick client creation
def create_client(
    base_url: str = "http://localhost:8765",
    token: str | None = None,
) -> JarvisClient:
    """Create a JarvisClient with the given configuration."""
    return JarvisClient(
        JarvisClientConfig(base_url=base_url, token=token)
    )


__all__ = [
    "JarvisClient",
    "JarvisClientConfig",
    "JarvisClientError",
    "create_client",
]