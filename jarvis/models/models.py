"""Model registry, router with fallback chain, lifecycle, self-model, improvement."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core.config import JarvisConfig
from ..core.types import now
from .backends import (BackendSpec, build_client, configured_backends,
                       resolve_selection)


# -- registry / router -----------------------------------------------------
@dataclass
class Model:
    name: str
    kind: str  # fast | reasoning | coding | vision | embedding
    backend: str = "local"  # backend instance name (ollama, nvidia, ...)
    capabilities: list[str] = field(default_factory=list)
    healthy: bool = True
    latency_ms: float = 0.0
    last_check: float = 0.0
    version: str = "1"
    backend_model: str = ""  # concrete model id on the backend (e.g. qwen2.5:3b)
    generative: bool = False  # True when a real model can answer
    local: bool = True  # False for remote providers (privacy boundary)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "kind": self.kind, "backend": self.backend,
                "capabilities": self.capabilities, "healthy": self.healthy,
                "latency_ms": self.latency_ms, "version": self.version,
                "backend_model": self.backend_model,
                "generative": self.generative, "local": self.local}


class ModelRegistry:
    def __init__(self, config: JarvisConfig | None = None) -> None:
        self._models: dict[str, Model] = {}
        self.config = config or JarvisConfig()

    def register(self, model: Model) -> None:
        self._models[model.name] = model

    def get(self, name: str) -> Model | None:
        return self._models.get(name)

    def by_kind(self, kind: str, healthy_only: bool = True) -> list[Model]:
        return [m for m in self._models.values()
                if m.kind == kind and (m.healthy or not healthy_only)]

    def deprecate(self, name: str) -> bool:
        model = self._models.get(name)
        if not model:
            return False
        model.healthy = False
        return True

    def health_check(self, name: str) -> bool:
        """Probe backends that can be probed; local stubs always pass."""
        model = self._models.get(name)
        if model is None:
            return False
        if model.generative:
            model.healthy = self._probe(model)
        model.last_check = now()
        return model.healthy

    def _probe(self, model: Model) -> bool:
        """Ask the backend whether it really serves this model."""
        spec = self._spec(model.backend)
        if spec is None:
            return False
        client = build_client(spec, self.config)
        if client is None:
            return False
        try:
            available = client.models()
        except Exception:
            return False
        if not available:
            return False
        return not model.backend_model or model.backend_model in available

    def _spec(self, backend: str) -> BackendSpec | None:
        for spec in configured_backends(self.config):
            if spec.name == backend:
                return spec
        return None

    def stats(self) -> dict[str, Any]:
        by_kind: dict[str, int] = {}
        for model in self._models.values():
            by_kind[model.kind] = by_kind.get(model.kind, 0) + 1
        return {"total": len(self._models), "by_kind": by_kind,
                "healthy": sum(1 for m in self._models.values() if m.healthy)}


class ModelRouter:
    """Task-based selection, privacy-aware, with fallback chain."""

    KIND_FOR_TASK = {
        "coding": "coding", "code": "coding", "debug": "coding",
        "write": "coding", "function": "coding", "implement": "coding",
        "refactor": "coding", "script": "coding",
        "reason": "reasoning", "plan": "reasoning", "analyze": "reasoning",
        "see": "vision", "image": "vision", "camera": "vision",
        "embed": "embedding", "search": "embedding",
    }

    def __init__(self, registry: ModelRegistry, config: JarvisConfig | None = None) -> None:
        self.registry = registry
        self.config = config or JarvisConfig()
        self.history: list[dict[str, Any]] = []
        self._clients: dict[str, Any] = {}

    # -- backends --------------------------------------------------------
    def _specs(self) -> dict[str, BackendSpec]:
        return {s.name: s for s in configured_backends(self.config)}

    def _client(self, model: Model) -> Any | None:
        """Client for a model's backend (built once, cached)."""
        spec = self._specs().get(model.backend)
        if spec is None:
            return None
        client = self._clients.get(spec.name)
        if client is None:
            client = build_client(spec, self.config)
            if client is None:
                return None
            self._clients[spec.name] = client
        return client

    def _selection(self) -> dict[str, tuple[str, str]]:
        return resolve_selection(self.config)

    # -- selection --------------------------------------------------------
    def kind_for(self, task: str) -> str:
        kind = "fast"
        low = task.lower()
        for marker, mapped in self.KIND_FOR_TASK.items():
            if marker in low:
                kind = mapped
                break
        return kind

    def _candidates(self, kind: str) -> list[Model]:
        """Models that may answer this kind, honouring the local-only wall.

        Unhealthy models stay in the list: a stale probe must not make a
        backend permanently unreachable, so the call itself decides.
        """
        candidates = self.registry.by_kind(kind, healthy_only=False)
        if self.config.policy.local_only:
            candidates = [m for m in candidates if m.local]
        return candidates

    def _rank(self, model: Model) -> tuple[int, float]:
        """Selected first, then healthy generative models, then stubs."""
        selected = self._selection().get(model.kind)
        if selected and model.backend == selected[0] and (
                not selected[1] or model.backend_model == selected[1]):
            return (0, model.latency_ms)
        if model.generative and model.healthy:
            return (1, model.latency_ms)
        if model.generative:
            return (2, model.latency_ms)
        return (3, model.latency_ms)

    def route(self, task: str) -> Model:
        kind = self.kind_for(task)
        candidates = self._candidates(kind)
        if not candidates:
            candidates = self.registry.by_kind("fast")
        if self.config.policy.local_only:
            local = [m for m in candidates if m.local]
            if local:
                candidates = local
        if not candidates:
            raise RuntimeError(f"no model available for kind={kind}")
        chosen = sorted(candidates, key=self._rank)[0]
        self.history.append({"task": task[:80], "model": chosen.name,
                             "kind": kind, "at": now()})
        return chosen

    def fallback_chain(self, kind: str) -> list[str]:
        """Ordered backends to try: kind → fast → local stub. Never empty.

        Order is by rank, so the selected backend is always tried first.
        """
        names = [m.name for m in sorted(self._candidates(kind), key=self._rank)]
        names += [m.name for m in sorted(self._candidates("fast"), key=self._rank)
                  if m.name not in names]
        if not names:
            names = ["local-stub"]
        if self.config.models.fallback_enabled and "local-stub" not in names:
            names.append("local-stub")
        return names

    def complete(self, task: str, prompt: str, system: str = "",
                 images: list[str] | None = None) -> dict[str, Any]:
        """Route then generate. Tries each healthy candidate in rank order."""
        kind = self.kind_for(task)
        tried: list[str] = []
        for name in self.fallback_chain(kind):
            if name == "local-stub":
                tried.append(name)
                continue
            model = self.registry.get(name)
            if model is None or not model.generative:
                continue
            client = self._client(model)
            if client is None:
                tried.append(f"{name}: no client")
                continue
            try:
                result = client.generate(
                    prompt, model=model.backend_model or model.name,
                    system=system,
                    options={"num_predict": self.config.models.llm_max_tokens},
                    images=images if model.kind == "vision" else None)
            except Exception as exc:
                tried.append(f"{name}: {type(exc).__name__}")
                continue
            tried.append(name)
            if result.get("ok"):
                # Keep the provider's own model id before we overwrite
                # "model" with the registry entry name.
                result["provider_model"] = result.get("model", "")
                result["model"] = name
                result["backend"] = model.backend
                result["backend_model"] = model.backend_model
                self.history.append({"task": task[:80], "model": name,
                                     "backend": model.backend,
                                     "kind": kind, "at": now()})
                return result
        return {"ok": False, "error": "no generative backend available",
                "tried": tried, "fallback": "local-stub"}


