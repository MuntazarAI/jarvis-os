"""Command centre page: elfaria-style layout, live data only.

Route, fidelity (all regions present), hygiene (offline, no secrets),
task create/read endpoints, CLI pointer.
"""

import json
from types import SimpleNamespace

from jarvis.api.command_page import COMMAND_HTML
from jarvis.api.server import JarvisAPI


class _Bus:
    def subscribe(self, *a, **k):
        return True


def _api(token=""):
    fake = SimpleNamespace(
        bus=_Bus(), cycle=0,
        config=SimpleNamespace(
            paths=SimpleNamespace(home=""),
            voice=SimpleNamespace(), world=None))
    return JarvisAPI(fake, token=token)


def test_command_route_is_public_shell():
    api = _api(token="tok")
    code, payload = api.handle("GET", "/command", b"", {})
    assert code == 200
    assert payload["__html__"].startswith("<!DOCTYPE html>")


def test_command_regions_present():
    for marker in ("JARVIS", "Agent Command Room", "JARVIS CORE",
                   "Mission Control", "Task Queue", "System Status",
                   "Recent Activity", "Memory Palace", "Knowledge Graph",
                   "Tools & Integrations", "Ask JARVIS anything",
                   "COMMAND CENTER", "QUICK ACTIONS"):
        assert marker in COMMAND_HTML, marker


def test_command_hygiene():
    lowered = COMMAND_HTML.lower()
    assert "src=\"http" not in lowered
    assert "href=\"http" not in lowered
    assert "sessionStorage" in COMMAND_HTML
    assert "api/experience" in COMMAND_HTML
    assert "alert(" not in lowered  # no dead demo popups


def test_command_post_has_no_page_route():
    api = _api()
    code, _ = api.handle("POST", "/command", b"{}", {})
    assert code == 404


def test_task_create_and_read(tmp_path):
    from jarvis.api.server import JarvisAPI as API

    class Events:
        def record(self, *a, **k):
            return None

    fake = SimpleNamespace(
        bus=_Bus(), cycle=0,
        config=SimpleNamespace(
            paths=SimpleNamespace(home=str(tmp_path)),
            voice=SimpleNamespace(), world=None),
        policy=SimpleNamespace(
            emergency_stop_engaged=lambda: False),
        events=Events())
    api = API(fake, token="")
    code, out = api.handle(
        "POST", "/api/tasks",
        json.dumps({"title": "file the report",
                    "steps": [{"title": "draft"},
                              {"title": "send"}]}).encode(), {})
    assert code == 201, out
    assert out["state"] == "ready" and out["steps"] == 2
    tid = out["task_id"]
    code, out = api.handle("GET", f"/api/tasks/{tid}", b"", {})
    assert code == 200
    assert out["title"] == "file the report"
    assert [s["title"] for s in out["steps"]] == ["draft", "send"]
    assert all("state" in s for s in out["steps"])


def test_task_create_validation():
    api = _api()
    code, _ = api.handle("POST", "/api/tasks", b"{}", {})
    assert code == 400  # title required
    code, _ = api.handle("POST", "/api/tasks", b"nope", {})
    assert code == 400
    code, _ = api.handle(
        "POST", "/api/tasks",
        json.dumps({"title": "t", "steps": []}).encode(), {})
    assert code == 400
    code, _ = api.handle("GET", "/api/tasks/nope-x", b"", {})
    assert code == 404
    code, _ = api.handle("GET", "/api/tasks/bad!id", b"", {})
    assert code == 400
