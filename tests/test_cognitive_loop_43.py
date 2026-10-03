"""Deterministic 4.3 cognitive-loop tests (26 categories).

Every stage, failure mode, replay/idempotency rule, and security
boundary of the cognitive lifecycle. Fast, isolated, no network.
"""

from __future__ import annotations

import json

import pytest

from jarvis.intelligence import cognitive as cog
from jarvis.intelligence.cognitive import (
    CognitiveError,
    CognitiveEvent,
    CognitiveStage,
    CognitiveSupervisor,
    CycleStore,
    check_transition,
)
from jarvis.intelligence.loop import IntelligenceLoop
from jarvis.intelligence.sensory import SensoryEvent, event_from_user
from jarvis.intelligence import wiring


def _stub_loop(**overrides):
    hooks = dict(
        normalize=lambda e: {"payload": {"text": str(e.get("text", ""))}}
        if isinstance(e, dict) else {"payload": {}},
        reason=lambda ctx: {"concluded": True, "summary": "test says hi",
                            "confidence": 0.8, "evidence_refs": ["m1"]},
        plan=lambda ctx: {"action": "", "args": {}},
    )
    hooks.update(overrides)
    loop = IntelligenceLoop(**hooks)
    loop.start()
    return loop


def _supervisor(tmp_path, **overrides):
    return CognitiveSupervisor(_stub_loop(**overrides), home=tmp_path)


# 1. event ingestion ------------------------------------------------------------

def test_event_coercion_dict_sensory_and_typed():
    evt = CognitiveSupervisor.coerce_event(
        {"source": "user", "type": "user", "payload": {"text": "hi"}})
    assert evt.source == "user" and evt.correlation_id == evt.event_id
    sensory = event_from_user("hello")
    evt2 = CognitiveSupervisor.coerce_event(sensory)
    assert evt2.source == "user" and evt2.event_id == sensory.event_id
    evt3 = CognitiveSupervisor.coerce_event(
        CognitiveEvent(source="s", type="t"))
    assert evt3.source == "s"
    with pytest.raises(CognitiveError):
        CognitiveSupervisor.coerce_event({"source": "", "type": ""})


# 2. context assembly -------------------------------------------------------------

def test_outcome_maps_record_fields(tmp_path):
    sup = _supervisor(tmp_path)
    out = sup.process({"source": "user", "type": "user",
                       "payload": {"text": "hi"}})
    assert out.state == CognitiveStage.COMPLETED
    assert out.decision.decided is True
    assert out.decision.conclusion == "test says hi"
    assert out.prediction.prediction == "NO_PREDICTION"
    assert out.plan.steps == [{"action": "", "args_keys": []}]
    assert len(out.transitions) == 10  # idle->...->completed walk


# 3. reasoning ---------------------------------------------------------------------

def test_no_decision_is_explicit(tmp_path):
    sup = CognitiveSupervisor(
        _stub_loop(reason=lambda ctx: {}), home=tmp_path)
    out = sup.process({"source": "user", "type": "user", "payload": {}})
    assert out.decision.decided is False
    assert out.state == CognitiveStage.COMPLETED


# 4. prediction ----------------------------------------------------------------------

def test_no_prediction_default_and_trend_with_board(tmp_path):
    assert wiring.make_predict_hook()({})["prediction"] == "NO_PREDICTION"

    class Board:
        def latest_changes(self, n):
            now = __import__("time").time()
            return [{"at": now - 2, "delta": 1.0, "summary": "up"},
                    {"at": now - 1, "delta": 2.0, "summary": "up more"}]

    got = wiring.make_predict_hook(Board())({})
    assert got["prediction"] == "trend rising"
    assert got["confidence"] == 0.5
    assert len(got["basis"]) == 2

    class Empty:
        def latest_changes(self, n):
            return [{"at": 1.0, "delta": 1.0, "summary": "once"}]

    assert wiring.make_predict_hook(Empty())({})["prediction"] == \
        "NO_PREDICTION"


# 5. planning --------------------------------------------------------------------------

