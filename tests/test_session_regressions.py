"""Regressions from a real end-to-end session.

Each test here pins a bug that a user actually hit: a busy port that
crashed instead of explaining, an argument that argparse refused, an
approval store with old-format entries, a vision call that ignored the
configured backend, and a fallback voice that produced no audio.
"""

import json
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.core.config import JarvisConfig  # noqa: E402
from jarvis.voice.tts import LocalFallbackTTSProvider, TTSRequest  # noqa: E402
from jarvis.vision.observer import VisionObserver  # noqa: E402


def _cli(home, *argv, timeout=120):
    return subprocess.run(
        [sys.executable, "-m", "jarvis.cli", "--home", str(home), *argv],
        capture_output=True, text=True, timeout=timeout)


# -- a busy port explains itself ---------------------------------------------
def test_serve_on_a_busy_port_explains_instead_of_crashing(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    with socket.socket() as held:
        held.bind(("127.0.0.1", 0))
        held.listen(1)
        port = held.getsockname()[1]
        result = _cli(home, "serve", "--port", str(port))
    assert result.returncode == 1
    assert "Address already in use" in result.stderr
    assert "Traceback" not in result.stderr
    assert "jarvis-api.service" in result.stderr


# -- world accepts a topic as a plain argument ------------------------------
def test_world_research_accepts_a_positional_topic(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    result = _cli(home, "world", "research", "ai regulation", timeout=180)
    assert "unrecognized arguments" not in result.stderr
    assert result.returncode in (0, 1)


# -- an old approval store must not crash the listing ------------------------
def test_approvals_listing_survives_old_format_entries(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    store = home / "policy-approvals.json"
    store.write_text(json.dumps({
        "version": 1,
        "approvals": {
            "appr-old": {"actor": "cli", "action": "old thing",
                         "status": "pending"},
        },
        "appr-flat": {"actor": "op", "action": "flat thing",
                      "requested_at": 1.0, "status": "pending"},
    }))
    result = _cli(home, "approvals")
    assert "Traceback" not in result.stderr
    assert result.returncode == 0
    assert "old thing" in result.stdout


# -- vision follows the configured backend -----------------------------------
class _VLHandler(BaseHTTPRequestHandler):
    seen: list[dict] = []

    def log_message(self, *args):
        return

    def _send(self, payload):
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        type(self).seen.append({"path": self.path})
        if self.path == "/v1/models":
            self._send({"data": [{"id": "vl/model"}]})
        else:
            self._send({"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode()
        type(self).seen.append({"path": self.path, "payload": json.loads(raw)})
        self._send({"model": "vl/model",
                    "choices": [{"message": {"content": "a red square"}}]})


@pytest.fixture
def vl_server():
    _VLHandler.seen = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _VLHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    host, port = httpd.server_address[0], httpd.server_address[1]
    yield f"http://{host}:{port}/v1"
    httpd.shutdown()
    httpd.server_close()


def test_vision_uses_the_selected_backend_not_the_default_one(vl_server,
                                                              tmp_path):
    cfg = JarvisConfig()
    cfg.paths.home = tmp_path
    cfg.models.backends = [{
        "name": "remote", "type": "openai", "base_url": vl_server,
        "models": {"vision": "vl/model"}, "local": False,
    }]
    cfg.models.selection = {"vision": "remote"}
    observer = VisionObserver(config=cfg)
    assert observer._vision_ready() is True
    image = tmp_path / "shot.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    assert observer._describe(str(image), "what is this?") == "a red square"
    posts = [s for s in _VLHandler.seen if s.get("path", "").endswith(
        "/chat/completions")]
    assert posts, "the configured backend must serve the vision call"


# -- the fallback voice must produce audio -----------------------------------
def test_local_fallback_voice_writes_a_real_audio_file(tmp_path):
    provider = LocalFallbackTTSProvider()
    if not provider.available():
        pytest.skip("no local TTS backend installed")
    dest = tmp_path / "speech.wav"
    result = provider.synthesize(TTSRequest(text="Muntazar"), dest)
    assert result.ok, result.error
    assert result.audio_path == str(dest)
    assert dest.exists() and dest.stat().st_size > 1000
    assert result.audio_bytes > 1000
