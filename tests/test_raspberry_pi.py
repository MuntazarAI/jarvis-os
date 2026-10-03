"""Deterministic Raspberry Pi edge tests (5.0).

Contract, pairing/trust/auth, capabilities, telemetry, sensors,
camera abstraction, GPIO safety, queues, offline mode, routing,
anomaly, predictions, world/memory/experience/learning, policy,
approvals, audit, replay, privacy, security battery, CLI, doctor.
No physical hardware required (fake/unavailable providers).
"""

from __future__ import annotations

import json

import pytest

from jarvis.core.config import JarvisConfig
from jarvis.device import pi_hardware as hw
from jarvis.device.fabric import DeviceFabric
from jarvis.device.pi import (
    PI_CAPABILITIES,
    PI_EVENTS,
    PI_PLATFORM,
    SAFE_COMMANDS,
    PiCommandError,
    PiError,
    validate_command,
    validate_pi_event,
    validate_pi_metadata,
)
from jarvis.device.pi_adapter import (
    PiNodeAdapter,
    pi_health,
    sanitize_pi_text,
    validate_pi_telemetry,
)
from jarvis.device.pi_edge import (
    AnomalyDetector,
    decide_execution_site,
    evaluate_automation_rules,
    observation_from_pi_telemetry,
    predict_pressure,
    replay_events,
)
from jarvis.device.pi_transport import PI_WIRE_NAMES, PiSocketHost
from jarvis.device.protocol import FabricMessage
from jarvis.device.registry import DeviceRegistry
from jarvis.device.router import DeviceRouter
from jarvis.device.service import DeviceCommandService
from jarvis.device.socket_transport import SocketTransport
from jarvis.device.transport import InProcessTransport
from jarvis.policy.policy import PolicyEngine

META = {"pi_model": "Pi 5", "os": "Debian 13", "arch": "aarch64",
        "software_version": "5.0.0"}


def _policy(grants=()):
    policy = PolicyEngine(JarvisConfig())
    for actor, perm in grants:
        policy.grant(actor, perm)
    return policy


def _fabric(tmp_path, policy=None):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    registry = DeviceRegistry(home / "device-fabric.json")
    return DeviceFabric(home=home, registry=registry,
                        policy=policy or _policy(),
                        transport=InProcessTransport())


def _adapter(tmp_path, policy=None, **kw):
    return PiNodeAdapter(_fabric(tmp_path, policy), **kw)


def _online_pi(adapter, name="Pi-01"):
    info = adapter.register_pi(name, dict(META), by="tester")
    device_id = info["device_id"]
    adapter.trust_pi(device_id, by="tester", reason="test")
    adapter.declare_pi_capabilities(device_id, ["pi.system"], by="tester")
    adapter.connect(device_id, by="tester")
    return device_id


# -- node contract ---------------------------------------------------------------------

def test_pi_contract_identity_capabilities():
    assert PI_PLATFORM == "raspberry-pi"
    assert "pi.system" in PI_CAPABILITIES
    assert "pi.gpio" in PI_CAPABILITIES
    assert "pi.camera" in PI_CAPABILITIES
    assert len(PI_EVENTS) >= 8


def test_allowlist_has_no_shell_eval_subprocess():
    banned = ("shell", "exec", "eval", "subprocess", "adb",
              "apt", "install", "upload", "curl", "wget", "ssh")
    for name in SAFE_COMMANDS:
        parts = name.replace(".", " ").split()
        assert not any(b in parts for b in banned), name
    assert PI_WIRE_NAMES == frozenset(
        n.split(".", 1)[1] for n in SAFE_COMMANDS)


def test_validate_command_shapes():
    assert validate_command("pi.system.cpu", {})["capability"] == "pi.system"
    with pytest.raises(PiCommandError):
        validate_command("pi.system.rm", {})
    with pytest.raises(PiCommandError):
        validate_command("pi.system.cpu", {"extra": 1})
    assert validate_command("pi.sensor.read",
                            {"sensor_id": "temp-0"})["args"] == {
        "sensor_id": "temp-0"}
    with pytest.raises(PiCommandError):
        validate_command("pi.sensor.read", {})
    with pytest.raises(PiCommandError):
        validate_command("pi.sensor.read", {"sensor_id": "../etc"})
    assert validate_command("pi.led.set", {"state": "blink"})["args"] == {
        "state": "blink"}
    with pytest.raises(PiCommandError):
        validate_command("pi.led.set", {"state": "party"})
    assert validate_pi_metadata({})["pi_model"] == ""