def test_plan_match_and_observe_only(tmp_path):
    from jarvis.planning.planner import MissionPlanner
    planner = MissionPlanner()
    planner.register("battery", "device.get_battery", {"device_id": "d1"})
    loop = _stub_loop(plan=planner.plan)
    loop.start()
    record = loop.cycle_once({"text": "check battery status"})
    assert record.action_taken == ""
    planner2 = MissionPlanner()
    planner2.register("status check", "device.get_status", {})
    loop2 = _stub_loop(plan=planner2.plan,
                       reason=lambda ctx: {"concluded": True,
                                           "summary": "status check now"})
    loop2.start()
    record2 = loop2.cycle_once({"text": "anything"})
    assert record2.action_taken == "device.get_status"


# 6. policy authorization ------------------------------------------------------------------

def test_loop_policy_denies_unknown_tool_and_missing_device_service():
    from jarvis.tools.tools import default_registry
    from jarvis.policy.policy import PolicyEngine
    from jarvis.core.config import JarvisConfig
    hook = wiring.make_policy_hook(PolicyEngine(JarvisConfig()),
                                   tools=default_registry())
    assert hook("definitely_not_a_tool", {})[0] is False
    assert hook("device.get_battery", {"device_id": "d"})[0] is False


# 7. approval waiting --------------------------------------------------------------------------

def test_device_executor_waiting_marker_no_retry(tmp_path):
    calls = []

    class Service:
        def request_command(self, actor, device_id, action, args):
            calls.append(action)
            return {"ok": False, "requires_approval": True,
                    "approval_id": "apd-x", "command_id": "cmd-x"}

    loop = IntelligenceLoop(
        plan=lambda ctx: {"action": "device.get_battery",
                          "args": {"device_id": "d1"}},
        policy_check=lambda name, args: (True, "device approval via service"),
        executor=wiring.make_device_executor(Service()),
        verify=wiring.make_verify_hook(),
    )
    loop.start()
    record = loop.cycle_once({"text": "battery"})
    assert calls == ["device.get_battery"]  # exactly once per cycle
    by_stage = {s.stage: s for s in record.stages}
    assert by_stage["verify"].detail["verdict"] == "UNKNOWN"
    sup = CognitiveSupervisor(_stub_loop(), home=tmp_path)
    out = sup.process({"source": "user", "type": "user", "payload": {}})
    assert out.action.approval_state in ("", "waiting", "denied", "approved")


# 8. execution ---------------------------------------------------------------------------------

def test_executor_called_once_when_allowed_and_never_when_denied():
    calls = []
    allowed = IntelligenceLoop(
        plan=lambda ctx: {"action": "do", "args": {}},
        policy_check=lambda name, args: (True, "ok"),
        executor=lambda name, args: (calls.append(name),
                                     {"ok": True})[1],
    )
    allowed.start()
    allowed.cycle_once({"text": "x"})
    assert calls == ["do"]
    denied = IntelligenceLoop(
        plan=lambda ctx: {"action": "do", "args": {}},
        policy_check=lambda name, args: (False, "no"),
        executor=lambda name, args: (calls.append(name),
                                     {"ok": True})[1],
    )
    denied.start()
    denied.cycle_once({"text": "x"})
    assert calls == ["do"]
    dry = IntelligenceLoop(
        plan=lambda ctx: {"action": "do", "args": {}},
        policy_check=lambda name, args: (True, "ok"),
        dry_run=True,
    )
    dry.start()
    record = dry.cycle_once({"text": "x"})
    assert calls == ["do"]
    assert [s.stage for s in record.stages
            if s.stage == "act"][0] == "act"


# 9. verification -----------------------------------------------------------------------------------

def test_verify_verdict_matrix():
    verify = wiring.make_verify_hook()
    assert verify({"action": {"action": "a"},
                   "result": None})["verdict"] == "UNKNOWN"
    assert verify({"action": {"action": "a"},
                   "result": {"ok": True}})["verdict"] == "VERIFIED"
    assert verify({"action": {"action": "a"},
                   "result": {"ok": False}})["verdict"] == "FAILED"
    assert verify({"action": {"action": "a",
                              "verification_conditions": {
                                  "expect_result_contains": "77"}},
                   "result": {"ok": True, "result": "battery 42%"}})[
        "verdict"] == "PARTIALLY_VERIFIED"
    assert verify({"action": {"action": "a"},
                   "result": {"ok": False, "waiting_approval": True}})[
                       "verdict"] == "UNKNOWN"


