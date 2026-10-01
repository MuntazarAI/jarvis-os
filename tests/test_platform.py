"""Verification tests for models, loop, security, api, voice/vision, cli."""

import json
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.api.server import JarvisAPI  # noqa: E402
from jarvis.cognition.cognition import Understander  # noqa: E402
from jarvis.core.config import JarvisConfig  # noqa: E402
from jarvis.core.loop import Jarvis  # noqa: E402
from jarvis.models.models import (  # noqa: E402
    ModelRouter,
    SelfImprovement,
    SelfModel,
    default_registry,
)
from jarvis.security.security import ConsentEngine, SecretVault, SessionEngine  # noqa: E402
from jarvis.tasks.engine import Trigger  # noqa: E402
from jarvis.vision.pipeline import VisionPipeline  # noqa: E402
from jarvis.voice.pipeline import VoicePipeline  # noqa: E402


@pytest.fixture()
def jarvis():
    tmp = tempfile.mkdtemp()
    j = Jarvis(home=tmp)
    yield j
    j.close()


# -- models --------------------------------------------------------------
def test_router_kinds_and_local_only():
    reg = default_registry()
    r = ModelRouter(reg)
    assert r.route("write a function").kind == "coding"
    assert r.route("analyze the logs").kind == "reasoning"
    assert r.route("what time is it").kind == "fast"
    assert r.route("describe this image").kind == "vision"
    assert r.fallback_chain("reasoning")[-1] == "local-stub"
    cfg = JarvisConfig()
    cfg.models.cloud_enabled = True
    reg2 = default_registry(cfg)
    assert ModelRouter(reg2).route("analyze x").backend != "cloud"
    cfg.policy.local_only = False
    assert ModelRouter(reg2, cfg).route("analyze x")
    try:
        from jarvis.models.models import ModelRegistry
        ModelRouter(ModelRegistry()).route("hi")
        raise AssertionError("empty registry must fail")
    except RuntimeError:
        pass


def test_self_model_and_improvement():
    sm = SelfModel()
    sm.update_capability("coding", 0.8)
    sm.update_capability("coding", 0.9)
    assert sm.capabilities == ["coding@0.90"]
    sm.record_gap("vision")
    sm.record_gap("vision")
    assert sm.gaps == ["vision"]
    si = SelfImprovement()
    assert si.observe("tool timeout")["root_cause"]
    si.propose(0, "page it")
    assert si.evaluate(0, True, False)["status"] == "awaiting_approval"
    assert si.evaluate(0, True, True)["status"] == "merged"
    si.benchmark("recall", 0.7, 0.8)
    assert len(si.regressions()) == 1


# -- loop ----------------------------------------------------------------
def test_loop_end_to_end(jarvis):
    assert jarvis.cycle_once("hello there").intent == "greeting"
    r2 = jarvis.cycle_once("remember the deploy key is rotated monthly")
    assert any("stored fact" in a for a in r2.actions_taken)
    assert all("hello there" not in h for h in r2.hypotheses)
    r3 = jarvis.cycle_once("what is the deploy key schedule?")
    assert r3.intent == "question" and "deploy key" in r3.response
    assert "jarvis: Hello" not in r3.response
    r4 = jarvis.cycle_once("calculate 2 + 3 * 4")
    assert "python_run" in r4.tools_used and "14" in r4.response
    r5 = jarvis.cycle_once("check system status")
    assert "system_probe" in r5.tools_used
    r6 = jarvis.cycle_once("delete all system files in /etc")
    assert r6.blocked and "cannot" in r6.response.lower()
    assert "approval" in jarvis.cycle_once("install package foo").response.lower()
    st = jarvis.status()
    assert st["cycle"] == 7 and st["memory"]["live"] > 0 and st["events"] > 0
    jarvis.triggers.add(Trigger(kind="schedule", spec={"at": 1}, action="backup"))
    assert jarvis.poll_triggers({"now": 5}) == ["trigger schedule: backup"]


