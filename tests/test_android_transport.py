"""Real Android socket-transport tests (3.10).

Deterministic: loopback TCP only (127.0.0.1, ephemeral ports), short
timeouts, no phone/emulator/network. Covers framing, strict server
behavior, HMAC auth + rotation, socket pairing (no auto-trust),
heartbeat/events, host-initiated command E2E (bare wire + host proof),
offline queue, rendezvous file, router/policy boundaries, and the
command allowlist.
"""

import json
import socket

import pytest

from jarvis.device.android import (
    ANDROID_EVENTS,
    COMMAND_TTL_S,
    QueuedCommand,
    SAFE_COMMANDS,
    AndroidCommandError,
    AndroidNodeAdapter,
    PairingError,
    PairingManager,
    validate_command,
)
from jarvis.device.android_transport import (
    ANDROID_WIRE_NAMES,
    AndroidSocketHost,
    read_host_status,
)
from jarvis.device.identity import IdentityError, require_verified_transport
from jarvis.device.protocol import FabricMessage, MessageType
from jarvis.device.registry import DeviceRegistry
from jarvis.device.fabric import DeviceFabric
from jarvis.device.socket_transport import (
    AuthError,
    DeviceAuthenticator,
    FabricServer,
    FramingError,
    SocketTransport,
    decode_frames,
    encode_frame,
)
from jarvis.device.telemetry import Telemetry, TelemetryError
from jarvis.device.transport import InProcessTransport
from jarvis.policy.policy import PolicyEngine

META = {"device_model": "TestPhone", "android_version": "15",
        "app_version": "3.10.0"}
TIMEOUT = 5.0


def _policy(grants=()):
    from jarvis.core.config import JarvisConfig
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


def _adapter(tmp_path, policy=None):
    return AndroidNodeAdapter(_fabric(tmp_path, policy))


def _host(adapter, **kw):
    host = AndroidSocketHost(adapter, **kw)
    port = host.start()
    return host, port


def _raw_request(port, items, timeout=TIMEOUT):
    """Send raw frames/pieces, collect reply dicts. items: bytes or dict."""
    sock = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    sock.settimeout(timeout)
    try:
        for item in items:
            sock.sendall(encode_frame(item) if isinstance(item, dict) else item)
        buf = bytearray()
        replies = []
        try:
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                buf += chunk
                for frame in decode_frames(buf):
                    replies.append(frame)
                if replies:
                    break
        except socket.timeout:
            pass
        return replies
    finally:
        sock.close()


def _msg(type_, sender="node-x", **kw):
    data = {"message_id": kw.pop("message_id", "msg-1"),
            "protocol_version": 1, "sender_node": sender,
            "message_type": type_, "payload": kw.pop("payload", {}),
            "auth": kw.pop("auth", {})}
    data.update(kw)
    return data


def _register(adapter, name="Pixel"):
    info = adapter.register_android(name, dict(META), by="tester")
    return info["device_id"], info["pairing"]["pairing_code"]


def _socket_pair(adapter, host, port, device_id, code, node_id="node-t",
                 on_request=None):
    """Full socket pairing up to approved secret. Returns (client, secret)."""
    client = SocketTransport(timeout_s=TIMEOUT)
    if on_request is None:
        client.connect("127.0.0.1", port)
    else:
        client.connect("127.0.0.1", port, on_request=on_request)
    req = _msg("pair_request", sender=node_id,
               payload={"device_id": device_id, "code": code,
                        "node_id": node_id})
    rep = client.send(FabricMessage.from_dict(req)).payload
    assert rep["ok"] and rep["pair"] == "pending", rep
    token = rep["pending_token"]
    # No auto-trust: still pending before human approval.
    pre = client.send(FabricMessage.from_dict(_msg(
        "pair_status", sender=node_id,
        payload={"device_id": device_id, "pending_token": token}))).payload
    assert pre["ok"] is False and pre["pair"] == "pending", pre
    adapter.trust_android(device_id, by="tester", reason="test approval")
    post = client.send(FabricMessage.from_dict(_msg(
        "pair_status", sender=node_id,
        payload={"device_id": device_id, "pending_token": token}))).payload
    assert post["ok"] and post["pair"] == "approved", post
    return client, post["device_secret"]


def _auth_headers(client, node_id, device_id, secret):
    chal = client.send(FabricMessage.from_dict(_msg(
        "auth_challenge", sender=node_id,
        payload={"device_id": device_id}))).payload
    assert chal["ok"], chal
    return {"challenge": chal["challenge"],
            "response": DeviceAuthenticator.answer(secret, chal["challenge"])}


# -- framing ---------------------------------------------------------------

def test_frame_roundtrip():
    item = {"a": [1, 2], "b": "héllo"}
    assert decode_frames(bytearray(encode_frame(item))) == [item]