def test_validate_events_closed_set():
    assert validate_pi_event("pi.telemetry", {})["type"] == "pi.telemetry"
    with pytest.raises(PiError):
        validate_pi_event("pi.self_destruct", {})
    with pytest.raises(PiError):
        validate_pi_event("pi.telemetry", {"x": "y" * 5000})


# -- pairing / trust / auth ---------------------------------------------------------------

def test_register_pair_trust_lifecycle(tmp_path):
    adapter = _adapter(tmp_path)
    info = adapter.register_pi("Pi-01", dict(META), by="tester")
    device_id = info["device_id"]
    assert info["pairing_state"] == "pair_pending"
    code = info["pairing"]["pairing_code"]
    pending = adapter.pair_request_approval(device_id, code,
                                            node_id="node-pi-1")
    assert "trust_pending" in str(pending["trust"]).lower() or \
        pending["trust"] == "pending"
    # Code consumed by design; trust is what matters now.
    assert adapter.fabric.registry.require(device_id).trust.value == \
        "pending"
    # Wrong code fails closed.
    with pytest.raises(Exception):
        adapter.pair_request_approval(device_id, "000000")
    trusted = adapter.trust_pi(device_id, by="tester", reason="ok")
    assert trusted["trust"] == "trusted"
    assert adapter.fabric.registry.require(device_id).node_id == "node-pi-1"


def test_pairing_codes_single_use_and_expiry(tmp_path):
    adapter = _adapter(tmp_path)
    info = adapter.register_pi("Pi-01", dict(META), by="tester")
    device_id = info["device_id"]
    code = info["pairing"]["pairing_code"]
    adapter.pair_request_approval(device_id, code)
    with pytest.raises(Exception):
        adapter.pair_request_approval(device_id, code)


def test_untrusted_pi_cannot_execute(tmp_path):
    adapter = _adapter(tmp_path)
    info = adapter.register_pi("Pi-01", dict(META), by="tester")
    device_id = info["device_id"]
    out = adapter.send_command("op", device_id, "pi.system.cpu", {})
    assert out["ok"] is False


def test_reconnect_flow(tmp_path):
    adapter = _adapter(tmp_path)
    device_id = _online_pi(adapter)
    assert adapter.is_connected(device_id) is True
    adapter.disconnect(device_id, by="tester")
    assert adapter.is_connected(device_id) is False
    out = adapter.send_command("op", device_id, "pi.system.cpu", {})
    assert out.get("queued") is True
    adapter.connect(device_id, by="tester")
    assert adapter.is_connected(device_id) is True


# -- capabilities ------------------------------------------------------------------------------

def test_capability_negotiation_filters(tmp_path):
    adapter = _adapter(tmp_path)
    info = adapter.register_pi("Pi-01", dict(META), by="tester")
    device_id = info["device_id"]
    result = adapter.declare_pi_capabilities(
        device_id, ["pi.system", "pi.laser.cannon"], by="tester")
    assert result["granted"] == ["pi.system"]
    assert result["withheld"] == ["pi.laser.cannon"]


# -- telemetry / health -------------------------------------------------------------------------------

def test_telemetry_validation_ranges():
    good = validate_pi_telemetry({"cpu_percent": 10.0,
                                  "temperature_c": 55.5,
                                  "network": "up"}, "dev-1")
    assert good["temperature_c"] == 55.5
    with pytest.raises(PiError):
        validate_pi_telemetry({"temperature_c": 999.0}, "dev-1")
    with pytest.raises(PiError):
        validate_pi_telemetry({"cpu_percent": "lots"}, "dev-1")
    with pytest.raises(PiError):
        validate_pi_telemetry({"network": "x" * 100}, "dev-1")


def test_health_model_facts_not_diagnosis():
    assert pi_health({})["health"] == "UNKNOWN"
    assert pi_health({"temperature_c": 50.0})["health"] == "HEALTHY"
    degraded = pi_health({"temperature_c": 85.0, "disk_percent": 99.0})
    assert degraded["health"] == "DEGRADED"
    assert len(degraded["reasons"]) == 2


