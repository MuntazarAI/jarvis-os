"""Experience Layer 1.0: presence mapping, snapshot, gated endpoints.

No network beyond localhost, no models, no mic. WebSocket auth is
tested over a real socket against an ephemeral-port server.
"""

import base64
import json
import os
import socket
from types import SimpleNamespace

import pytest

from jarvis.api.experience import build_experience, presence_state
from jarvis.api.server import JarvisAPI


class _Bus:
    def subscribe(self, *a, **k):
        return True


class _Policy:
    def __init__(self):
        self.approvals = {}

    def _emergency_stop(self):
        return False

    def conflicts(self):
        return 0

    def approve(self, token, by="user"):
        entry = self.approvals.get(token)
        if not isinstance(entry, dict) or entry.get("status") != \
                "pending":
            return False
        entry["status"] = "approved"
        return True

    def deny(self, token, by="user"):
        entry = self.approvals.get(token)
        if not isinstance(entry, dict) or entry.get("status") != \
                "pending":
            return False
        entry["status"] = "denied"
        return True


class _Events:
    def __init__(self):
        self.items = []

    def record(self, type, payload=None, **kw):
        self.items.append({"type": type, "payload": payload or {}})
        return SimpleNamespace(seq=len(self.items))

    def count(self):
        return len(self.items)

    def types(self):
        return {}

    def last_seq(self):
        return len(self.items)

    def stream(self, since=0, limit=None):
        return []


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


def _fake(home="", policy=None):
    return SimpleNamespace(
        bus=_Bus(), cycle=1,
        config=SimpleNamespace(
            paths=SimpleNamespace(home=home),
            voice=SimpleNamespace(tts_provider="fake", profile="j",
                                  style="calm"),
            world=SimpleNamespace(topics=["security"])),
        status=lambda: {"cycle": 1, "agents": {"agents": [
            {"name": "supervisor", "state": "idle", "tasks_done": 1,
             "tasks_failed": 0}]}, "memory": {}, "events": {},
            "policy_conflicts": 0, "tasks": {}},
        missions=_Missions(), dots=_Dots(), tasks=_Tasks(),
        notifier=None, policy=policy or _Policy(), events=_Events(),
        world=SimpleNamespace(), device_fabric=None,
        proactive=SimpleNamespace(
            notifications=[{"text": "hello", "level": "info"}]))


# -- presence mapping (pure) ----------------------------------------------------

def test_presence_priority_order():
    assert presence_state() == "IDLE"
    assert presence_state(ready_tasks=2) == "PLANNING"
    assert presence_state(ready_tasks=2, verifying_tasks=1) == \
        "VERIFYING"
    assert presence_state(verifying_tasks=1, running_tasks=1) == \
        "EXECUTING"
    assert presence_state(running_tasks=1,
                          approvals_pending=1) == "WAITING"
    assert presence_state(approvals_pending=1, failed_tasks=1) == \
        "ALERT"
    assert presence_state(policy_conflicts=2) == "ALERT"
    assert presence_state(failed_tasks=1, emergency=True) == "E_STOP"


# -- snapshot ---------------------------------------------------------------------

def test_snapshot_shape_and_honesty(tmp_path):
    snap = build_experience(_fake(str(tmp_path)))
    for key in ("presence", "system", "mesh", "missions", "durable",
                "task_counts", "approvals", "policy", "security",
                "world", "voice", "service", "devices",
                "notifications", "timeline", "settings_mode"):
        assert key in snap, key
    assert snap["presence"] == "IDLE"
    assert snap["mesh"][0]["name"] == "supervisor"
    assert snap["world"]["topics"] == ["security"]
    assert "read-only" in snap["settings_mode"]


def test_snapshot_never_raises_and_scrubs():
    snap = build_experience(SimpleNamespace())
    assert snap["presence"] == "IDLE"
    assert "generated_at" in snap
    assert "SECRET" not in json.dumps(snap)


def test_snapshot_hides_full_approval_tokens(tmp_path):
    policy = _Policy()
    policy.approvals["appr-full-secret-token"] = {
        "actor": "a", "action": "restart", "status": "pending",
        "requested_at": 0.0}
    snap = build_experience(_fake(str(tmp_path), policy=policy))
    assert "appr-full-secret-token" not in json.dumps(snap)
    assert snap["approvals"][0]["token_hint"].startswith("appr-ful")


# -- approvals endpoint -------------------------------------------------------------

def test_approval_decision_flow(tmp_path):
    policy = _Policy()
    policy.approvals["appr-abc123"] = {
        "actor": "a", "action": "restart", "status": "pending",
        "requested_at": 0.0}
    api = JarvisAPI(_fake(str(tmp_path), policy=policy), token="tok")
    auth = {"authorization": "Bearer tok"}
    code, out = api.handle("POST", "/api/approvals/decision",
                           json.dumps({"token": "appr-abc123",
                                       "approve": True}).encode(),
                           auth)
    assert code == 200 and out == {"ok": True, "approved": True}
    assert "appr-abc123" not in json.dumps(out)  # never echoed
    recorded = api.jarvis.events.items
    assert recorded and recorded[0]["type"] == "approval.decided"
    code, out = api.handle("POST", "/api/approvals/decision",
                           json.dumps({"token": "appr-abc123",
                                       "approve": True}).encode(),
                           auth)
    assert out == {"ok": False,
                   "reason": "unknown or already redeemed"}