def test_frame_multi_and_fragmented_over_loopback():
    def echo(msg, peer):
        return FabricMessage(
            sender_node="core", recipient_node=msg.sender_node,
            message_type="event", correlation_id=msg.message_id,
            payload={"ok": True, "n": msg.payload.get("n")})

    server = FabricServer(echo, port=0)
    port = server.start()
    try:
        sock = socket.create_connection(("127.0.0.1", port), timeout=TIMEOUT)
        sock.settimeout(TIMEOUT)
        try:
            frames = b"".join(
                encode_frame(_msg("event", payload={"n": i},
                                  message_id=f"msg-{i}"))
                for i in range(3))
            # Fragmented delivery: header first, then body in two pieces.
            sock.sendall(frames[:2])
            sock.sendall(frames[2:10])
            sock.sendall(frames[10:])
            buf = bytearray()
            got = []
            while len(got) < 3:
                chunk = sock.recv(65536)
                assert chunk, "server closed early"
                buf += chunk
                got.extend(decode_frames(buf))
            assert [g["payload"]["n"] for g in got] == [0, 1, 2]
            assert all(g["correlation_id"] == f"msg-{g['payload']['n']}"
                       for g in got)
        finally:
            sock.close()
    finally:
        server.stop()


def test_frame_oversize_encode_rejected():
    with pytest.raises(FramingError):
        encode_frame({"blob": "x" * (256 * 1024 + 1)})


def test_frame_oversize_wire_rejected_and_counted():
    server = FabricServer(lambda m, p: None, port=0)
    port = server.start()
    try:
        big = b"\x00\x10\x00\x00" + b"y" * 64  # claims 1MiB, sends little
        replies = _raw_request(port, [big])
        assert replies == []  # connection dropped, no reply
        assert server.rejected >= 1
        assert server.status()["listening"]
    finally:
        server.stop()


def test_frame_garbage_does_not_kill_server():
    def echo(msg, peer):
        return FabricMessage(
            sender_node="core", recipient_node=msg.sender_node,
            message_type="event", correlation_id=msg.message_id,
            payload={"ok": True})

    server = FabricServer(echo, port=0)
    port = server.start()
    try:
        _raw_request(port, [b"\xff\xfe\x00garbage!!!"])
        assert server.rejected >= 1
        # Server still serves the next connection.
        ok = _raw_request(port, [_msg("event", payload={"n": 1})])
        assert ok and ok[0]["message_type"] == "event"
    finally:
        server.stop()


# -- strict server behavior --------------------------------------------------

def test_server_unknown_type_gets_error_reply():
    server = FabricServer(lambda m, p: None, port=0)
    port = server.start()
    try:
        replies = _raw_request(port, [_msg("teleport")])
        assert len(replies) == 1
        assert replies[0]["message_type"] == "error"
        assert "rejected" in replies[0]["payload"]["error"]
    finally:
        server.stop()


def test_server_bad_version_gets_error_reply():
    server = FabricServer(lambda m, p: None, port=0)
    port = server.start()
    try:
        bad = _msg("event")
        bad["protocol_version"] = 999
        replies = _raw_request(port, [bad])
        assert len(replies) == 1
        assert replies[0]["message_type"] == "error"
    finally:
        server.stop()


def test_truncated_close_is_transport_error():
    from jarvis.device.transport import TransportError
    server = FabricServer(lambda m, p: None, port=0)
    port = server.start()
    client = SocketTransport(timeout_s=2.0)
    try:
        client.connect("127.0.0.1", port)
        sock = socket.create_connection(("127.0.0.1", port), timeout=TIMEOUT)
        sock.sendall(encode_frame(_msg("event"))[:3])  # partial header
        sock.close()
        with pytest.raises(TransportError):
            client.send(FabricMessage.from_dict(_msg("event")))
    finally:
        client.close()
        server.stop()


# -- authentication ----------------------------------------------------------

def test_challenge_response_success(tmp_path):
    auth = DeviceAuthenticator(tmp_path / "keys.json")
    secret = auth.issue("dev-1")
    challenge = auth.begin_challenge("dev-1")
    assert auth.verify("dev-1", challenge,
                       DeviceAuthenticator.answer(secret, challenge))


def test_challenge_wrong_secret_rejected(tmp_path):
    auth = DeviceAuthenticator(tmp_path / "keys.json")
    auth.issue("dev-1")
    challenge = auth.begin_challenge("dev-1")
    assert not auth.verify("dev-1", challenge, "0" * 64)


def test_challenge_single_use_rejects_replay(tmp_path):
    auth = DeviceAuthenticator(tmp_path / "keys.json")
    secret = auth.issue("dev-1")
    challenge = auth.begin_challenge("dev-1")
    good = DeviceAuthenticator.answer(secret, challenge)
    assert auth.verify("dev-1", challenge, good)
    assert not auth.verify("dev-1", challenge, good)


