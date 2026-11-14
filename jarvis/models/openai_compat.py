"""OpenAI-compatible backend: any server that speaks /v1/chat/completions.

One client covers NVIDIA NIM (build.nvidia.com), LM Studio, vLLM,
llama.cpp's server, Ollama's own /v1 surface, Groq, OpenRouter,
Together and OpenAI itself. Stdlib HTTP only.

Every call degrades to a clear error dict -- never an exception -- so
the router can fall through to the next backend. Payloads and reads
are bounded; the API key never leaves the Authorization header and is
never written to a log or snapshot.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

#: Hard cap on a single response body (bytes). A model that streams a
#: runaway body must not be able to exhaust memory.
MAX_RESPONSE_BYTES = 4 * 1024 * 1024

#: Hard cap on error bodies read back from a server.
MAX_ERROR_BYTES = 2048


class OpenAICompatClient:
    """Client for an OpenAI-compatible chat/completions server."""

    def __init__(self, base_url: str, api_key: str = "", timeout: float = 120.0,
                 default_model: str = "",
                 headers: dict[str, str] | None = None,
                 key_provider: Any = None) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self.timeout = timeout
        self.default_model = default_model
        self.headers = dict(headers or {})
        #: Fetched at request time, so no caller ever holds the value.
        self._key_provider = key_provider

    def _current_key(self) -> str:
        """The key for this request, or "" when there is none."""
        if self.api_key:
            return self.api_key
        if self._key_provider is None:
            return ""
        try:
            return str(self._key_provider() or "")
        except Exception:
            return ""

    # -- transport ---------------------------------------------------------
    def _request(self, method: str, path: str,
                 payload: dict[str, Any] | None = None,
                 timeout: float | None = None) -> dict[str, Any]:
        url = self.base_url + path
        data = json.dumps(payload).encode() if payload is not None else None
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        key = self._current_key()
        if key:
            headers["Authorization"] = "Bearer " + key
        headers.update(self.headers)
        req = urllib.request.Request(url, data=data, headers=headers,
                                     method=method)
        try:
            with urllib.request.urlopen(
                    req, timeout=timeout or self.timeout) as resp:
                raw = resp.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    return {"ok": False, "error": "response too large"}
                try:
                    parsed = json.loads(raw.decode())
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    return {"ok": False,
                            "error": f"invalid json: {type(exc).__name__}"}
                return {"ok": True, **parsed}
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read(MAX_ERROR_BYTES).decode(errors="replace")
            except OSError:
                detail = ""
            return {"ok": False, "error": f"http {exc.code}: {detail[:500]}"}
        except Exception as exc:  # connection refused, timeout, DNS, ...
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    # -- discovery / health --------------------------------------------------
    def _model_list(self) -> dict[str, Any]:
        return self._request("GET", "/models", timeout=min(self.timeout, 15.0))

    def alive(self) -> bool:
        result = self._model_list()
        if result.get("ok"):
            return True
        # A server that answers but does not implement /models is still up.
        return str(result.get("error", "")).startswith("http 404")

    def models(self) -> list[str]:
        result = self._model_list()
        if not result.get("ok"):
            return []
        names: list[str] = []
        entries = result.get("data")
        if not isinstance(entries, list):
            return names
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            model_id = str(entry.get("id") or entry.get("model") or "").strip()
            if model_id:
                names.append(model_id)
        return names

    def health(self) -> dict[str, Any]:
        result = self._model_list()
        names: list[str] = []
        if result.get("ok"):
            entries = result.get("data") or []
            for entry in entries if isinstance(entries, list) else []:
                if isinstance(entry, dict):
                    model_id = str(entry.get("id") or "").strip()
                    if model_id:
                        names.append(model_id)
        return {"alive": bool(result.get("ok")), "models": names,
                "expected": {"default": self.default_model}}

    # -- completion ----------------------------------------------------------
    def generate(self, prompt: str, model: str = "", system: str = "",
                 options: dict[str, Any] | None = None,
                 images: list[str] | None = None) -> dict[str, Any]:
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        content: Any = prompt
        if images:
            parts: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
            for path in images:
                try:
                    parts.append({"type": "image_url",
                                  "image_url": {"url": self._data_url(path)}})
                except OSError as exc:
                    return {"ok": False, "error": f"unreadable image: {exc}"}
            content = parts
        messages.append({"role": "user", "content": content})
        return self.chat(messages, model=model, options=options)

    def chat(self, messages: list[dict[str, Any]], model: str = "",
             options: dict[str, Any] | None = None) -> dict[str, Any]:
        target = model or self.default_model
        if not target:
            return {"ok": False, "error": "no model selected"}
        payload: dict[str, Any] = {"model": target, "messages": messages,
                                   "stream": False}
        if options:
            payload.update(self._map_options(options))
        result = self._request("POST", "/chat/completions", payload)
        if not result.get("ok"):
            return result
        choices = result.get("choices")
        if not isinstance(choices, list) or not choices:
            return {"ok": False, "error": "no choices in response"}
        first = choices[0] if isinstance(choices[0], dict) else {}
        message = first.get("message")
        message = message if isinstance(message, dict) else {}
        text = str(message.get("content") or "")
        if not text:
            # Reasoning models may answer in a side channel.
            text = str(message.get("reasoning_content") or "")
        return {"ok": True, "text": text,
                "model": str(result.get("model") or target),
                "finish": str(first.get("finish_reason") or "")}

    def embed(self, text: str, model: str = "") -> dict[str, Any]:
        target = model or self.default_model
        if not target:
            return {"ok": False, "error": "no model selected"}
        result = self._request("POST", "/embeddings",
                                {"model": target, "input": text})
        if not result.get("ok"):
            return result
        data = result.get("data")
        vector: list[float] = []
        if isinstance(data, list) and data and isinstance(data[0], dict):
            raw = data[0].get("embedding") or []
            if isinstance(raw, list):
                vector = [float(v) for v in raw]
        return {"ok": True, "vector": vector, "dim": len(vector)}

    # -- router glue ---------------------------------------------------------
    def model_for(self, kind: str) -> str:
        return self.default_model

    def complete(self, kind: str, prompt: str, system: str = "",
                 images: list[str] | None = None) -> dict[str, Any]:
        """Single entry point used by the model router."""
        if not self.alive():
            return {"ok": False, "error": "backend not reachable",
                    "fallback": "local-stub"}
        return self.generate(prompt, model=self.default_model, system=system,
                             images=images)

    # -- helpers -------------------------------------------------------------
    @staticmethod
    def _map_options(options: dict[str, Any]) -> dict[str, Any]:
        """Translate JARVIS generation options into OpenAI parameters."""
        mapped: dict[str, Any] = {}
        if "num_predict" in options:
            mapped["max_tokens"] = int(options["num_predict"])
        for key in ("temperature", "top_p", "stop", "seed", "presence_penalty",
                    "frequency_penalty"):
            if key in options and options[key] is not None:
                mapped[key] = options[key]
        return mapped

    @staticmethod
    def _data_url(path: str) -> str:
        raw = Path(path).read_bytes()
        mime = mimetypes.guess_type(path)[0] or "image/png"
        return f"data:{mime};base64," + base64.b64encode(raw).decode()
