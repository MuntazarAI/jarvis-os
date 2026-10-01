"""Model registry, router with fallback chain, lifecycle, self-model, improvement."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any

from ..core.config import JarvisConfig
from ..core.types import now


# -- registry / router -----------------------------------------------------
@dataclass
class Model:
    name: str
    kind: str  # fast | reasoning | coding | vision | embedding
    backend: str = "local"  # local | ollama | cloud
    capabilities: list[str] = field(default_factory=list)
    healthy: bool = True
    latency_ms: float = 0.0
    last_check: float = 0.0
    version: str = "1"
    backend_model: str = ""  # concrete model id on the backend (e.g. qwen2.5:3b)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "kind": self.kind, "backend": self.backend,
                "capabilities": self.capabilities, "healthy": self.healthy,
                "latency_ms": self.latency_ms, "version": self.version}


class ModelRegistry:
    def __init__(self) -> None:
        self._models: dict[str, Model] = {}

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
        if model.backend == "ollama":
            model.healthy = self._ollama_up()
        model.last_check = now()
        return model.healthy

    @staticmethod
    def _ollama_up() -> bool:
        if shutil.which("ollama") is None:
            return False
        try:
            proc = subprocess.run(["ollama", "list"], capture_output=True,
                                  text=True, timeout=5)
            return proc.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

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

    def route(self, task: str) -> Model:
        kind = "fast"
        low = task.lower()
        for marker, mapped in self.KIND_FOR_TASK.items():
            if marker in low:
                kind = mapped
                break
        candidates = self.registry.by_kind(kind)
        if not candidates:
            candidates = self.registry.by_kind("fast")
        if self.config.policy.local_only:
            local = [m for m in candidates if m.backend != "cloud"]
            if local:
                candidates = local
        if not candidates:
            raise RuntimeError(f"no model available for kind={kind}")
        # Prefer a healthy generative backend (ollama) over local stubs,
        # which cannot generate. Within a backend class, lowest latency wins.
        def rank(model: Model) -> tuple[int, float]:
            if model.backend == "ollama" and model.healthy:
                return (0, model.latency_ms)
            if model.backend == "local":
                return (1, model.latency_ms)
            return (2, model.latency_ms)

        chosen = sorted(candidates, key=rank)[0]
        self.history.append({"task": task[:80], "model": chosen.name,
                             "kind": kind, "at": now()})
        return chosen

    def fallback_chain(self, kind: str) -> list[str]:
        """Ordered backends to try: kind → fast → local stub. Never empty."""
        names = [m.name for m in self.registry.by_kind(kind)]
        names += [m.name for m in self.registry.by_kind("fast") if m.name not in names]
        if not names:
            names = ["local-stub"]
        if self.config.models.fallback_enabled and "local-stub" not in names:
            names.append("local-stub")
        return names

    def complete(self, task: str, prompt: str, system: str = "",
                 images: list[str] | None = None) -> dict[str, Any]:
        """Route then generate. Tries each healthy candidate in rank order."""
        kind = "fast"
        low = task.lower()
        for marker, mapped in self.KIND_FOR_TASK.items():
            if marker in low:
                kind = mapped
                break
        tried: list[str] = []
        for name in self.fallback_chain(kind):
            if name == "local-stub":
                tried.append(name)
                continue
            model = self.registry.get(name)
            if model is None or model.backend != "ollama" or not model.healthy:
                continue
            try:
                from .ollama import OllamaClient, OllamaConfig
                client = OllamaClient(OllamaConfig(host=self.config.models.ollama_host))
                result = client.generate(
                    prompt, model=model.backend_model or model.name,
                    system=system,
                    options={"num_predict": self.config.models.llm_max_tokens},
                    images=images)
            except Exception as exc:
                tried.append(f"{name}: {type(exc).__name__}")
                continue
            tried.append(name)
            if result.get("ok"):
                result["model"] = name
                self.history.append({"task": task[:80], "model": name,
                                     "kind": kind, "at": now()})
                return result
        return {"ok": False, "error": "no generative backend available",
                "tried": tried, "fallback": "local-stub"}


def default_registry(config: JarvisConfig | None = None) -> ModelRegistry:
    reg = ModelRegistry()
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
    if shutil.which("ollama"):
        reg.register(Model("ollama-main", "reasoning", "ollama",
                           ["planning"], latency_ms=1500.0,
                           backend_model="qwen2.5:3b"))
    cfg_for_ollama = config or JarvisConfig()
    if cfg_for_ollama.models.ollama_enabled:
        try:
            from .ollama import OllamaClient, OllamaConfig
            client = OllamaClient(OllamaConfig(host=cfg_for_ollama.models.ollama_host))
            present = set(client.models()) if client.alive() else set()
        except Exception:
            present = set()
        specs = [
            ("ollama-fast", "fast", "qwen2.5:3b", 900.0),
            ("ollama-reasoning", "reasoning", "qwen2.5:3b", 1200.0),
            ("ollama-coding", "coding", "qwen2.5-coder:3b", 1300.0),
            ("ollama-vision", "vision", "minicpm-v:latest", 2500.0),
            ("ollama-embed", "embedding", "nomic-embed-text:latest", 300.0),
        ]
        for entry_name, kind, backend_model, latency in specs:
            reg.register(Model(entry_name, kind, "ollama", ["generate"],
                               healthy=backend_model in present,
                               latency_ms=latency, backend_model=backend_model))
    cfg = config or JarvisConfig()
    if cfg.models.cloud_enabled:
        reg.register(Model("cloud-reasoning", "reasoning", "cloud",
                           ["planning", "analysis"], latency_ms=2000.0))
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