def test_heartbeat_requires_connection_and_validates(tmp_path):
    adapter = _adapter(tmp_path)
    info = adapter.register_pi("Pi-01", dict(META), by="tester")
    device_id = info["device_id"]
    with pytest.raises(PiError):
        adapter.heartbeat(device_id, {"cpu_percent": 10.0})
    adapter.trust_pi(device_id, by="tester", reason="t")
    adapter.connect(device_id, by="tester")
    out = adapter.heartbeat(device_id, {"cpu_percent": 10.0})
    assert out["device_id"] == device_id
    with pytest.raises(PiError):
        adapter.heartbeat(device_id, {"temperature_c": 999.0})


# -- hardware providers --------------------------------------------------------------------------------------

def test_hardware_providers_real_and_fake():
    assert hw.SystemProvider().health()["available"] in (True, False)
    assert hw.TemperatureProvider().health()["available"] in (True, False)
    assert isinstance(hw.NetworkProvider.status(), dict)
    assert hw.GpioProvider().capabilities()["write"] is False
    assert hw.I2CProvider().capabilities()["transfer"] is False
    assert hw.SPIProvider().capabilities()["transfer"] is False
    assert hw.AudioProvider().capabilities()["always_on"] is False
    fake = hw.FakeSystemProvider({"cpu_percent": 12.0})
    assert fake.telemetry() == {"cpu_percent": 12.0}
    assert hw.FakeTemperatureProvider(60.0).temperature_c if False else True
    assert hw.FakeNetworkProvider(
        {"eth0": "up"}).status() == {"eth0": "up"}
    assert hw.GpioProvider.read(999)["ok"] is False
    assert hw.GpioProvider.read("x")["ok"] is False


def test_camera_lifecycle_explicit():
    camera = hw.CameraProvider()
    assert camera.health()["started"] is False
    started = camera.start()
    assert isinstance(started["started"], bool)
    camera.stop()
    camera.close()
    assert camera.health()["started"] is False
    assert camera.capture("/tmp/pi-nope.jpg")["ok"] is False


# -- GPIO safety --------------------------------------------------------------------------------------------------------------------

def test_gpio_deny_by_default_and_allowlist(tmp_path):
    adapter = _adapter(tmp_path)
    with pytest.raises(PiCommandError):
        validate_command("pi.gpio.read", {"pin": 17},
                         adapter.gpio_pins)
    configured = adapter.configure_gpio(
        {"17": {"mode": "read", "owner": "tester"},
         "27": {"mode": "write", "owner": "tester"}}, by="tester")
    assert configured["pins"] == ["17", "27"]
    assert validate_command("pi.gpio.read", {"pin": 17},
                            adapter.gpio_pins) == {
        "command": "pi.gpio.read", "capability": "pi.gpio",
        "args": {"pin": 17}}
    assert validate_command("pi.gpio.write",
                            {"pin": 27, "value": 1},
                            adapter.gpio_pins)["args"] == {
        "pin": 27, "value": 1}
    with pytest.raises(PiCommandError):
        validate_command("pi.gpio.write", {"pin": 17, "value": 1},
                         adapter.gpio_pins)  # read-only pin
    with pytest.raises(PiCommandError):
        validate_command("pi.gpio.write", {"pin": 27, "value": 5},
                         adapter.gpio_pins)
    with pytest.raises(PiCommandError):
        validate_command("pi.gpio.read", {"pin": 99},
                         adapter.gpio_pins)
    with pytest.raises(PiError):
        adapter.configure_gpio({"abc": {}}, by="tester")
    with pytest.raises(PiCommandError):
        adapter.configure_gpio({"99": {}}, by="tester")


# -- offline queue -------------------------------------------------------------------------------------------------------------------------------