def test_challenge_rotation_chain(tmp_path):
    auth = DeviceAuthenticator(tmp_path / "keys.json")
    secret = auth.issue("dev-1")
    first = auth.outstanding("dev-1")
    rotated = auth.verify_and_rotate(
        "dev-1", first, DeviceAuthenticator.answer(secret, first))
    assert rotated and rotated != first
    assert auth.verify("dev-1", rotated,
                       DeviceAuthenticator.answer(secret, rotated))


def test_challenge_unknown_device(tmp_path):
    auth = DeviceAuthenticator(tmp_path / "keys.json")
    with pytest.raises(AuthError):
        auth.begin_challenge("ghost")
    assert not auth.verify("ghost", "c", "r")


def test_verified_transport_gate():
    with pytest.raises(IdentityError):
        require_verified_transport("in-process", action="trust test")
    require_verified_transport("socket", action="trust test")


# -- pairing over the socket ---------------------------------------------------

def test_pair_new_peer_starts_trust_pending(tmp_path):
    adapter = _adapter(tmp_path)
    host, port = _host(adapter)
    try:
        device_id, code = _register(adapter)
        client = SocketTransport(timeout_s=TIMEOUT)
        client.connect("127.0.0.1", port)
        try:
            rep = client.send(FabricMessage.from_dict(_msg(
                "pair_request", payload={"device_id": device_id,
                                          "code": code,
                                          "node_id": "node-t"}))).payload
            assert rep["ok"] and rep["pair"] == "pending"
            assert rep["trust"] == "pending"
            dev = adapter.fabric.registry.require(device_id)
            assert dev.trust.value == "pending"
            assert dev.lifecycle.value == "trust_pending"
        finally:
            client.close()
    finally:
        host.stop()


def test_pair_wrong_code_rejected(tmp_path):
    adapter = _adapter(tmp_path)
    host, port = _host(adapter)
    try:
        device_id, _ = _register(adapter)
        replies = _raw_request(port, [_msg(
            "pair_request", payload={"device_id": device_id,
                                      "code": "000000",
                                      "node_id": "node-t"})])
        assert len(replies) == 1
        assert replies[0]["payload"]["ok"] is False
        dev = adapter.fabric.registry.require(device_id)
        assert dev.trust.value == "pending"  # still untrusted
    finally:
        host.stop()


def test_pair_status_pending_then_approved_secret_once(tmp_path):
    adapter = _adapter(tmp_path)
    host, port = _host(adapter)
    try:
        device_id, code = _register(adapter)
        client, secret = _socket_pair(adapter, host, port, device_id, code)
        try:
            assert secret
            # Token reuse is rejected.
            again = client.send(FabricMessage.from_dict(_msg(
                "pair_status",
                payload={"device_id": device_id,
                         "pending_token": "reused"}))).payload
            assert again["ok"] is False
        finally:
            client.close()
    finally:
        host.stop()


def test_pairing_code_single_use_manager_level(tmp_path):
    pm = PairingManager(path=str(tmp_path / "pairings.json"))
    started = pm.begin("dev-1")
    pm.confirm("dev-1", started["pairing_code"])
    with pytest.raises(PairingError):
        pm.confirm("dev-1", started["pairing_code"])


def test_pairing_code_expiry_manager_level(tmp_path):
    pm = PairingManager(ttl_s=0, path=str(tmp_path / "pairings.json"))
    started = pm.begin("dev-1")
    with pytest.raises(PairingError):
        pm.confirm("dev-1", started["pairing_code"])


def test_confirm_sees_codes_issued_by_another_process(tmp_path):
    """Cross-process pairing: a long-running host's manager starts empty;
    a short-lived CLI process issues the code afterwards. confirm() must
    reload from disk and succeed (single-use consumption included)."""
    path = str(tmp_path / "pairings.json")
    host_manager = PairingManager(path=path)  # serve starts, empty
    cli_manager = PairingManager(path=path)   # later CLI register process
    issued = cli_manager.begin("dev-x", by="user")
    assert "dev-x" not in host_manager._pending  # stale view, as in prod
    host_manager.confirm("dev-x", issued["pairing_code"])
    assert "dev-x" not in host_manager._pending  # consumed, single-use
    import json as _json
    on_disk = _json.loads(open(path, encoding="utf-8").read())["pending"]
    assert "dev-x" not in on_disk  # consumption persisted for others


def test_pair_request_sees_devices_registered_by_another_process(tmp_path):
    """Cross-process register: a long-running host's adapter starts with
    an empty registry view; a later CLI process registers the device.
    pair_request_approval must reload from disk and reach code
    verification (not fail with 'unknown device')."""
    host = _adapter(tmp_path)  # serve starts, empty view
    cli = _adapter(tmp_path)   # later CLI register process
    device_id, code = _register(cli, name="XProc")
    assert device_id not in host.fabric.registry.devices  # stale, as in prod
    out = host.pair_request_approval(device_id, code, node_id="node-x")
    assert out["trust"] != "trusted"  # verified, still pending approval
    assert host.fabric.registry.require(device_id).node_id == "node-x"