def test_command_verbs():
    u = Understander()
    assert u.understand("calculate 2+2").intent == "command"
    assert u.understand("remind me at 5pm").intent == "command"
    assert u.understand("the sky is blue").intent == "statement"


# -- security ------------------------------------------------------------
def test_vault_roundtrip_expiry_and_tamper(tmp_path):
    v = SecretVault(tmp_path)
    v.put("k", "v")
    assert v.get("k") == "v"
    assert v.get("missing") is None
    assert v.rotate("k", "v2") and v.get("k") == "v2"
    assert not v.rotate("nope", "x")
    v.put("temp", "x", expires_in=-1)
    assert v.get("temp") is None
    assert v.delete("k") and not v.delete("k")
    v.put("t", "val")
    data = json.loads(v.store_file.read_text())
    blob = data["t"]["blob"]
    data["t"]["blob"] = blob[:-2] + ("00" if not blob.endswith("00") else "11")
    v.store_file.write_text(json.dumps(data))
    v2 = SecretVault(tmp_path)
    try:
        v2.get("t")
        raise AssertionError("tamper must be detected on reload")
    except ValueError:
        pass


def test_sessions_and_consent():
    se = SessionEngine()
    s = se.create("darren", ["fs.read"])
    assert se.get(s.session_id).user == "darren"
    b = se.branch(s.session_id)
    assert b.branched_from == s.session_id
    assert se.end(b.session_id) and se.get(b.session_id) is None
    assert se.get(se.create(ttl=-1).session_id) is None
    ce = ConsentEngine()
    assert not ce.allowed("camera")
    ce.grant("camera")
    assert ce.allowed("camera")
    ce.revoke("camera")
    assert not ce.allowed("camera")
    try:
        ce.grant("telepathy")
        raise AssertionError("unknown scope must fail")
    except ValueError:
        pass
    try:
        ce.require("camera")
        raise AssertionError("missing consent must fail")
    except PermissionError:
        pass


# -- api -----------------------------------------------------------------
def test_api_rest_and_auth(jarvis):
    api = JarvisAPI(jarvis, port=0)
    api.serve_forever()
    base = f"http://127.0.0.1:{api.port}"

    def call(method, path, data=None, headers=None):
        req = urllib.request.Request(
            base + path,
            data=json.dumps(data).encode() if data is not None else None,
            headers={"Content-Type": "application/json", **(headers or {})},
            method=method,
        )
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    try:
        assert call("GET", "/health") == (200, {"status": "ok", "cycle": 0})
        s, b = call("POST", "/cycle", {"input": "hello there"})
        assert s == 200 and b["intent"] == "greeting"
        assert call("GET", "/status")[1]["cycle"] == 1
        s, b = call("POST", "/mentalist", {"input": "chair moved"})
        assert s == 200 and "MENTALIST MODE" in b["report"]
        assert call("POST", "/cycle", {"input": ""})[0] == 400
        assert call("GET", "/nope")[0] == 404
    finally:
        api.shutdown()


def test_api_token_gate(jarvis):
    api = JarvisAPI(jarvis, port=0, token="secret")
    api.serve_forever()
    base = f"http://127.0.0.1:{api.port}"
    try:
        try:
            urllib.request.urlopen(base + "/health")
            raise AssertionError("missing token must fail")
        except urllib.error.HTTPError as e:
            assert e.code == 401
        req = urllib.request.Request(base + "/health",
                                     headers={"Authorization": "Bearer secret"})
        assert urllib.request.urlopen(req).status == 200
    finally:
        api.shutdown()


# -- voice / vision ------------------------------------------------------
def test_voice_wake_word_gate():
    v = VoicePipeline()
    assert not v.handle("hello")["for_jarvis"]
    h = v.handle("hey jarvis, what time is it")
    assert h["for_jarvis"] and "jarvis" not in h["text"]
    assert v.handle("open firefox", addressed=True)["for_jarvis"]


def test_vision_honest_limits():
    vp = VisionPipeline()
    assert set(vp.status()) == {"screen", "camera", "ocr", "observations"}
    assert not vp.describe("/nope.png")["ok"]