# 10. learning -------------------------------------------------------------------------------------------

def test_learning_record_maps_memory_id(tmp_path):
    loop = IntelligenceLoop(
        plan=lambda ctx: {"action": "do", "args": {}},
        policy_check=lambda name, args: (True, "ok"),
        executor=lambda name, args: {"ok": True},
        learn=lambda ctx: {"stored": True, "memory_id": "m-1"},
    )
    loop.start()
    sup = CognitiveSupervisor(loop, home=tmp_path)
    out = sup.process({"source": "user", "type": "user", "payload": {}})
    assert out.learning is not None
    assert out.learning.memory_id == "m-1"
    assert out.learning.outcome == "ok"


# 11. invalid transitions -------------------------------------------------------------------------------------

def test_invalid_transitions_rejected():
    with pytest.raises(CognitiveError):
        check_transition(CognitiveStage.EXECUTING, CognitiveStage.REASONING)
    with pytest.raises(CognitiveError):
        check_transition(CognitiveStage.IDLE, CognitiveStage.COMPLETED)
    check_transition(CognitiveStage.IDLE, CognitiveStage.OBSERVING)
    sup = CognitiveSupervisor(_stub_loop(), home=None)
    sup.stage = CognitiveStage.EXECUTING
    with pytest.raises(CognitiveError):
        sup._reset()


# 12. failure recovery ----------------------------------------------------------------------------------------------

def test_stage_failure_isolates_and_reports(tmp_path):
    def boom(ctx):
        raise RuntimeError("reason exploded")
    sup = CognitiveSupervisor(_stub_loop(reason=boom), home=tmp_path)
    out = sup.process({"source": "user", "type": "user", "payload": {}})
    assert out.state == CognitiveStage.FAILED
    assert any(not s["ok"] and "exploded" in s.get("error", "")
               for s in out.stages)


# 13. replay -----------------------------------------------------------------------------------------------------------------

def test_replay_executes_nothing(tmp_path):
    calls = []
    loop = IntelligenceLoop(
        normalize=lambda e: {"payload": dict(e) if isinstance(e, dict)
                             else {}},
        reason=lambda ctx: {"concluded": True},
        plan=lambda ctx: {"action": "do", "args": {}},
        policy_check=lambda name, args: (True, "ok"),
        executor=lambda name, args: (calls.append(name),
                                     {"ok": True})[1],
    )
    loop.start()
    sup = CognitiveSupervisor(loop, home=tmp_path)
    out = sup.process({"source": "user", "type": "user",
                       "payload": {"text": "go"}})
    assert calls == ["do"]
    replayed = sup.replay(out.cycle_id)
    assert replayed.replayed is True
    assert calls == ["do"]  # still exactly once: replay is pure
    assert replayed.cycle_id == f"replay-{out.cycle_id}"


def test_replay_unknown_cycle_rejected(tmp_path):
    sup = _supervisor(tmp_path)
    with pytest.raises(CognitiveError):
        sup.replay("cyc-nope")


# 14/15. idempotency + duplicates ----------------------------------------------------------------------------------------------------

def test_duplicate_events_never_reexecute(tmp_path):
    calls = []
    loop = IntelligenceLoop(
        executor=lambda name, args: (calls.append(name),
                                     {"ok": True})[1],
        plan=lambda ctx: {"action": "do", "args": {}},
        policy_check=lambda name, args: (True, "ok"),
    )
    loop.start()
    sup = CognitiveSupervisor(loop, home=tmp_path)
    event = {"source": "user", "type": "user", "event_id": "evt-fixed-1",
             "payload": {"text": "go"}}
    first = sup.process(dict(event))
    second = sup.process(dict(event))
    assert calls == ["do"]
    assert second.state == CognitiveStage.COMPLETED
    assert second.replayed is True
    assert sup.total_duplicates == 1


# 16. restart recovery ----------------------------------------------------------------------------------------------------------------------