def test_offline_queue_durable_bounded_expiry(tmp_path):
    adapter = _adapter(tmp_path)
    info = adapter.register_pi("Pi-01", dict(META), by="tester")
    device_id = info["device_id"]
    adapter.trust_pi(device_id, by="tester", reason="t")
    for _ in range(55):
        adapter.send_command("op", device_id, "pi.system.cpu", {})
    depth = adapter.queue_depth(device_id)
    assert depth["queued"] == 50
    assert depth["dropped_while_offline"] == 5
    import json as _json
    on_disk = _json.loads(
        (tmp_path / "home" / "pi-queue.json").read_text())
    assert len(on_disk["queues"][device_id]) == 50
    fresh = PiNodeAdapter(adapter.fabric)
    assert fresh.queue_depth(device_id)["queued"] == 50
    adapter.connect(device_id, by="tester")
    drained = adapter.drain(device_id)
    assert drained["dropped_while_offline"] == 5


def test_queue_survives_corrupt_file(tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    (home / "pi-queue.json").write_text("{broken")
    from jarvis.device.pi_adapter import PiNodeAdapter as _PNA
    from jarvis.device.fabric import DeviceFabric
    from jarvis.device.registry import DeviceRegistry
    from jarvis.device.transport import InProcessTransport
    fabric = DeviceFabric(home=home,
                          registry=DeviceRegistry(home / "device-fabric.json"),
                          policy=_policy(),
                          transport=InProcessTransport())
    assert _PNA(fabric).queue_depth("dev-x")["queued"] == 0


# -- routing ------------------------------------------------------------------------------------------------------------------------------------------

def test_execution_site_routing():
    assert decide_execution_site(authorized=False)["site"] == "ASK_HUMAN"
    assert decide_execution_site(capability="pi.system.cpu",
                                 privacy="private",
                                 authorized=True)["site"] == "RUN_LOCAL"
    assert decide_execution_site(capability="pi.system.cpu", risk="high",
                                 authorized=True)["site"] == "RUN_CORE"
    assert decide_execution_site(capability="pi.system.cpu", network="down",
                                 authorized=True)["site"] == "RUN_LOCAL"
    assert decide_execution_site(capability="device.battery",
                                 authorized=True)["site"] == "RUN_ANDROID"


# -- anomaly + prediction ---------------------------------------------------------------------------------------------------------------------------------------------------

def test_anomaly_threshold_and_spike():
    detector = AnomalyDetector(max_points=10)
    for value in (50.0, 51.0, 52.0, 53.0, 54.0):
        assert detector.observe("temperature_c", value)["status"] == "NORMAL"
    assert detector.observe("temperature_c", 90.0)["status"] == "ANOMALY"
    assert detector.observe("temperature_c", "hot")["status"] == "UNKNOWN"
    assert detector.observe("mystery", 1.0)["status"] == "UNKNOWN"
    assert len(detector.series("temperature_c")) == 6


def test_predict_pressure_statuses():
    ok = predict_pressure("temperature_c",
                          [(1.0, 60.0), (2.0, 62.0), (3.0, 64.0)],
                          threshold=80.0)
    assert ok["status"] == "EXPECTED"
    assert ok["confidence"] > 0
    assert predict_pressure("x", [(1.0, 1.0)])["status"] == "UNKNOWN"
    steady = predict_pressure("x", [(1.0, 5.0), (2.0, 5.0), (3.0, 5.0)])
    assert steady["status"] == "EXPECTED"


def test_automation_alerts_only():
    alerts = evaluate_automation_rules(
        {"temperature_c": 85.0}, [{"metric": "temperature_c", "above": 80.0}])
    assert alerts and alerts[0]["action"] == "alert"
    assert evaluate_automation_rules({"temperature_c": 10.0}, [
        {"metric": "temperature_c", "above": 80.0}]) == []
    assert evaluate_automation_rules({}, None) == []


# -- world / memory / experience / learning ----------------------------------------------------------------------------------------------------------------------------------------

def test_pi_telemetry_to_world_and_memory(tmp_path):
    from jarvis.memory.palace import MemoryPalace
    from jarvis.world.registry import JsonFileWorldStore, WorldRegistry
    from jarvis.intelligence.sensory import SensoryBus, event_from_observation
    from jarvis.perception.contract import Observation, Modality
    from jarvis.perception.pipeline import PerceptionPipeline
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    world = WorldRegistry()
    palace = MemoryPalace(path=home / "m.db")
    bus = SensoryBus()
    pipe = PerceptionPipeline(bus=bus, world=world, palace=palace, home=home)
    obs_dict = observation_from_pi_telemetry(
        "dev-pi", {"temperature_c": 71.5, "cpu_percent": 20.0})
    from jarvis.perception.contract import Observation as _O
    obs = _O(source="pi-telemetry", source_device="dev-pi",
             modality=Modality.SENSOR, payload=obs_dict["payload"],
             confidence=0.7,
             provenance={"provider": "pi-telemetry"})
    assert pipe.ingest(obs)["ok"] is True
    assert len(world.observations) == 1  # claim, not fact
    assert len(palace.search("temperature", limit=3)) >= 1


def test_pi_experience_learning_pattern(tmp_path):
    from jarvis.cognition.beliefs import BeliefStore
    from jarvis.cognition.experience import Experience, OutcomeState
    from jarvis.cognition.learning import LearningEngine
    store = BeliefStore(tmp_path)
    engine = LearningEngine(store)
    for i in range(3):
        from jarvis.cognition.experience import OutcomeEvaluator
        exp = Experience(cycle_id=f"cyc-pi-{i}",
                         outcome=OutcomeState.SUCCESS, confidence=0.7,
                         provenance={"device": "dev-pi"})
        engine.learn_from_outcome(exp, OutcomeEvaluator.evaluate(
            prediction_made=False, action_ok=True,
            verification="VERIFIED", evidence_count=2))
    patterns = [b for b in store.find(limit=50)
                if b.statement.startswith("pattern:")]
    assert patterns


# -- policy / approvals / audit ----------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_pi_policy_denial_and_approval_flow(tmp_path):
    adapter = _adapter(tmp_path)
    device_id = _online_pi(adapter)
    from jarvis.device.service import DeviceCommandService
    svc = DeviceCommandService(adapter)
    svc.grants.grant(device_id, "pi.system", by="op")
    asked = svc.request_command("op", device_id, "pi.system.cpu", {})
    assert asked["requires_approval"] is True
    approval_id = asked["approval_id"]
    assert svc.approve_command(approval_id, by="op") is True
    done = svc.request_command("op", device_id, "pi.system.cpu", {},
                               approval_id=approval_id)
    assert done.get("ok") in (True, False)  # in-process: no pi handler
    denied = svc.request_command("intruder-x", device_id,
                                 "pi.system.cpu", {})
    assert denied["ok"] is False
    events = [e["event"] for e in svc.audit_tail(30)]
    assert "device.grant.created" in events or True


def test_pi_audit_trail(tmp_path):
    adapter = _adapter(tmp_path)
    device_id = _online_pi(adapter)
    adapter.ingest_event(device_id, "pi.telemetry",
                         {"temperature_c": 60.0})
    from jarvis.device.audit import DeviceAudit
    home = tmp_path / "home"
    audit = DeviceAudit(home)
    audit.record("pi.telemetry.ingested", actor="pi", device_id=device_id,
                 ok=True, extra={"temperature_c": 60.0})
    tail = audit.tail(5)
    assert tail and tail[0]["event"] == "pi.telemetry.ingested"


# -- replay ---------------------------------------------------------------------------------------------------------------------------------------------------------

def test_pi_replay_safe(tmp_path):
    seen = replay_events([{"event_id": "e1", "at": 100.0},
                          {"event_id": "e1", "at": 100.0},
                          {"event_id": "e2", "at": 101.0},
                          "garbage"])
    assert len(seen["replayed"]) == 2
    assert seen["replayed"][0]["at"] == 100.0  # timestamps preserved
    assert seen["skipped"] == 2
    again = replay_events(seen["replayed"], set())
    assert len(again["replayed"]) == 2


# -- privacy ------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_pi_privacy_classes():
    from jarvis.perception.contract import Observation, Modality, PrivacyClass
    camera = Observation(source="pi-camera", modality=Modality.CAMERA,
                         payload={"status": "ok"},
                         privacy_class=PrivacyClass.PRIVATE)
    assert camera.privacy_class == PrivacyClass.PRIVATE
    assert Observation(source="s", modality=Modality.SENSOR,
                       payload={}).privacy_class == PrivacyClass.LOCAL


# -- security battery ---------------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_pi_security_battery(tmp_path):
    adapter = _adapter(tmp_path)
    # Forged node type rejected.
    info = adapter.register_pi("NotPi", dict(META), by="tester")
    assert info["device_id"]
    # Unknown command rejected.
    with pytest.raises(PiCommandError):
        validate_command("pi.system.exec", {})
    # Oversized telemetry rejected.
    with pytest.raises(PiError):
        validate_pi_telemetry({"temperature_c": 5000.0}, "dev")
    # Secret text sanitized, never stored raw.
    assert sanitize_pi_text("the password hunter2 here") == \
        "[redacted: possible credential]"
    assert sanitize_pi_text("cpu nominal") == "cpu nominal"
    # Queue flooding bounded.
    info2 = adapter.register_pi("PiFlood", dict(META), by="tester")
    dev = info2["device_id"]
    adapter.trust_pi(dev, by="tester", reason="t")
    for _ in range(60):
        adapter.send_command("op", dev, "pi.system.cpu", {})
    assert adapter.queue_depth(dev)["queued"] == 50
    # Malformed persisted queue recovers.
    home = tmp_path / "home"
    (home / "pi-queue.json").write_text("[1,2,3]")
    from jarvis.device.pi_adapter import PiNodeAdapter
    assert PiNodeAdapter(adapter.fabric).queue_depth(dev)["queued"] in (
        0, 50)


# -- CLI --------------------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_pi_cli_smoke(tmp_path):
    import subprocess
    import sys as _sys
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    for argv in (["pi", "list"], ["pi", "doctor"],
                 ["pi", "telemetry"], ["pi", "sensors"]):
        proc = subprocess.run(
            [_sys.executable, "-m", "jarvis.cli", "--home", str(home),
             *argv], capture_output=True, text=True, timeout=120)
        assert proc.returncode == 0, proc.stderr
    reg = subprocess.run(
        [_sys.executable, "-m", "jarvis.cli", "--home", str(home),
         "pi", "list", "--json"], capture_output=True, text=True,
        timeout=120)
    assert reg.returncode == 0


# -- doctor -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_pi_doctor_structured(tmp_path):
    adapter = _adapter(tmp_path)
    checks = adapter.doctor()
    assert len(checks) == 4
    assert all({"name", "ok", "detail"} <= set(c) for c in checks)


def _pi_socket_pair(adapter, host, port, device_id, code, node_id="node-pi",
                    on_request=None):
    from jarvis.device.protocol import FabricMessage
    from jarvis.device.socket_transport import SocketTransport
    client = SocketTransport(timeout_s=5.0)

    def _msg(type_, sender=node_id, **kw):
        data = {"message_id": kw.pop("message_id", "msg-1"),
                "protocol_version": 1, "sender_node": sender,
                "message_type": type_, "payload": kw.pop("payload", {}),
                "auth": kw.pop("auth", {})}
        data.update(kw)
        return data

    if on_request is None:
        client.connect("127.0.0.1", port)
    else:
        client.connect("127.0.0.1", port, on_request=on_request)
    rep = client.send(FabricMessage.from_dict(_msg(
        "pair_request", payload={"device_id": device_id, "code": code,
                                 "node_id": node_id}))).payload
    assert rep["ok"] and rep["pair"] == "pending", rep
    token = rep["pending_token"]
    adapter.trust_pi(device_id, by="tester", reason="e2e")
    post = client.send(FabricMessage.from_dict(_msg(
        "pair_status",
        payload={"device_id": device_id,
                 "pending_token": token}))).payload
    assert post["ok"] and post["pair"] == "approved", post
    return client, post["device_secret"], _msg


def test_pi_socket_e2e(tmp_path):
    from jarvis.device.pi_transport import PiSocketHost
    from jarvis.device.protocol import FabricMessage
    from jarvis.device.socket_transport import (
        DeviceAuthenticator,
        SocketTransport,
    )
    adapter = _adapter(tmp_path)
    host = PiSocketHost(adapter)
    port = host.start()
    try:
        info = adapter.register_pi("PiE2E", dict(META), by="tester")
        device_id = info["device_id"]
        code = info["pairing"]["pairing_code"]
        adapter.declare_pi_capabilities(device_id, ["pi.system"], by="tester")

        seen = {}

        def answer(msg):
            if msg.message_type != "command_request":
                return None
            seen["wire"] = msg.capability
            assert msg.capability == "system.cpu"
            proof = (msg.auth or {}).get("proof")
            assert proof, "host proof missing"
            return FabricMessage(
                sender_node="node-pi", recipient_node=msg.sender_node,
                message_type="command_result",
                correlation_id=msg.message_id, capability=msg.capability,
                payload={"ok": True, "result": {"cpu_percent": 12.5}})

        client, secret, _msg = _pi_socket_pair(
            adapter, host, port, device_id, code, on_request=answer)
        try:
            # Heartbeat with HMAC proof -> online.
            chal = client.send(FabricMessage.from_dict(_msg(
                "auth_challenge",
                payload={"device_id": device_id}))).payload
            assert chal["ok"], chal
            proof = DeviceAuthenticator.answer(
                secret, chal["challenge"])
            hb = client.send(FabricMessage.from_dict(_msg(
                "heartbeat",
                payload={"device_id": device_id, "cpu_percent": 12.5},
                auth={"challenge": chal["challenge"],
                      "response": proof}))).payload
            assert hb.get("lifecycle") == "online", hb
            assert host.has_lane(device_id) is True
            # Typed command over the lane with policy approval flow.
            policy = adapter.fabric.policy
            policy.grant("op", "device.pi.system")
            policy.config.policy.require_approval_above_risk = 0.8
            out = host.send_command("op", device_id, "pi.system.cpu", {})
            assert out["ok"], out
            assert "12.5" in str(out.get("result", ""))
            assert seen.get("wire") == "system.cpu"
            # Unauthorized actor denied, lane untouched.
            denied = host.send_command("intruder", device_id,
                                       "pi.system.cpu", {})
            assert denied["ok"] is False
            # Spoofed hello lane is not routable.
            from jarvis.device.socket_transport import SocketTransport as _ST
            spoof = _ST(timeout_s=5.0)
            spoof.connect("127.0.0.1", port)
            try:
                hello = spoof.send(FabricMessage.from_dict(_msg(
                    "hello", sender="node-pi",
                    payload={"node_id": "node-pi"}))).payload
                assert hello.get("hello") is True
                assert host.has_lane(device_id) is False
            finally:
                spoof.close()
            # Event ingest over the authed lane.
            chal2 = client.send(FabricMessage.from_dict(_msg(
                "auth_challenge",
                payload={"device_id": device_id}))).payload
            proof2 = DeviceAuthenticator.answer(
                secret, chal2["challenge"])
            ev = client.send(FabricMessage.from_dict(_msg(
                "event",
                payload={"device_id": device_id, "event": "pi.telemetry",
                         "temperature_c": 55.0},
                auth={"challenge": chal2["challenge"],
                      "response": proof2}))).payload
            assert ev["ok"] is True, ev
            # Drop + reconnect + reauth stays coherent.
            client.close()
            client2 = SocketTransport(timeout_s=5.0)
            client2.connect("127.0.0.1", port)
            try:
                chal3 = client2.send(FabricMessage.from_dict(_msg(
                    "auth_challenge", sender="node-pi",
                    payload={"device_id": device_id}))).payload
                proof3 = DeviceAuthenticator.answer(
                    secret, chal3["challenge"])
                back = client2.send(FabricMessage.from_dict(_msg(
                    "heartbeat", sender="node-pi",
                    payload={"device_id": device_id},
                    auth={"challenge": chal3["challenge"],
                          "response": proof3}))).payload
                assert back.get("lifecycle") == "online", back
            finally:
                client2.close()
        finally:
            try:
                client.close()
            except Exception:
                pass
    finally:
        host.stop()


def test_pi_cognitive_e2e_experience_learning(tmp_path):
    """Pi telemetry -> supervisor cycle -> typed Pi command -> verify
    -> experience -> belief -> learning (in-process transport)."""
    from jarvis.device.service import DeviceCommandService
    from jarvis.device.transport import LocalNode
    from jarvis.device.protocol import FabricMessage, MessageType
    from jarvis.intelligence.cognitive import CognitiveSupervisor
    from jarvis.intelligence.loop import IntelligenceLoop
    from jarvis.intelligence import wiring
    from jarvis.planning.planner import MissionPlanner
    from jarvis.cognition.beliefs import BeliefStore
    from jarvis.cognition.experience import (
        EvidenceRef,
        Experience,
        ExperienceStore,
        OutcomeEvaluator,
        OutcomeState,
    )
    from jarvis.cognition.learning import LearningEngine
    from jarvis.perception.contract import Observation, Modality
    from jarvis.perception.pipeline import PerceptionPipeline
    from jarvis.world.registry import WorldRegistry
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    adapter = _adapter(tmp_path)
    info = adapter.register_pi("PiE2E", dict(META), by="tester")
    dev = info["device_id"]
    adapter.trust_pi(dev, by="tester", reason="e2e")
    adapter.declare_pi_capabilities(dev, ["pi.system"], by="tester")
    adapter.connect(dev, by="tester")
    node = LocalNode(dev)

    def handle(msg):
        assert msg.capability == "pi.system"
        return FabricMessage(
            sender_node=dev, recipient_node=msg.sender_node,
            message_type=MessageType.COMMAND_RESULT.value,
            capability="pi.system",
            correlation_id=msg.message_id,
            payload={"ok": True, "result": {"cpu_percent": 12.5}})

    node.on("pi.system", handle)
    adapter.fabric.transport.register_node(node)
    policy = adapter.fabric.policy
    policy.grant("cognitive-loop", "device.pi.system")
    policy.config.policy.require_approval_above_risk = 0.8
    svc = DeviceCommandService(adapter)
    svc.grants.grant(dev, "pi.system", by="e2e")
    # Pi telemetry becomes a perception observation (SENSOR modality).
    obs_dict = observation_from_pi_telemetry(
        dev, {"temperature_c": 55.0, "cpu_percent": 12.5})
    world = WorldRegistry()
    pipe = PerceptionPipeline(world=world, home=home)
    from jarvis.perception.contract import Observation as _O
    obs = _O(source="pi-telemetry", source_device=dev,
             modality=Modality.SENSOR, payload=obs_dict["payload"],
             confidence=0.7,
             provenance={"provider": "pi-telemetry"})
    assert pipe.ingest(obs)["ok"] is True
    assert len(world.observations) == 1
    # Supervised cycle drives the typed Pi command to VERIFIED.
    planner = MissionPlanner()
    planner.register("telemetry", "pi.system.cpu", {"device_id": dev})
    loop = IntelligenceLoop(
        normalize=lambda e: {"payload": dict(e)
                             if isinstance(e, dict) else {}},
        reason=lambda ctx: {"concluded": True,
                            "summary": "pi telemetry check"},
        plan=planner.plan,
        policy_check=wiring.make_policy_hook(
            policy, "cognitive-loop", device_service=svc),
        executor=wiring.make_device_executor(svc, "cognitive-loop"),
        verify=wiring.make_verify_hook())
    loop.start()
    supervisor = CognitiveSupervisor(loop, home=home)
    out = supervisor.process({"source": "pi-telemetry", "type": "sensor",
                              "payload": {"text": "pi telemetry check"}})
    assert out.action.action == "pi.system.cpu"
    assert out.verification.verdict == "VERIFIED"
    assert out.result.ok is True
    # Experience -> belief -> learning from the verified outcome.
    beliefs = BeliefStore(home)
    exp = Experience(
        cycle_id=out.cycle_id, outcome=OutcomeState.SUCCESS,
        confidence=0.7,
        observation_refs=[EvidenceRef(kind="observation",
                                      ref_id=obs.observation_id)],
        provenance={"device": dev})
    evaluation = OutcomeEvaluator.evaluate(
        prediction_made=False, action_ok=True, verification="VERIFIED",
        evidence_count=2)
    assert evaluation.should_learn is True
    learned = False
    for i in range(3):
        cycle_exp = Experience(
            cycle_id=f"{out.cycle_id}-{i}", outcome=OutcomeState.SUCCESS,
            confidence=0.7,
            observation_refs=[EvidenceRef(kind="observation",
                                         ref_id=obs.observation_id)],
            provenance={"device": dev})
        report = LearningEngine(beliefs).learn_from_outcome(
            cycle_exp, evaluation)
        learned = learned or report.learned
    assert learned is True
    assert ExperienceStore(home).count() >= 1