# -- heartbeat / events ----------------------------------------------------------

def test_heartbeat_authed_goes_online(tmp_path):
    adapter = _adapter(tmp_path)
    host, port = _host(adapter)
    try:
        device_id, code = _register(adapter)
        client, secret = _socket_pair(adapter, host, port, device_id, code)
        try:
            headers = _auth_headers(client, "node-t", device_id, secret)
            rep = client.send(FabricMessage.from_dict(_msg(
                "heartbeat", sender="node-t",
                payload={"device_id": device_id, "battery_pct": 72.0},
                auth=headers))).payload
            assert rep["ok"] and rep["lifecycle"] == "online", rep
            assert "next_challenge" in rep
        finally:
            client.close()
    finally:
        host.stop()


def test_heartbeat_replay_rejected(tmp_path):
    adapter = _adapter(tmp_path)
    host, port = _host(adapter)
    try:
        device_id, code = _register(adapter)
        client, secret = _socket_pair(adapter, host, port, device_id, code)
        try:
            headers = _auth_headers(client, "node-t", device_id, secret)
            first = client.send(FabricMessage.from_dict(_msg(
                "heartbeat", sender="node-t",
                payload={"device_id": device_id}, auth=headers))).payload
            assert first["ok"]
            replay = client.send(FabricMessage.from_dict(_msg(
                "heartbeat", sender="node-t",
                payload={"device_id": device_id}, auth=headers))).payload
            assert replay["ok"] is False
        finally:
            client.close()
    finally:
        host.stop()


def test_heartbeat_unauthenticated_rejected(tmp_path):
    adapter = _adapter(tmp_path)
    host, port = _host(adapter)
    try:
        device_id, _ = _register(adapter)
        replies = _raw_request(port, [_msg(
            "heartbeat", payload={"device_id": device_id})])
        assert len(replies) == 1
        assert replies[0]["payload"]["ok"] is False
    finally:
        host.stop()


def _online_authed(tmp_path):
    adapter = _adapter(tmp_path)
    host, port = _host(adapter)
    device_id, code = _register(adapter)
    client, secret = _socket_pair(adapter, host, port, device_id, code)
    headers = _auth_headers(client, "node-t", device_id, secret)
    rep = client.send(FabricMessage.from_dict(_msg(
        "heartbeat", sender="node-t",
        payload={"device_id": device_id}, auth=headers))).payload
    assert rep["lifecycle"] == "online", rep
    return adapter, host, port, client, device_id, secret


def test_event_ingest_ok(tmp_path):
    adapter, host, port, client, device_id, secret = _online_authed(tmp_path)
    try:
        headers = _auth_headers(client, "node-t", device_id, secret)
        rep = client.send(FabricMessage.from_dict(_msg(
            "event", sender="node-t",
            payload={"device_id": device_id, "event": "battery.low",
                     "level": 9},
            auth=headers))).payload
        assert rep["ok"] and isinstance(rep["dots"], list), rep
    finally:
        client.close()
        host.stop()


def test_event_invalid_type_rejected(tmp_path):
    adapter, host, port, client, device_id, secret = _online_authed(tmp_path)
    try:
        headers = _auth_headers(client, "node-t", device_id, secret)
        rep = client.send(FabricMessage.from_dict(_msg(
            "event", sender="node-t",
            payload={"device_id": device_id, "event": "mind.control"},
            auth=headers))).payload
        assert rep["ok"] is False
    finally:
        client.close()
        host.stop()


# -- command E2E -------------------------------------------------------------------

def _granted_online(tmp_path, on_request=None):
    policy = _policy([("cli", "device.device.battery")])
    adapter = _adapter(tmp_path, policy)
    host, port = _host(adapter)
    device_id, code = _register(adapter)
    client, secret = _socket_pair(adapter, host, port, device_id, code,
                                  on_request=on_request)
    headers = _auth_headers(client, "node-t", device_id, secret)
    rep = client.send(FabricMessage.from_dict(_msg(
        "heartbeat", sender="node-t",
        payload={"device_id": device_id}, auth=headers))).payload
    assert rep["lifecycle"] == "online", rep
    adapter.declare_android_capabilities(device_id, ["device.battery"],
                                         by="tester")
    return adapter, host, port, client, device_id, secret