def default_registry(config: JarvisConfig | None = None) -> ModelRegistry:
    """Register the local stubs plus every configured backend."""
    cfg = config or JarvisConfig()
    reg = ModelRegistry(cfg)
    reg.register(Model("local-fast", "fast", "local", ["chat", "intent"],
                       latency_ms=50.0))
    reg.register(Model("local-reasoning", "reasoning", "local",
                       ["planning", "analysis"], latency_ms=400.0))
    reg.register(Model("local-coding", "coding", "local",
                       ["codegen", "debug"], latency_ms=600.0))
    reg.register(Model("local-vision", "vision", "local",
                       ["ocr", "describe"], latency_ms=800.0))
    reg.register(Model("local-embed", "embedding", "local",
                       ["search"], latency_ms=60.0))
    selection = resolve_selection(cfg)
    for spec in configured_backends(cfg):
        if not spec.enabled:
            continue
        client = build_client(spec, cfg)
        if client is None:
            continue
        try:
            present = set(client.models())
            reachable = bool(present) or client.alive()
        except Exception:
            present, reachable = set(), False
        # The selected model wins over the backend's default for that kind.
        effective: dict[str, str] = dict(spec.models)
        for kind, (backend_name, model_id) in selection.items():
            if backend_name == spec.name and model_id:
                effective[kind] = model_id
        for kind, backend_model in effective.items():
            if reachable and not present:
                healthy = True  # server does not enumerate models; trust it
            else:
                healthy = backend_model in present
            reg.register(Model(
                f"{spec.name}-{kind}", kind, spec.name, ["generate"],
                healthy=healthy,
                latency_ms=spec.latency_ms, backend_model=backend_model,
                generative=True, local=spec.local))
    if cfg.models.cloud_enabled:
        reg.register(Model("cloud-reasoning", "reasoning", "cloud",
                           ["planning", "analysis"], latency_ms=2000.0,
                           local=False))
    return reg


