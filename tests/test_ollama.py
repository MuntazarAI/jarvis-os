"""Tests for the Ollama backend wiring. Live tests skip cleanly offline."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.core.config import JarvisConfig  # noqa: E402
from jarvis.models.models import ModelRouter, default_registry  # noqa: E402
from jarvis.models.ollama import OllamaClient, OllamaConfig  # noqa: E402


def _live_client() -> OllamaClient | None:
    client = OllamaClient()
    return client if client.alive() else None


def test_client_reports_unreachable_host():
    client = OllamaClient(OllamaConfig(host="http://127.0.0.1:1"))
    assert not client.alive()
    assert client.models() == []
    result = client.generate("hi")
    assert not result["ok"] and "error" in result
    assert client.complete("fast", "hi")["fallback"] == "local-stub"


def test_router_complete_falls_back_without_backend():
    cfg = JarvisConfig()
    cfg.models.ollama_enabled = False
    cfg.models.ollama_host = "http://127.0.0.1:1"
    router = ModelRouter(default_registry(cfg), cfg)
    result = router.complete("write a function", "print(1)")
    assert not result["ok"] and result["fallback"] == "local-stub"


def test_registry_prefers_ollama_when_healthy():
    reg = default_registry()
    ollama_kinds = {m.kind for m in reg.by_kind("coding") if m.backend == "ollama"}
    if not ollama_kinds:
        pytest.skip("ollama server not running")
    router = ModelRouter(reg)
    assert router.route("write a function").backend == "ollama"


@pytest.mark.skipif(_live_client() is None, reason="ollama server not running")
def test_live_generate_and_embed():
    client = _live_client()
    assert client is not None
    result = client.generate("Reply with exactly: OK", options={"num_predict": 10})
    assert result["ok"] and "OK" in result["text"]
    embed = client.embed("hello world")
    assert embed["ok"] and embed["dim"] > 100


@pytest.mark.skipif(_live_client() is None, reason="ollama server not running")
def test_live_router_complete():
    router = ModelRouter(default_registry())
    result = router.complete("say hi", "Reply with exactly: HI")
    assert result["ok"] and "HI" in result["text"]