def test_command_e2e_approval_then_bare_wire_and_proof(tmp_path):
    duplex_seen = {}

    def answer(msg):
        if msg.message_type != "command_request":
            return None
        duplex_seen["wire"] = msg.capability
        duplex_seen["proof"] = (msg.auth or {}).get("proof")
        assert msg.capability == "get_battery", msg.capability
        return FabricMessage(
            sender_node="node-t", recipient_node=msg.sender_node,
            message_type="command_result",
            correlation_id=msg.message_id, capability=msg.capability,
            payload={"ok": True, "result": "battery 77%"})

    # The paired lane itself runs the reader that answers host commands,
    # so server.request() gets its correlated reply on the bound lane.
    adapter, host, port, client, device_id, secret = _granted_online(
        tmp_path, on_request=answer)
    seen = {}
    real_request = host.server.request

    def spy(peer, message, timeout_s=None):
        seen["capability"] = message.capability
        assert message.auth.get("proof"), "host proof missing"
        return real_request(peer, message, timeout_s=timeout_s)

    host.server.request = spy  # type: ignore[method-assign]
    try:
        # Router risk (0.75) forces the approval-token roundtrip first.
        need = host.send_command("cli", device_id, "device.get_battery", {})
        assert need["ok"] is False and need.get("requires_approval"), need
        token = need["approval_token"]
        assert adapter.fabric.policy.approve(token, by="tester")
        out = host.send_command("cli", device_id, "device.get_battery", {},
                                approval_token=token)
        assert out["ok"], out
        assert "77" in out["result"]
        assert seen["capability"] == "get_battery"
        assert duplex_seen["wire"] == "get_battery"
        assert duplex_seen["proof"], "client saw no host proof"
    finally:
        client.close()
        host.stop()


def test_command_undeclared_capability_refused(tmp_path):
    adapter, host, port, client, device_id, secret = _granted_online(tmp_path)
    try:
        out = host.send_command("cli", device_id, "device.capture_photo",
                                {})
        assert out["ok"] is False
    finally:
        client.close()
        host.stop()


def test_command_unauthorized_actor_denied(tmp_path):
    adapter = _adapter(tmp_path)  # no grants at all
    host, port = _host(adapter)
    try:
        device_id, code = _register(adapter)
        client, secret = _socket_pair(adapter, host, port, device_id, code)
        try:
            headers = _auth_headers(client, "node-t", device_id, secret)
            client.send(FabricMessage.from_dict(_msg(
                "heartbeat", sender="node-t",
                payload={"device_id": device_id}, auth=headers)))
            adapter.declare_android_capabilities(device_id,
                                                 ["device.battery"],
                                                 by="tester")
            out = host.send_command("intruder", device_id,
                                    "device.get_battery", {})
            assert out["ok"] is False
            assert not out.get("requires_approval")
        finally:
            client.close()
    finally:
        host.stop()


def test_command_unknown_not_on_allowlist(tmp_path):
    adapter = _adapter(tmp_path)
    host, port = _host(adapter)
    try:
        with pytest.raises(AndroidCommandError):
            validate_command("device.self_destruct", {})
        out = host.send_command("cli", "dev-missing", "device.self_destruct",
                                {})
        assert out["ok"] is False
    finally:
        host.stop()


def test_allowlist_has_no_shell_eval_adb():
    banned = ("shell", "exec", "eval", "adb", "subprocess", "system",
              "filesystem", "unrestricted")
    for name in SAFE_COMMANDS:
        assert not any(b in name for b in banned), name
    assert ANDROID_WIRE_NAMES == frozenset(
        n.split(".", 1)[1] for n in SAFE_COMMANDS)


def test_offline_trusted_device_denied(tmp_path):
    policy = _policy([("cli", "device.device.battery")])
    adapter = _adapter(tmp_path, policy)
    device_id, _ = _register(adapter)
    adapter.trust_android(device_id, by="tester", reason="direct")
    router = adapter.fabric.router
    gate = router.authorize("cli", device_id, "device.battery", args={})
    assert gate["authorized"] is False
    assert "not online" in " ".join(gate["reasons"])


def test_offline_queue_and_expiry(tmp_path):
    adapter = _adapter(tmp_path)
    device_id, _ = _register(adapter)
    queued = adapter.send_command("cli", device_id, "device.get_battery",
                                  {})
    assert queued["queued"] is True
    assert adapter.drain(device_id)["dispatched"] == []
    stale = QueuedCommand(device_id=device_id, command="device.get_battery",
                          capability="device.battery", args={}, actor="cli",
                          created_at=1.0, expires_at=2.0)
    assert stale.expired(at=3.0)
    assert not stale.expired(at=1.5)
    assert COMMAND_TTL_S > 0


# -- rendezvous / lifecycle ----------------------------------------------------------

def test_rendezvous_file_lifecycle(tmp_path):
    adapter = _adapter(tmp_path)
    host = AndroidSocketHost(adapter)
    home = adapter.fabric.home
    assert read_host_status(home)["running"] is False
    port = host.start()
    try:
        status = read_host_status(home)
        assert status["running"] is True
        assert status["port"] == port
    finally:
        host.stop()
    assert read_host_status(home)["running"] is False