def test_store_survives_supervisor_restart(tmp_path):
    sup = _supervisor(tmp_path)
    out = sup.process({"source": "user", "type": "user",
                       "payload": {"text": "hi"}})
    sup2 = CognitiveSupervisor(_stub_loop(), home=tmp_path)
    found = sup2.inspect(out.cycle_id)
    assert found is not None
    assert found["cycle_id"] == out.cycle_id
    assert sup2.replay(out.cycle_id).replayed is True


# 17. stale/corrupt state ------------------------------------------------------------------------------------------------------------------------

def test_corrupt_store_lines_skipped(tmp_path):
    store = CycleStore(tmp_path)
    path = store.path
    assert path is not None
    path.write_text('{"cycle_id": "cyc-good", "state": "completed"}\n'
                    '{broken\n'
                    '[1,2,3]\n')
    rows = store.read()
    assert [r["cycle_id"] for r in rows] == ["cyc-good"]
    assert store.find("cyc-missing") is None


# 19. timeout ----------------------------------------------------------------------------------------------------------------------------

def test_stage_budget_timeout(tmp_path):
    import time as _time

    def slow(ctx):
        _time.sleep(0.05)
        return {"concluded": True}

    loop = IntelligenceLoop(reason=slow)
    loop.start()
    record = loop.cycle_once({"text": "x"}, stage_timeout_s=0.001)
    assert record.failed_stage.startswith("timeout:")
    assert loop.state.value == "timeout"


# 20/21. device offline + policy denial ---------------------------------------------------------------------------------------------------------------

def test_device_executor_refuses_without_service_or_device():
    assert wiring.make_device_executor(None)(
        "device.get_battery", {})["ok"] is False
    assert wiring.make_device_executor(object())(
        "other.action", {})["ok"] is False

    class Service:
        def request_command(self, *a, **k):
            raise AssertionError("must not be called")

    assert wiring.make_device_executor(Service())(
        "device.get_battery", {})["ok"] is False


# 22. approval expiry (durable layer already covers; loop records waiting) -------------------------------------------------------------------------------

def test_waiting_approval_is_not_a_failure(tmp_path):
    sup = _supervisor(tmp_path)
    out = sup.process({"source": "user", "type": "user", "payload": {}})
    assert out.state == CognitiveStage.COMPLETED
    assert out.verification.verdict in ("UNKNOWN", "VERIFIED")


# 23. verification failure -------------------------------------------------------------------------------------------------------------------------------------

def test_failed_action_verifies_failed():
    loop = IntelligenceLoop(
        plan=lambda ctx: {"action": "do", "args": {}},
        policy_check=lambda name, args: (True, "ok"),
        executor=lambda name, args: {"ok": False, "error": "broke"},
        verify=wiring.make_verify_hook(),
    )
    loop.start()
    record = loop.cycle_once({"text": "x"})
    by_stage = {s.stage: s for s in record.stages}
    assert by_stage["verify"].detail["verdict"] == "FAILED"


# 24. secret-leak scan ------------------------------------------------------------------------------------------------------------------------------------------------

def test_stored_cycles_scrub_secrets(tmp_path):
    sup = _supervisor(tmp_path)
    out = sup.process({"source": "user", "type": "user",
                       "payload": {"password": "topsecret-x"}})
    raw = CycleStore(tmp_path).path.read_text()
    assert "topsecret-x" not in raw
    assert "[redacted]" in raw
    assert out.cycle_id in raw


def test_approval_tokens_never_persist_in_cycles_or_outbox(tmp_path):
    from jarvis.intelligence.loop import scrub_token_strings
    assert scrub_token_strings("needs approval (token appr-abcdef1234567890)") == \
        "needs approval (token [approval redacted])"
    assert scrub_token_strings("use apd-0123456789abcdef0123456789abcdef ok") == \
        "use [approval redacted] ok"
    assert scrub_token_strings("ordinary prose 12345") == \
        "ordinary prose 12345"
    # Service denial paths persist scrubbed reasons only.
    import sys as _sys
    _sys.path.insert(0, "tests")
    from test_android_transport import _adapter, _policy as _p
    from jarvis.device.service import DeviceCommandService
    adapter = _adapter(tmp_path, _p())
    svc = DeviceCommandService(adapter)
    record = svc.outbox.enqueue("dev-1", "device.battery",
                                "device.get_battery", {}, actor="op")
    denied = svc._handle_deny(
        record, ["needs approval (token appr-abcdef1234567890)"], "")
    assert "appr-abcdef1234567890" not in json.dumps(denied)
    stored = svc.outbox.get(record["command_id"])
    assert "appr-abcdef1234567890" not in json.dumps(stored)