def test_approval_decision_validation():
    api = JarvisAPI(_fake(""), token="tok")
    auth = {"authorization": "Bearer tok"}
    code, _ = api.handle("POST", "/api/approvals/decision",
                         b"{}", auth)
    assert code == 400  # malformed token
    code, _ = api.handle("POST", "/api/approvals/decision",
                         json.dumps({"token": "appr-1",
                                     "approve": "yes"}).encode(),
                         auth)
    assert code == 400  # approve must be boolean
    code, _ = api.handle("POST", "/api/approvals/decision",
                         b"nope", auth)
    assert code == 400
    code, _ = api.handle("POST", "/api/approvals/decision",
                         json.dumps({"token": "appr-1",
                                     "approve": True}).encode(), {})
    assert code == 401  # bearer gate holds


# -- task endpoints -------------------------------------------------------------------

def _seed_task(home):
    from jarvis.durable import DurableRunner, TaskStore
    store = TaskStore(str(home))
    runner = DurableRunner(store)
    task = runner.create(title="op task", steps=[{"title": "s"}])
    runner.mark_ready(task.task_id)
    return task.task_id


def test_task_pause_resume_cancel_recover(tmp_path):
    api = JarvisAPI(_fake(str(tmp_path)), token="")
    tid = _seed_task(tmp_path)
    for verb, want in (("pause", "paused"), ("resume", "ready"),
                       ("recover", "ready")):
        code, out = api.handle("POST", f"/api/tasks/{tid}/{verb}",
                               b"{}", {})
        assert code == 200, (verb, out)
        assert out["state"] == want, (verb, out)
    code, out = api.handle(
        "POST", f"/api/tasks/{tid}/cancel",
        json.dumps({"reason": "ui test"}).encode(), {})
    assert code == 200 and out["state"] == "cancelled"


def test_task_endpoint_errors(tmp_path):
    api = JarvisAPI(_fake(str(tmp_path)), token="")
    code, _ = api.handle("POST", "/api/tasks/nope-x/pause", b"{}",
                         {})
    assert code == 404
    code, _ = api.handle("POST", "/api/tasks/bad!id/pause", b"{}",
                         {})
    assert code == 400
    code, _ = api.handle("POST", "/api/tasks/x/selfdestruct", b"{}",
                         {})
    assert code == 404
    code, _ = api.handle("POST", "/api/tasks/x/pause", b"{bad",
                         {})
    assert code == 400
    tid = _seed_task(tmp_path)  # READY: pause works, advance runs
    code, out = api.handle("POST", f"/api/tasks/{tid}/pause", b"{}",
                           {})
    assert code == 200
    import jarvis.durable.task as _task_mod
    from jarvis.durable import TaskStore
    fresh = _task_mod.Task(title="planning only",
                           steps=[_task_mod.TaskStep(title="s")])
    fresh.transition(_task_mod.TaskState.PLANNING)
    store = TaskStore(str(tmp_path))
    store.create(fresh)
    code, out = api.handle("POST", f"/api/tasks/{fresh.task_id}/advance",
                           b"{}", {})
    assert code == 409  # planning is not advanceable; nothing executed


# -- websocket auth over a real socket -----------------------------------------------

def _ws_handshake(port, path):
    sock = socket.create_connection(("127.0.0.1", port), timeout=10)
    key = base64.b64encode(os.urandom(16)).decode()
    sock.sendall(
        f"GET {path} HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\n"
        f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
        f"Sec-WebSocket-Version: 13\r\n\r\n".encode())
    data = sock.recv(1024).decode(errors="replace")
    sock.close()
    return data.split("\r\n", 1)[0]


def test_websocket_rejects_missing_token():
    api = JarvisAPI(_fake(""), token="tok", port=0)
    api.serve_forever()
    try:
        assert "403" in _ws_handshake(api.port, "/")
        assert "101" in _ws_handshake(api.port, "/?token=tok")
        assert "403" in _ws_handshake(api.port, "/?token=wrong")
    finally:
        api.shutdown()


def test_websocket_open_without_server_token():
    api = JarvisAPI(_fake(""), port=0)
    api.serve_forever()
    try:
        assert "101" in _ws_handshake(api.port, "/")
    finally:
        api.shutdown()


# -- scan history ------------------------------------------------------------------------

def test_scan_history_bounded_and_summaries_only(tmp_path):
    from jarvis.security.strix import read_history, record_history
    home = str(tmp_path)
    for i in range(25):
        record_history(home, {"at": float(i), "target": "t",
                              "mode": "quick", "status": "no-findings",
                              "summary": f"s{i}", "duration_s": 0.1,
                              "findings": {}, "log_tail": "x" * 5000,
                              "secret": "drop me"})
    items = read_history(home)
    assert len(items) == 20  # bounded
    assert all("log_tail" not in item and "secret" not in item
               for item in items)
    assert items[-1]["summary"] == "s24"


def test_experience_page_markers():
    from jarvis.api.experience_page import EXPERIENCE_HTML
    lowered = EXPERIENCE_HTML.lower()
    assert "src=\"http" not in lowered
    assert "href=\"http" not in lowered
    assert "api/experience" in EXPERIENCE_HTML
    assert "prefers-reduced-motion" in EXPERIENCE_HTML


def test_perf_budgets(tmp_path):
    import time
    from jarvis.api.experience_page import EXPERIENCE_HTML
    snap = build_experience(_fake(str(tmp_path)))
    started = time.perf_counter()
    build_experience(_fake(str(tmp_path)))
    elapsed_ms = (time.perf_counter() - started) * 1000
    assert elapsed_ms < 1000, f"snapshot too slow: {elapsed_ms:.0f}ms"
    assert len(EXPERIENCE_HTML.encode()) < 150 * 1024
    assert len(json.dumps(snap).encode()) < 500 * 1024
