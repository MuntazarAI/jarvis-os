"""Ollama backend: chat, generate, stream, embeddings, vision, health.

Standard-library HTTP only. Every call degrades to a clear error dict —
never an exception — so the router can fall through the fallback chain.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator


@dataclass
class OllamaConfig:
    host: str = "http://localhost:11434"
    timeout: float = 120.0
    default_model: str = "qwen2.5:3b"
    coding_model: str = "qwen2.5-coder:3b"
    vision_model: str = "minicpm-v:latest"
    embedding_model: str = "nomic-embed-text:latest"


class OllamaClient:
    def __init__(self, config: OllamaConfig | None = None) -> None:
        self.config = config or OllamaConfig()

    # -- transport ---------------------------------------------------------
    def _post(self, path: str, payload: dict[str, Any],
              timeout: float | None = None) -> dict[str, Any]:
        url = self.config.host.rstrip("/") + path
        data = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(
                    req, timeout=timeout or self.config.timeout) as resp:
                raw = resp.read().decode()
                # /generate and /chat stream NDJSON when stream=true
                if payload.get("stream"):
                    return {"ok": True, "chunks": raw}
                return {"ok": True, **json.loads(raw)}
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read().decode()[:500]
            except OSError:
                detail = ""
            return {"ok": False, "error": f"http {exc.code}: {detail}"}
        except Exception as exc:  # connection refused, timeout, ...
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    def _get(self, path: str) -> dict[str, Any]:
        try:
            with urllib.request.urlopen(
                    self.config.host.rstrip("/") + path, timeout=10) as resp:
                return {"ok": True, **json.loads(resp.read().decode())}
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    # -- discovery / health --------------------------------------------------
    def alive(self) -> bool:
        result = self._get("/api/tags")
        return bool(result.get("ok"))

    def models(self) -> list[str]:
        result = self._get("/api/tags")
        if not result.get("ok"):
            return []
        return [m.get("name", "") for m in result.get("models", [])]

    def has(self, name: str) -> bool:
        return name in self.models()

    def health(self) -> dict[str, Any]:
        names = self.models()
        return {"alive": bool(names or self.alive()), "models": names,
                "expected": {"default": self.config.default_model,
                             "coding": self.config.coding_model,
                             "vision": self.config.vision_model,
                             "embedding": self.config.embedding_model}}

    # -- completion ------------------------------------------------------------
    def generate(self, prompt: str, model: str = "",
                 system: str = "", options: dict[str, Any] | None = None,
                 images: list[str] | None = None,
                 timeout: float | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model or self.config.default_model,
            "prompt": prompt, "stream": False,
        }
        if system:
            payload["system"] = system
        if options:
            payload["options"] = options
        if images:
            try:
                payload["images"] = [self._image_b64(p) for p in images]
            except OSError as exc:
                return {"ok": False, "error": f"unreadable image: {exc}"}
            # First multimodal inference loads the vision tower; allow longer.
            timeout = max(timeout or 0.0, 300.0)
        result = self._post("/api/generate", payload, timeout=timeout)
        if not result.get("ok"):
            return result
        return {"ok": True, "text": result.get("response", ""),
                "model": result.get("model", ""),
                "prompt_eval": result.get("prompt_eval_count", 0),
                "eval": result.get("eval_count", 0)}

    def chat(self, messages: list[dict[str, str]], model: str = "",
             options: dict[str, Any] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"model": model or self.config.default_model,
                                   "messages": messages, "stream": False}
        if options:
            payload["options"] = options
        result = self._post("/api/chat", payload)
        if not result.get("ok"):
            return result
        message = result.get("message", {})
        return {"ok": True, "text": message.get("content", ""),
                "model": result.get("model", "")}

    def stream(self, prompt: str, model: str = "",
               on_token: Callable[[str], None] | None = None) -> dict[str, Any]:
        payload = {"model": model or self.config.default_model,
                   "prompt": prompt, "stream": True}
        result = self._post("/api/generate", payload)
        if not result.get("ok"):
            return result
        full: list[str] = []
        for line in result.get("chunks", "").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError:
                continue
            token = chunk.get("response", "")
            full.append(token)
            if on_token:
                on_token(token)
            if chunk.get("done"):
                break
        return {"ok": True, "text": "".join(full)}

    def describe_image(self, image_path: str, question: str = "Describe this image.") -> dict[str, Any]:
        if not Path(image_path).exists():
            return {"ok": False, "error": f"no such image: {image_path}"}
        return self.generate(question, model=self.config.vision_model,
                             images=[image_path])

    def embed(self, text: str, model: str = "") -> dict[str, Any]:
        result = self._post("/api/embeddings",
                            {"model": model or self.config.embedding_model,
                             "prompt": text})
        if not result.get("ok"):
            return result
        vec = result.get("embedding", [])
        return {"ok": True, "vector": vec, "dim": len(vec)}

    @staticmethod
    def _image_b64(path: str) -> str:
        return base64.b64encode(Path(path).read_bytes()).decode()

    # -- router glue -------------------------------------------------------------
    def model_for(self, kind: str) -> str:
        return {"coding": self.config.coding_model,
                "vision": self.config.vision_model,
                "reasoning": self.config.default_model,
                "fast": self.config.default_model,
                "embedding": self.config.embedding_model}.get(kind, self.config.default_model)

    def complete(self, kind: str, prompt: str, system: str = "",
                 images: list[str] | None = None) -> dict[str, Any]:
        """Single entry point used by the model router."""
        if not self.alive():
            return {"ok": False, "error": "ollama server not reachable",
                    "fallback": "local-stub"}
        return self.generate(prompt, model=self.model_for(kind),
                             system=system, images=images)
