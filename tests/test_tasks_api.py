"""Task endpoints: create, read and validate.

The pages are gone; the API behind them is what a new frontend will
use.
"""

import json
from types import SimpleNamespace

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