def test_disconnect_reconnect_reauth(tmp_path):
    adapter = _adapter(tmp_path)
    host, port = _host(adapter)
    try:
        device_id, code = _register(adapter)
        client, secret = _socket_pair(adapter, host, port, device_id, code)
        client.close()
        import time as _time
        deadline = _time.time() + 5.0
        while host.server.status()["peers"] and _time.time() < deadline:
            _time.sleep(0.05)
        assert host.server.status()["peers"] == {}
        client2 = SocketTransport(timeout_s=TIMEOUT)
        client2.connect("127.0.0.1", port)
        try:
            headers = _auth_headers(client2, "node-t", device_id, secret)
            rep = client2.send(FabricMessage.from_dict(_msg(
                "heartbeat", sender="node-t",
                payload={"device_id": device_id}, auth=headers))).payload
            assert rep["ok"], rep
        finally:
            client2.close()
    finally:
        host.stop()


def test_host_stop_cleans_up(tmp_path):
    adapter = _adapter(tmp_path)
    host, port = _host(adapter)
    assert host.server.status()["listening"] is True
    host.stop()
    assert host.server.status()["listening"] is False
    assert host.server.status()["peers"] == {}


def test_telemetry_out_of_range_rejected():
    with pytest.raises(TelemetryError):
        Telemetry(device_id="d", battery_pct=101.0)
    tel = Telemetry(device_id="d", battery_pct=50.0)
    assert "battery_pct" not in tel.unknown_metrics()
    assert "cpu_pct" in tel.unknown_metrics()


def test_android_events_are_closed_set():
    assert "battery.low" in ANDROID_EVENTS
    assert "mind.control" not in ANDROID_EVENTS


# -- 3.10-complete regression: lane spoofing -----------------------------------

def test_spoofed_hello_lane_is_not_routable(tmp_path):
    """An unauthenticated hello claiming a victim node_id must not divert
    that device's commands (F1: lane.device_id binding required)."""
    policy = _policy([("cli", "device.device.battery")])
    adapter = _adapter(tmp_path, policy)
    host, port = _host(adapter)
    try:
        device_id, code = _register(adapter)
        client, secret = _socket_pair(adapter, host, port, device_id, code)
        try:
            headers = _auth_headers(client, "node-t", device_id, secret)
            rep = client.send(FabricMessage.from_dict(_msg(
                "heartbeat", sender="node-t",
                payload={"device_id": device_id}, auth=headers))).payload
            assert rep["lifecycle"] == "online", rep
            adapter.declare_android_capabilities(device_id,
                                                 ["device.battery"],
                                                 by="tester")
            assert host.has_lane(device_id) is True
            # Attacker on a fresh lane claims the victim's node_id.
            spoof = SocketTransport(timeout_s=TIMEOUT)
            spoof.connect("127.0.0.1", port)
            try:
                hello = spoof.send(FabricMessage.from_dict(_msg(
                    "hello", sender="node-t",
                    payload={"node_id": "node-t"}))).payload
                assert hello.get("hello") is True, hello
                assert host.has_lane(device_id) is False
                # Reach the lane check with a pre-approved token: the
                # denial must be "no live socket lane", never delivery.
                need = host.send_command("cli", device_id,
                                         "device.get_battery", {})
                assert need.get("requires_approval"), need
                token = need["approval_token"]
                assert adapter.fabric.policy.approve(token, by="tester")
                out = host.send_command("cli", device_id,
                                        "device.get_battery", {},
                                        approval_token=token)
                assert out["ok"] is False
                assert "no live socket lane" in out.get("error", ""), out
            finally:
                spoof.close()
        finally:
            client.close()
    finally:
        host.stop()


# -- 3.10-complete regression: explicit auth-failure marker --------------------

def test_unauthenticated_heartbeat_marks_auth_failed(tmp_path):
    """HMAC failures carry auth_failed so the phone stops retrying
    credentials; transient errors must not set it (F2)."""
    adapter, host, port, client, device_id, secret = _online_authed(tmp_path)
    try:
        rep = client.send(FabricMessage.from_dict(_msg(
            "heartbeat", sender="node-t",
            payload={"device_id": device_id},
            auth={"challenge": "wrong", "response": "wrong"}))).payload
        assert rep["ok"] is False
        assert rep.get("auth_failed") is True, rep
    finally:
        client.close()
        host.stop()


# -- 3.10-complete regression: pending-token expiry ----------------------------

def test_expired_pending_token_rejected(tmp_path):
    """Stale pending-approval tokens are swept and rejected (F3)."""
    from jarvis.core.types import now
    adapter = _adapter(tmp_path)
    host, port = _host(adapter)
    try:
        host._pending_approvals["stale-token"] = ("dev-old", 0.0)
        host._pending_approvals["fresh-token"] = ("dev-new", now() + 300.0)
        host._sweep_pending()
        assert "stale-token" not in host._pending_approvals
        assert "fresh-token" in host._pending_approvals
        # End to end: an aged live token is refused at pair_status.
        device_id, code = _register(adapter)
        client = SocketTransport(timeout_s=TIMEOUT)
        client.connect("127.0.0.1", port)
        try:
            rep = client.send(FabricMessage.from_dict(_msg(
                "pair_request", sender="node-t",
                payload={"device_id": device_id, "code": code,
                         "node_id": "node-t"}))).payload
            assert rep["ok"] and rep["pair"] == "pending", rep
            token = rep["pending_token"]
            held = host._pending_approvals[token]
            host._pending_approvals[token] = (held[0], 0.0)
            late = client.send(FabricMessage.from_dict(_msg(
                "pair_status", sender="node-t",
                payload={"device_id": device_id,
                         "pending_token": token}))).payload
            assert late["ok"] is False
            assert "unknown or reused" in late.get("error", ""), late
        finally:
            client.close()
    finally:
        host.stop()


