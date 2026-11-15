"""The status snapshot: read-only, auth gated, secret scrubbed.

The page that used to show it is gone; the data stays.
"""

import json
from types import SimpleNamespace

from jarvis.api.board import build_board
from jarvis.api.server import JarvisAPI


class _Bus:
    def subscribe(self, *args, **kwargs):
        return True


class _Missions:
    def list(self):
        return []

    def list_proposals(self):
        return []


class _Dots:
    def list(self):
        return []


class _Tasks:
    def stats(self):
        return {"total": 0}


class _Policy:
    approvals = {}

    def _emergency_stop(self):
        return False

    def conflicts(self):
        return 0


class _Events:
    def count(self):
        return 7

    def types(self):
        return {"cycle.completed": 7}


def _fake(home="", broken=False):
    jarvis = SimpleNamespace()
    jarvis.config = SimpleNamespace(
        paths=SimpleNamespace(home=home),
        voice=SimpleNamespace(tts_provider="fake", profile="jarvis",
                              style="calm"))
    if broken:
        jarvis.status = lambda: (_ for _ in ()).throw(RuntimeError("x"))
    else:
        jarvis.status = lambda: {"cycle": 3,
                                 "agents": {"supervisor": "ok"}}
    jarvis.missions = _Missions()
    jarvis.dots = _Dots()
    jarvis.tasks = _Tasks()
    jarvis.notifier = None
    jarvis.policy = _Policy()
    jarvis.events = _Events()
    jarvis.world = SimpleNamespace()
    jarvis.bus = _Bus()
    return jarvis


def test_snapshot_keys_and_honesty(tmp_path):
    board = build_board(_fake(str(tmp_path)))
    for key in ("service", "presence", "system", "missions",
                "durable", "voice", "approvals", "events",
                "policy"):
        assert key in board, key
    assert board["voice"]["provider"] == "fake"
    assert board["events"]["count"] == 7
    assert board["policy"]["emergency"] is False


def test_snapshot_never_raises_and_marks_unknown(tmp_path):
    board = build_board(_fake(str(tmp_path), broken=True))
    assert board["system"] == {"status": "unknown"}
    assert "generated_at" in board


def test_snapshot_survives_empty_jarvis():
    board = build_board(SimpleNamespace())
    assert isinstance(board["missions"], dict)  # never raises
    assert board["system"] == {"status": "unknown"}
    assert board["durable"] == []  # no home configured, no tasks


def test_secret_scrubbed_from_snapshot(tmp_path):
    api = JarvisAPI(_fake(str(tmp_path)), token="SECRET-TOKEN-123")
    code, payload = api.handle("GET", "/api/board", b"", {})
    assert code == 401  # header gate holds without credentials
    code, payload = api.handle("GET", "/api/board", b"", {
        "authorization": "Bearer SECRET-TOKEN-123"})
    assert code == 200
    assert "SECRET-TOKEN-123" not in json.dumps(payload)


def test_board_read_only():
    api = JarvisAPI(_fake(""))
    for path in ("/api/board",):
        code, _ = api.handle("POST", path, b"{}", {})
        assert code == 404


def test_api_board_needs_token_when_set():
    api = JarvisAPI(_fake(""), token="tok")
    code, _ = api.handle("GET", "/api/board", b"", {
        "authorization": "Bearer wrong"})
    assert code == 401


def test_http_responses_carry_a_length():
    """HTTP/1.1 without Content-Length leaves the client waiting."""
    import urllib.request

    api = JarvisAPI(_fake(""), port=0)  # 0 = a free port
    api.serve_forever()
    try:
        url = f"http://127.0.0.1:{api.port}/api/board"
        with urllib.request.urlopen(url, timeout=10) as handle:
            body = handle.read()
            assert handle.headers.get("Content-Length") == str(len(body))
            assert json.loads(body)
    finally:
        api.shutdown()
