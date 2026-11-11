"""Tests for pluggable model backends: JARVIS can use any model.

Offline and deterministic: the "remote" backend is a local HTTP server
that speaks the OpenAI protocol. No network, no real API key.
"""

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.core.config import JarvisConfig  # noqa: E402
from jarvis.core.service import check_dependencies  # noqa: E402
from jarvis.models.backends import (BackendSpec, build_client,  # noqa: E402
                                    configured_backends, resolve_selection)
from jarvis.models.models import ModelRouter, default_registry  # noqa: E402
from jarvis.models.openai_compat import OpenAICompatClient  # noqa: E402
from jarvis.security.security import SecretVault  # noqa: E402


# -- fake OpenAI-compatible server ------------------------------------------
class _Handler(BaseHTTPRequestHandler):
    seen: list[dict] = []

    def log_message(self, *args):  # silence the server
        return

    def _send(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        type(self).seen.append({"path": self.path,
                                "auth": self.headers.get("Authorization", "")})
        if self.path == "/v1/models":
            self._send({"object": "list",
                        "data": [{"id": "test/model-a"}, {"id": "test/model-b"}]})
        else:
            self._send({"error": "not found"}, status=404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode()
        payload = json.loads(raw) if raw else {}
        type(self).seen.append({"path": self.path,
                                "auth": self.headers.get("Authorization", ""),
                                "payload": payload})
        if self.path == "/v1/chat/completions":
            self._send({"model": payload.get("model", ""),
                        "choices": [{"message": {"content": "OK"},
                                     "finish_reason": "stop"}]})
        elif self.path == "/v1/embeddings":
            self._send({"data": [{"embedding": [0.1, 0.2, 0.3]}]})
        else:
            self._send({"error": "not found"}, status=404)


@pytest.fixture
def server():
    _Handler.seen = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address[0], httpd.server_address[1]
    yield f"http://{host}:{port}/v1"
    httpd.shutdown()
    httpd.server_close()


def _config(tmp_path, base_url, **kwargs):
    cfg = JarvisConfig()
    cfg.paths.home = tmp_path
    cfg.policy.local_only = False
    cfg.models.backends = [{
        "name": "remote",
        "type": "openai",
        "base_url": base_url,
        "models": {"fast": "test/model-a", "reasoning": "test/model-b"},
        "api_key_secret": "remote_api_key",
        "local": False,
    }]
    for key, value in kwargs.items():
        setattr(cfg.policy, key, value)
    return cfg


# -- spec parsing -----------------------------------------------------------
def test_spec_parses_models_and_ignores_unknown_kinds():
    spec = BackendSpec.from_dict({
        "name": "nvidia", "type": "openai",
        "base_url": "https://example.invalid/v1",
        "models": {"fast": "m1", "reasoning": "m2", "bogus": "m3"},
        "api_key_secret": "k", "local": False,
    })
    assert spec.models == {"fast": "m1", "reasoning": "m2"}
    assert spec.local is False
    assert spec.has_key is True


def test_spec_rejects_unknown_type_and_empty_name():
    with pytest.raises(ValueError):
        BackendSpec.from_dict({"name": "x", "type": "telepathy"})
    with pytest.raises(ValueError):
        BackendSpec.from_dict({"type": "ollama"})


def test_broken_backend_entry_does_not_break_startup(tmp_path):
    cfg = JarvisConfig()
    cfg.paths.home = tmp_path
    cfg.models.backends = [{"name": "bad", "type": "nope"}, "junk"]
    specs = configured_backends(cfg)
    assert all(s.type in ("ollama", "openai") for s in specs)


def test_default_backend_is_local_ollama(tmp_path):
    cfg = JarvisConfig()
    cfg.paths.home = tmp_path
    specs = configured_backends(cfg)
    assert [s.name for s in specs] == ["ollama"]
    assert specs[0].local is True


# -- the OpenAI-compatible client --------------------------------------------
def test_client_reads_models_and_sends_bearer_key(server, tmp_path):
    client = OpenAICompatClient(base_url=server, api_key="secret-key")
    assert client.alive() is True
    assert client.models() == ["test/model-a", "test/model-b"]
    result = client.generate("hi", model="test/model-a")
    assert result["ok"] and result["text"] == "OK"
    assert _Handler.seen[-1]["auth"] == "Bearer secret-key"


def test_client_never_leaks_the_key_on_error(server):
    client = OpenAICompatClient(base_url=server, api_key="secret-key")
    broken = OpenAICompatClient(base_url=server + "/missing",
                                api_key="secret-key")
    result = broken.generate("hi", model="test/model-a")
    assert result["ok"] is False
    assert "secret-key" not in json.dumps(result)


def test_client_sends_images_as_data_urls(server, tmp_path):
    image = tmp_path / "shot.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    client = OpenAICompatClient(base_url=server, api_key="k")
    result = client.generate("what is this?", model="test/model-a",
                             images=[str(image)])
    assert result["ok"]
    payload = _Handler.seen[-1]["payload"]
    content = payload["messages"][-1]["content"]
    assert isinstance(content, list)
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_client_reports_unreachable_backend():
    client = OpenAICompatClient(base_url="http://127.0.0.1:1/v1")
    assert client.alive() is False
    assert client.models() == []
    result = client.generate("hi", model="m")
    assert result["ok"] is False and "error" in result


# -- the router uses whichever backend is selected ----------------------------
def test_router_calls_the_configured_backend(server, tmp_path):
    cfg = _config(tmp_path, server)
    router = ModelRouter(default_registry(cfg), cfg)
    result = router.complete("say hi", "Reply with exactly: OK")
    assert result["ok"] and result["text"] == "OK"
    assert result["backend"] == "remote"
    assert _Handler.seen[-1]["payload"]["model"] == "test/model-a"


def test_selection_picks_the_chosen_model(server, tmp_path):
    cfg = _config(tmp_path, server)
    cfg.models.selection = {"fast": "remote:test/model-b"}
    router = ModelRouter(default_registry(cfg), cfg)
    router.complete("say hi", "hello")
    assert _Handler.seen[-1]["payload"]["model"] == "test/model-b"


def test_fallback_chain_starts_with_the_selected_backend(server, tmp_path):
    """A local backend registered first must not shadow the selection."""
    cfg = _config(tmp_path, server)
    cfg.models.backends.insert(0, {
        "name": "ollama", "type": "ollama",
        "base_url": "http://127.0.0.1:11434",
        "models": {"fast": "qwen2.5:3b"},
    })
    cfg.models.selection = {"fast": "remote:test/model-b"}
    router = ModelRouter(default_registry(cfg), cfg)
    chain = router.fallback_chain("fast")
    assert chain[0] == "remote-fast"
    assert chain.index("remote-fast") < chain.index("ollama-fast")
    result = router.complete("say hi", "hello")
    assert result["ok"] and result["backend"] == "remote"
    assert _Handler.seen[-1]["payload"]["model"] == "test/model-b"


def test_an_unhealthy_backend_is_still_tried(server, tmp_path):
    """A stale boot probe must not make a backend permanently unusable."""
    cfg = _config(tmp_path, server)
    registry = default_registry(cfg)
    registry.get("remote-fast").healthy = False  # as if the probe failed
    router = ModelRouter(registry, cfg)
    result = router.complete("say hi", "hello")
    assert result["ok"] and result["backend"] == "remote"


def test_local_only_blocks_a_remote_backend(server, tmp_path):
    cfg = _config(tmp_path, server)
    cfg.policy.local_only = True
    router = ModelRouter(default_registry(cfg), cfg)
    assert all(m.local for m in router.registry.by_kind("fast", healthy_only=False)
               if m.backend == "remote" and m.generative) is False
    result = router.complete("say hi", "hello")
    # The remote backend must not be called while local_only is on.
    assert not any(s.get("path", "").endswith("/chat/completions")
                   for s in _Handler.seen)
    assert result["ok"] is False


def test_remote_backend_is_used_when_local_only_is_off(server, tmp_path):
    cfg = _config(tmp_path, server)
    router = ModelRouter(default_registry(cfg), cfg)
    result = router.complete("say hi", "hello")
    assert result["ok"] is True
    assert any(s.get("path", "").endswith("/chat/completions")
               for s in _Handler.seen)


def test_fallback_chain_never_reaches_a_remote_backend_when_blocked(tmp_path):
    cfg = _config(tmp_path, "http://127.0.0.1:1/v1")
    cfg.policy.local_only = True
    router = ModelRouter(default_registry(cfg), cfg)
    assert "remote-fast" not in router.fallback_chain("fast")


# -- keys --------------------------------------------------------------------
def test_api_key_comes_from_the_vault_and_never_from_config(server, tmp_path):
    vault = SecretVault(tmp_path)
    vault.put("remote_api_key", "vault-secret")
    cfg = _config(tmp_path, server)
    registry = default_registry(cfg)
    router = ModelRouter(registry, cfg)
    router.complete("say hi", "hello")
    assert any(s.get("auth") == "Bearer vault-secret" for s in _Handler.seen)
    assert "vault-secret" not in json.dumps(cfg.to_dict())


def test_key_is_not_in_health_output(server, tmp_path):
    vault = SecretVault(tmp_path)
    vault.put("remote_api_key", "vault-secret")
    cfg = _config(tmp_path, server)
    spec = configured_backends(cfg)[0]
    client = build_client(spec, cfg)
    assert client is not None
    assert "vault-secret" not in json.dumps(client.health())


# -- doctor ------------------------------------------------------------------
def test_doctor_reports_every_backend(server, tmp_path):
    cfg = _config(tmp_path, server)
    checks = check_dependencies(cfg)
    names = [c.name for c in checks]
    assert "backend:remote" in names
    assert "model:remote/fast" in names
    assert "models:local-only" in names


# -- selection resolution ----------------------------------------------------
def test_resolve_selection_understands_model_ids_with_colons(tmp_path):
    cfg = JarvisConfig()
    cfg.paths.home = tmp_path
    cfg.models.backends = [{
        "name": "ollama2", "type": "ollama",
        "base_url": "http://127.0.0.1:11434",
        "models": {"fast": "qwen2.5:3b"},
    }]
    cfg.models.selection = {"fast": "ollama2:qwen2.5:3b"}
    resolved = resolve_selection(cfg)
    assert resolved["fast"] == ("ollama2", "qwen2.5:3b")


# -- CLI ---------------------------------------------------------------------
def _run_cli(argv, home):
    from jarvis.cli import main
    return main(["--home", str(home)] + argv)


def test_cli_adds_and_selects_a_backend(tmp_path, capsys):
    home = tmp_path / "home"
    home.mkdir()
    code = _run_cli(["models", "add", "remote", "--type", "openai",
                     "--base-url", "http://127.0.0.1:9/v1",
                     "--model", "fast=model-a", "--remote", "--json"], home)
    assert code == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["added"]["name"] == "remote"

    code = _run_cli(["models", "use", "fast", "remote", "--json"], home)
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["selection"]["fast"] == "remote"

    config = json.loads((home / "config.json").read_text())
    assert config["models"]["selection"]["fast"] == "remote"
    names = [b["name"] for b in config["models"]["backends"]]
    assert "remote" in names
    # the local backend stays available next to the remote one
    assert "ollama" in names


def test_cli_refuses_unknown_kind(tmp_path, capsys):
    home = tmp_path / "home"
    home.mkdir()
    code = _run_cli(["models", "use", "telepathy", "remote", "--json"], home)
    assert code == 2
    assert "kind must be one of" in json.loads(capsys.readouterr().out)["error"]


def test_cli_remove_drops_selection(tmp_path, capsys):
    home = tmp_path / "home"
    home.mkdir()
    _run_cli(["models", "add", "remote", "--type", "openai",
              "--base-url", "http://127.0.0.1:9/v1",
              "--model", "fast=model-a", "--remote", "--json"], home)
    capsys.readouterr()
    _run_cli(["models", "use", "fast", "remote", "--json"], home)
    capsys.readouterr()
    code = _run_cli(["models", "remove", "remote", "--json"], home)
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["removed"] == 1
    assert "fast" not in payload["selection"]