# -- 3.10-complete regression: lane-aware offline drain --------------------------

def test_drain_uses_live_lane_not_inproc_route(tmp_path):
    """Queued commands drain over the socket lane path (authorize +
    lane delivery), never silently via in-process routing (F4)."""
    policy = _policy([("cli", "device.device.battery")])
    adapter = _adapter(tmp_path, policy)
    host, port = _host(adapter)
    try:
        device_id, code = _register(adapter)

        def answer(msg):
            if msg.message_type != "command_request":
                return None
            return FabricMessage(
                sender_node="node-t", recipient_node=msg.sender_node,
                message_type="command_result",
                correlation_id=msg.message_id, capability=msg.capability,
                payload={"ok": True, "result": "battery 77%"})

        client = SocketTransport(timeout_s=TIMEOUT)
        client.connect("127.0.0.1", port, on_request=answer)
        try:
            req = _msg("pair_request", sender="node-t",
                       payload={"device_id": device_id, "code": code,
                                "node_id": "node-t"})
            rep = client.send(FabricMessage.from_dict(req)).payload
            assert rep["pair"] == "pending", rep
            token = rep["pending_token"]
            adapter.declare_android_capabilities(device_id,
                                                 ["device.battery"],
                                                 by="tester")
            # Still offline: command queues (bounded, expiring).
            queued = adapter.send_command("cli", device_id,
                                          "device.get_battery", {})
            assert queued.get("queued") is True, queued
            assert host.has_lane(device_id) is False
            adapter.trust_android(device_id, by="tester",
                                  reason="drain test")
            post = client.send(FabricMessage.from_dict(_msg(
                "pair_status", sender="node-t",
                payload={"device_id": device_id,
                         "pending_token": token}))).payload
            assert post["pair"] == "approved", post
            secret = post["device_secret"]
            headers = _auth_headers(client, "node-t", device_id, secret)
            hb = client.send(FabricMessage.from_dict(_msg(
                "heartbeat", sender="node-t",
                payload={"device_id": device_id}, auth=headers))).payload
            assert hb["lifecycle"] == "online", hb
            assert host.has_lane(device_id) is True
            routed = []
            real_route = adapter.fabric.route_command
            adapter.fabric.route_command = (  # type: ignore[method-assign]
                lambda *a, **k: (routed.append((a, k)), real_route(*a, **k))[1])
            try:
                out = adapter.drain(device_id)
            finally:
                adapter.fabric.route_command = real_route  # type: ignore[method-assign]
            # Approval-gated items stay queued (fail closed with a fresh
            # token path), but the in-process route must never run for a
            # lane device — and nothing may execute silently.
            assert routed == [], routed
            assert out["dispatched"] == []
            assert adapter.queue_depth(device_id)["queued"] == 1
        finally:
            client.close()
    finally:
        host.stop()


# -- 3.10-complete: full ordered E2E over real sockets --------------------------
# No transport mock: a real FabricServer host and real SocketTransport
# clients talk loopback TCP (framing, HMAC, rotation, routing all live).
# The duplex on_request callback plays the phone's command handler.

