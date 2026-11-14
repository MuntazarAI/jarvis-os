"""Backend specs: how JARVIS reaches any model, anywhere.

A *backend* is a named provider JARVIS can ask for text: the local
Ollama daemon, NVIDIA NIM, an OpenAI-compatible server (LM Studio,
vLLM, llama.cpp, Groq, OpenRouter, Together, OpenAI), or anything else
that speaks one of the supported protocols.

Backends live in config. Each one declares the model ids it serves per
kind (fast / reasoning / coding / vision / embedding). *Selection* says
which backend answers which kind, so switching models is a config or
CLI change -- never a code change.

Keys never live in config. A backend names a vault secret and/or an
environment variable; the value is fetched at call time and never
reaches config, logs or snapshots.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from .openai_compat import OpenAICompatClient
from ..core.config import MODEL_BACKEND_TYPES as BACKEND_TYPES
from ..core.config import MODEL_KINDS as KINDS

#: Default local Ollama models (unchanged behaviour when nothing is set).
DEFAULT_OLLAMA_MODELS = {
    "fast": "qwen2.5:3b",
    "reasoning": "qwen2.5:3b",
    "coding": "qwen2.5-coder:3b",
    "vision": "qwen3-vl:2b",
    "embedding": "nomic-embed-text:latest",
}


@dataclass
class BackendSpec:
    """One model provider JARVIS can talk to."""

    name: str
    type: str = "ollama"
    base_url: str = ""
    models: dict[str, str] = field(default_factory=dict)
    #: The NAME of the environment variable holding the key.
    api_key_env_ref: str = ""
    #: The NAME of the vault secret / env var holding the key.
    #: It is a reference, never the key itself.
    api_key_ref: str = ""
    local: bool = True
    enabled: bool = True
    timeout: float = 120.0
    latency_ms: float = 1500.0
    headers: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Any, name_hint: str = "") -> "BackendSpec":
        """Build a spec from a config mapping. Raises ValueError on junk."""
        if not isinstance(data, dict):
            raise ValueError("backend entry must be a mapping")
        name = str(data.get("name") or name_hint or "").strip()
        if not name:
            raise ValueError("backend needs a name")
        backend_type = str(data.get("type") or "ollama").strip().lower()
        if backend_type not in BACKEND_TYPES:
            raise ValueError(
                f"unknown backend type '{backend_type}' "
                f"(use {', '.join(BACKEND_TYPES)})")
        models: dict[str, str] = {}
        raw_models = data.get("models")
        if isinstance(raw_models, dict):
            for kind, model_id in raw_models.items():
                key = str(kind).strip().lower()
                if key not in KINDS:
                    continue
                value = str(model_id).strip()
                if value:
                    models[key] = value
        local = data.get("local")
        if local is None:
            local = backend_type == "ollama"
        raw_headers = data.get("headers")
        headers: dict[str, str] = {}
        if isinstance(raw_headers, dict):
            headers = {str(k): str(v) for k, v in raw_headers.items()}
        return cls(
            name=name,
            type=backend_type,
            base_url=str(data.get("base_url") or "").strip(),
            models=models,
            api_key_env_ref=str(data.get("api_key_env") or "").strip(),
            api_key_ref=str(data.get("api_key_secret")
                             or data.get("api_key_ref") or "").strip(),
            local=bool(local),
            enabled=bool(data.get("enabled", True)),
            timeout=float(data.get("timeout") or 120.0),
            latency_ms=float(data.get("latency_ms") or 1500.0),
            headers=headers,
        )

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "type": self.type,
                "base_url": self.base_url, "models": dict(self.models),
                "api_key_env": self.api_key_env_ref,
                "api_key_secret": self.api_key_ref, "local": self.local,
                "enabled": self.enabled, "timeout": self.timeout,
                "latency_ms": self.latency_ms, "headers": dict(self.headers)}

    @property
    def has_key(self) -> bool:
        """True when a key source is configured (never the key itself)."""
        return bool(self.api_key_env_ref or self.api_key_ref)


def default_ollama_spec(host: str = "http://localhost:11434") -> BackendSpec:
    """The always-available local backend."""
    return BackendSpec(name="ollama", type="ollama", base_url=host,
                       models=dict(DEFAULT_OLLAMA_MODELS), local=True)


def configured_backends(config: Any) -> list[BackendSpec]:
    """Backends from config, or the default local Ollama one.

    A malformed entry is skipped rather than allowed to break startup;
    `jarvis models list` shows what was actually loaded.
    """
    model_config = getattr(config, "models", None)
    raw = getattr(model_config, "backends", None) or []
    specs: list[BackendSpec] = []
    for entry in raw:
        try:
            specs.append(BackendSpec.from_dict(entry))
        except ValueError:
            continue
    if not specs:
        host = getattr(model_config, "ollama_host", "http://localhost:11434")
        specs.append(default_ollama_spec(host))
    if not getattr(model_config, "ollama_enabled", True):
        specs = [s for s in specs if s.type != "ollama"]
    return specs


def resolve_key(spec: BackendSpec, config: Any = None) -> str:
    """Fetch a backend's API key from the vault, then the environment.

    The value is returned to the caller and nowhere else: it is not
    written to config, logs, health output or snapshots.
    """
    if spec.api_key_ref and config is not None:
        try:
            from ..security.security import SecretVault
            value = SecretVault(config.paths.home).get(spec.api_key_ref)
            if value:
                return value
        except Exception:
            pass
    if spec.api_key_env_ref:
        return os.environ.get(spec.api_key_env_ref, "")
    return ""


def key_provider(spec: BackendSpec, config: Any = None) -> Any:
    """A callable that fetches the key when it is needed.

    The value is read at request time, so the caller that wires the
    backend never holds it.
    """
    def _fetch() -> str:
        return resolve_key(spec, config)
    return _fetch


def key_present(spec: BackendSpec, config: Any = None) -> bool:
    """Is a key available for this backend?

    The value is never read: for the vault this asks whether the slot
    exists, for the environment whether the variable is set. A caller
    that only needs "is there a key" never handles the secret itself.
    """
    if spec.api_key_ref:
        if config is None:
            return False
        try:
            from ..security.security import SecretVault
            return spec.api_key_ref in SecretVault(config.paths.home).names()
        except Exception:
            return False
    if spec.api_key_env_ref:
        return bool(os.environ.get(spec.api_key_env_ref, ""))
    return False


def build_client(spec: BackendSpec, config: Any = None) -> Any | None:
    """Create a client for a backend spec, or None when it cannot serve."""
    if not spec.enabled:
        return None
    if spec.type == "ollama":
        from .ollama import OllamaClient
        return OllamaClient.from_spec(spec)
    if spec.type == "openai":
        if not spec.base_url:
            return None
        return OpenAICompatClient(
            base_url=spec.base_url,
            timeout=spec.timeout,
            default_model=spec.models.get("fast", ""),
            headers=spec.headers,
            key_provider=key_provider(spec, config))
    return None


def selection_targets(config: Any) -> dict[str, str]:
    """Raw selection map: kind -> "backend" or "backend:model"."""
    model_config = getattr(config, "models", None)
    raw = getattr(model_config, "selection", None) or {}
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items()}


def resolve_selection(config: Any) -> dict[str, tuple[str, str]]:
    """Resolve selection into kind -> (backend name, model id)."""
    specs = {s.name: s for s in configured_backends(config)}
    out: dict[str, tuple[str, str]] = {}
    for kind, target in selection_targets(config).items():
        if kind not in KINDS:
            continue
        backend_name, _, model_id = str(target).partition(":")
        backend_name = backend_name.strip()
        model_id = model_id.strip()
        spec = specs.get(backend_name)
        if spec is None:
            continue
        if not model_id:
            model_id = spec.models.get(kind, "")
        if model_id:
            out[kind] = (backend_name, model_id)
    return out


def client_for_kind(config: Any, kind: str) -> tuple[Any, str] | None:
    """The (client, model id) that should answer work of `kind`.

    The selected backend wins; otherwise any enabled backend that
    serves that kind is used.
    """
    specs = {s.name: s for s in configured_backends(config)}
    selection = resolve_selection(config)
    order: list[tuple[str, str]] = []
    chosen = selection.get(kind)
    if chosen:
        order.append(chosen)
    for spec in specs.values():
        if not spec.enabled:
            continue
        model_id = spec.models.get(kind, "")
        if model_id and spec.name not in [name for name, _ in order]:
            order.append((spec.name, model_id))
    for name, model_id in order:
        spec = specs.get(name)
        if spec is None:
            continue
        client = build_client(spec, config)
        if client is None:
            continue
        return client, model_id
    return None
