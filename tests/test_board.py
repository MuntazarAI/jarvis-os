"""Status board: read-only snapshot, auth gating, secret hygiene."""

import json
from types import SimpleNamespace

import pytest

from jarvis.api.board import BOARD_HTML, build_board
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


def test_board_page_route_and_auth():
    api = JarvisAPI(_fake(""), token="tok")
    code, _ = api.handle("GET", "/board", b"", {})
    assert code == 401
    code, payload = api.handle("GET", "/board", b"", {
        "authorization": "Bearer tok"})
    assert code == 200
    assert payload["__html__"].startswith("<!DOCTYPE html>")
    assert "api/board" in payload["__html__"]  # relative fetch URL
    assert "sessionStorage" in payload["__html__"]  # token hygiene


def test_board_has_no_external_references():
    lowered = BOARD_HTML.lower()
    assert "src=\"http" not in lowered
    assert "href=\"http" not in lowered
    assert "@import" not in lowered


def test_board_read_only():
    api = JarvisAPI(_fake(""))
    for path in ("/api/board", "/board"):
        code, _ = api.handle("POST", path, b"{}", {})
        assert code == 404


def test_api_board_needs_token_when_set():
    api = JarvisAPI(_fake(""), token="tok")
    code, _ = api.handle("GET", "/api/board", b"", {
        "authorization": "Bearer wrong"})
    assert code == 401