def test_full_device_e2e_over_real_sockets(tmp_path):
    from jarvis.device.socket_transport import TransportError
    policy = _policy([("cli", "device.device.battery")])
    adapter = _adapter(tmp_path, policy)
    host, port = _host(adapter)
    try:
        # 1. host starts on a real port.
        assert host.port == port and port > 0
        # 2. phone connects; 3. hello.
        seen = {}

        def answer(msg):
            if msg.message_type != "command_request":
                return None
            seen["wire"] = msg.capability
            return FabricMessage(
                sender_node="node-e2e", recipient_node=msg.sender_node,
                message_type="command_result",
                correlation_id=msg.message_id, capability=msg.capability,
                payload={"ok": True, "result": "battery 77%"})

        phone = SocketTransport(timeout_s=TIMEOUT)
        phone.connect("127.0.0.1", port, on_request=answer)
        try:
            hello = phone.send(FabricMessage.from_dict(_msg(
                "hello", sender="node-e2e",
                payload={"node_id": "node-e2e"}))).payload
            assert hello.get("hello") is True, hello
            # 4. register + pair_request -> pending, no trust yet.
            device_id, code = _register(adapter, name="E2EPhone")
            pre_trust = adapter.fabric.registry.require(device_id).trust
            assert str(pre_trust) != "TrustState.TRUSTED", pre_trust
            pending = phone.send(FabricMessage.from_dict(_msg(
                "pair_request", sender="node-e2e",
                payload={"device_id": device_id, "code": code,
                         "node_id": "node-e2e"}))).payload
            assert pending["ok"] and pending["pair"] == "pending", pending
            token = pending["pending_token"]
            # 5. pre-approval poll stays pending.
            early = phone.send(FabricMessage.from_dict(_msg(
                "pair_status", sender="node-e2e",
                payload={"device_id": device_id,
                         "pending_token": token}))).payload
            assert early["pair"] == "pending", early
            # 6. explicit human trust; 7. secret delivered exactly once.
            adapter.trust_android(device_id, by="tester",
                                  reason="e2e approval")
            approved = phone.send(FabricMessage.from_dict(_msg(
                "pair_status", sender="node-e2e",
                payload={"device_id": device_id,
                         "pending_token": token}))).payload
            assert approved["pair"] == "approved", approved
            secret = approved["device_secret"]
            assert secret
            replay_poll = phone.send(FabricMessage.from_dict(_msg(
                "pair_status", sender="node-e2e",
                payload={"device_id": device_id,
                         "pending_token": token}))).payload
            assert replay_poll["ok"] is False, replay_poll
            # 8. challenge -> heartbeat -> online.
            headers = _auth_headers(phone, "node-e2e", device_id, secret)
            hb = phone.send(FabricMessage.from_dict(_msg(
                "heartbeat", sender="node-e2e",
                payload={"device_id": device_id, "battery_pct": 77},
                auth=headers))).payload
            assert hb["lifecycle"] == "online", hb
            assert host.has_lane(device_id) is True
            # 9. capability discovery: declared caps are routable.
            adapter.declare_android_capabilities(device_id,
                                                 ["device.battery"],
                                                 by="tester")
            # 10. allowed typed command -> typed result over the lane.
            need = host.send_command("cli", device_id,
                                     "device.get_battery", {})
            assert need.get("requires_approval"), need
            assert adapter.fabric.policy.approve(
                need["approval_token"], by="tester")
            out = host.send_command("cli", device_id,
                                    "device.get_battery", {},
                                    approval_token=need["approval_token"])
            assert out["ok"] and "77" in out["result"], out
            assert seen["wire"] == "get_battery"
            # 11. phone event -> host ingest.
            ev_headers = _auth_headers(phone, "node-e2e", device_id, secret)
            ev = phone.send(FabricMessage.from_dict(_msg(
                "event", sender="node-e2e",
                payload={"device_id": device_id, "event": "battery.low",
                         "level": 9},
                auth=ev_headers))).payload
            assert ev["ok"] and isinstance(ev["dots"], list), ev
            # 12. unauthorized actor denied (fail closed, no lane use).
            denied = host.send_command("intruder", device_id,
                                       "device.get_battery", {})
            assert denied["ok"] is False, denied
            # 13. replayed heartbeat (rotated challenge) rejected.
            replay = phone.send(FabricMessage.from_dict(_msg(
                "heartbeat", sender="node-e2e",
                payload={"device_id": device_id}, auth=headers))).payload
            assert replay["ok"] is False, replay
            # 14. malformed traffic on a side connection is rejected
            #     and counted; the host keeps serving the good lane.
            raw = socket.create_connection(("127.0.0.1", port),
                                           timeout=TIMEOUT)
            raw.settimeout(TIMEOUT)
            try:
                raw.sendall(b"\xff\xff\xff\xff-not-json")
                buf = bytearray()
                try:
                    while True:
                        chunk = raw.recv(65536)
                        if not chunk:
                            break
                        buf += chunk
                        if decode_frames(buf):
                            break
                except socket.timeout:
                    pass
            finally:
                raw.close()
            assert host.server.rejected >= 1
            fresh = _auth_headers(phone, "node-e2e", device_id, secret)
            still = phone.send(FabricMessage.from_dict(_msg(
                "heartbeat", sender="node-e2e",
                payload={"device_id": device_id}, auth=fresh))).payload
            assert still["lifecycle"] == "online", still
            # 15. drop + reconnect + reauth stays coherent.
            phone.close()
            phone2 = SocketTransport(timeout_s=TIMEOUT)
            phone2.connect("127.0.0.1", port, on_request=answer)
            try:
                h2 = _auth_headers(phone2, "node-e2e", device_id, secret)
                back = phone2.send(FabricMessage.from_dict(_msg(
                    "heartbeat", sender="node-e2e",
                    payload={"device_id": device_id}, auth=h2))).payload
                assert back["lifecycle"] == "online", back
                assert host.has_lane(device_id) is True
            finally:
                phone2.close()
        except TransportError as exc:
            raise AssertionError(f"e2e transport failure: {exc}")
        finally:
            try:
                phone.close()
            except Exception:
                pass
    finally:
        host.stop()