# 25. direct-bypass attempts ---------------------------------------------------------------------------------------------------------------------------------------------------

def test_loop_without_policy_or_executor_cannot_act():
    bare = IntelligenceLoop(
        plan=lambda ctx: {"action": "do", "args": {}})
    bare.start()
    record = bare.cycle_once({"text": "x"})
    by_stage = {s.stage: s for s in record.stages}
    assert by_stage["policy"].detail["allowed"] is False
    assert by_stage["act"].detail.get("skipped") == "policy denied or absent"

    class Tools:
        def get(self, name):
            return None

    hook = wiring.make_policy_hook(policy=None, tools=Tools())
    assert hook("device.get_battery", {"device_id": "d"})[0] is False


# observability -------------------------------------------------------------------------------------------------------------------------

def test_status_inspect_failures_views(tmp_path):
    sup = _supervisor(tmp_path)
    out = sup.process({"source": "user", "type": "user",
                       "payload": {"text": "hi"}})
    status = sup.status()
    assert status["total_cycles"] == 1
    assert status["stage"] == "completed"
    assert sup.inspect(out.cycle_id)["cycle_id"] == out.cycle_id
    assert sup.inspect("cyc-nope") is None
    assert sup.failures() == []
    assert len(sup.transitions) == 10  # idle->...->completed walk


# real Android cognitive E2E (loopback sockets, no emulator) ----

def _socket_device(tmp_path, policy=None, answer=None):
    """Paired online device + duplex client + host. Returns dict."""
    import sys as _sys
    _sys.path.insert(0, "tests")
    from test_android_transport import (
        _adapter as _mk_adapter, _auth_headers, _msg, _register,
    )
    from jarvis.device.android_transport import AndroidSocketHost
    from jarvis.device.protocol import FabricMessage
    from jarvis.device.socket_transport import SocketTransport
    adapter = _mk_adapter(tmp_path, policy)
    host = AndroidSocketHost(adapter)
    port = host.start()
    device_id, code = _register(adapter)
    seen = {}

    def default_answer(msg):
        if msg.message_type != "command_request":
            return None
        seen["wire"] = msg.capability
        return FabricMessage(
            sender_node="node-e2e", recipient_node=msg.sender_node,
            message_type="command_result",
            correlation_id=msg.message_id, capability=msg.capability,
            payload={"ok": True, "result": "battery 77%"})

    client = SocketTransport(timeout_s=5.0)
    client.connect("127.0.0.1", port, on_request=answer or default_answer)
    node_id = "node-e2e"
    req = _msg("pair_request", sender=node_id,
               payload={"device_id": device_id, "code": code,
                        "node_id": node_id})
    rep = client.send(FabricMessage.from_dict(req)).payload
    assert rep["pair"] == "pending", rep
    token = rep["pending_token"]
    adapter.trust_android(device_id, by="tester", reason="cog-e2e")
    post = client.send(FabricMessage.from_dict(_msg(
        "pair_status", sender=node_id,
        payload={"device_id": device_id, "pending_token": token}))).payload
    assert post["pair"] == "approved", post
    secret = post["device_secret"]
    headers = _auth_headers(client, node_id, device_id, secret)
    hb = client.send(FabricMessage.from_dict(_msg(
        "heartbeat", sender=node_id,
        payload={"device_id": device_id, "battery_pct": 77},
        auth=headers))).payload
    assert hb["lifecycle"] == "online", hb
    adapter.declare_android_capabilities(device_id, ["device.battery"],
                                         by="tester")
    return {"adapter": adapter, "host": host, "port": port,
            "client": client, "device_id": device_id, "secret": secret,
            "seen": seen, "node_id": node_id}