# -- self-model --------------------------------------------------------------
@dataclass
class SelfModel:
    capabilities: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    workload: dict[str, Any] = field(default_factory=dict)
    gaps: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)

    def update_capability(self, name: str, confidence: float) -> None:
        entry = f"{name}@{confidence:.2f}"
        self.capabilities = [c for c in self.capabilities
                             if not c.startswith(name + "@")] + [entry]

    def record_error(self, error: str) -> None:
        self.errors.append(error)
        self.errors = self.errors[-50:]

    def record_gap(self, gap: str) -> None:
        if gap not in self.gaps:
            self.gaps.append(gap)

    def summary(self) -> dict[str, Any]:
        return {"capabilities": self.capabilities, "limitations": self.limitations,
                "recent_errors": self.errors[-5:], "workload": self.workload,
                "gaps": self.gaps, "permissions": self.permissions}


# -- self-improvement ------------------------------------------------------------
class SelfImprovement:
    """Observe → propose → patch → test → evaluate → record. Human-gated."""

    def __init__(self) -> None:
        self.issues: list[dict[str, Any]] = []
        self.patches: list[dict[str, Any]] = []
        self.benchmarks: list[dict[str, Any]] = []

    def observe(self, symptom: str, context: str = "") -> dict[str, Any]:
        issue = {"symptom": symptom, "context": context, "at": now(),
                 "root_cause": self._root_cause(symptom), "status": "open"}
        self.issues.append(issue)
        return issue

    @staticmethod
    def _root_cause(symptom: str) -> str:
        low = symptom.lower()
        if "timeout" in low:
            return "budget too small or scope too large"
        if "permission" in low:
            return "missing grant or over-strict policy"
        if "not found" in low:
            return "stale reference or wrong path"
        if "slow" in low:
            return "unbounded retrieval or missing cache"
        return "unknown — needs reproduction"

    def propose(self, issue_index: int, change: str) -> dict[str, Any]:
        if issue_index >= len(self.issues):
            raise IndexError("no such issue")
        patch = {"issue": self.issues[issue_index]["symptom"], "change": change,
                 "status": "proposed", "at": now()}
        self.patches.append(patch)
        return patch

    def evaluate(self, patch_index: int, tests_pass: bool,
                 approved: bool = False) -> dict[str, Any]:
        if patch_index >= len(self.patches):
            raise IndexError("no such patch")
        patch = self.patches[patch_index]
        if tests_pass and approved:
            patch["status"] = "merged"
        elif tests_pass:
            patch["status"] = "awaiting_approval"
        else:
            patch["status"] = "reverted"
        patch["evaluated_at"] = now()
        return patch

    def benchmark(self, name: str, score: float, baseline: float) -> dict[str, Any]:
        entry = {"name": name, "score": score, "baseline": baseline,
                 "regressed": score < baseline, "at": now()}
        self.benchmarks.append(entry)
        return entry

    def regressions(self) -> list[dict[str, Any]]:
        return [b for b in self.benchmarks if b["regressed"]]