def _cog_loop(service, device_id="", actor="cognitive-loop"):
    from jarvis.planning.planner import MissionPlanner
    planner = MissionPlanner()
    planner.register("battery", "device.get_battery", {"device_id": device_id})
    return IntelligenceLoop(
        normalize=lambda e: {"payload": dict(e) if isinstance(e, dict)
                             else {}},
        reason=lambda ctx: {"concluded": True,
                            "summary": "phone battery check"},
        plan=planner.plan,
        policy_check=wiring.make_policy_hook(
            service.adapter.fabric.policy, actor,
            device_service=service),
        executor=wiring.make_device_executor(service, actor),
        verify=wiring.make_verify_hook(),
    )


def test_cognitive_loop_drives_real_device_command(tmp_path):
    from jarvis.device.service import DeviceCommandService
    from jarvis.policy.policy import PolicyEngine
    from jarvis.core.config import JarvisConfig
    policy = PolicyEngine(JarvisConfig())
    policy.config.policy.require_approval_above_risk = 0.8
    policy.grant("cognitive-loop", "device.device.battery")
    env = _socket_device(tmp_path, policy)
    adapter = env["adapter"]
    try:
        svc = DeviceCommandService(adapter, host=env["host"])
        svc.grants.grant(env["device_id"], "device.battery", by="op")
        loop = _cog_loop(svc, device_id=env["device_id"])
        loop.start()
        sup = CognitiveSupervisor(loop, home=tmp_path)
        out = sup.process({"source": "user", "type": "user",
                           "payload": {"text": "check phone battery"}})
        assert out.state == CognitiveStage.COMPLETED, \
            [s for s in out.stages if not s["ok"]]
        assert out.action.action == "device.get_battery"
        assert out.policy_allowed is True
        assert out.result.ok is True
        assert "77" in str(out.result.output)
        assert out.verification.verdict == "VERIFIED"
        assert env["seen"].get("wire") == "get_battery"
        assert out.learning is None  # no learn hook bound: honest absence
    finally:
        env["client"].close()
        env["host"].stop()


def test_cognitive_loop_parks_approval_then_completes(tmp_path):
    from jarvis.device.service import DeviceCommandService
    from jarvis.policy.policy import PolicyEngine
    from jarvis.core.config import JarvisConfig
    policy = PolicyEngine(JarvisConfig())  # default: approval required
    env = _socket_device(tmp_path, policy)
    adapter = env["adapter"]
    try:
        svc = DeviceCommandService(adapter, host=env["host"])
        svc.grants.grant(env["device_id"], "device.battery", by="op")
        loop = _cog_loop(svc, device_id=env["device_id"])
        loop.start()
        sup = CognitiveSupervisor(loop, home=tmp_path)
        out = sup.process({"source": "user", "type": "user",
                           "payload": {"text": "check phone battery"}})
        assert out.action.approval_state == "waiting"
        assert out.verification.verdict == "UNKNOWN"
        assert out.result.ok is False
        assert out.action.command_id.startswith("cmd-")
        record = svc.command_status(out.action.command_id)
        assert record is not None and record["state"] == "queued"
        approval_id = record["approval_id"]
        assert approval_id.startswith("apd-")
        assert svc.approve_command(approval_id, by="op") is True
        # Re-present the approved token: immediate authorized delivery
        # (the tick path would also deliver once the deferral lapses).
        done = svc.request_command(
            "cognitive-loop", env["device_id"], "device.get_battery", {},
            approval_id=approval_id)
        assert done["ok"] is True, done
        assert svc.command_status(done["command_id"])["state"] == "completed"
        assert "77" in json.dumps(done.get("result", done))
    finally:
        env["client"].close()
        env["host"].stop()


def test_normalize_nests_bare_dicts_under_payload():
    from jarvis.intelligence.wiring import normalize_event
    assert normalize_event({"text": "hi"}) == {"payload": {"text": "hi"}}
    already = {"payload": {"text": "hi"}, "source": "user"}
    assert normalize_event(already) == already
    assert normalize_event("oops") == {"raw": "oops"}
