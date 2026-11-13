"""CLI + API contracts: exit codes, flags, and request bounds.

Every promise here is made to scripts, not humans: a failed operation
exits non-zero, a doctor reports failure in the exit code, `--home`
is honoured wherever it appears, and the HTTP API refuses oversized or
malformed requests instead of dying.

Deterministic and offline: tmp homes, loopback sockets, no network,
no models, no mic.
"""

from __future__ import annotations

import socket
from types import SimpleNamespace

import pytest

from jarvis.cli import main


@pytest.fixture(autouse=True)
def _never_touch_real_home(tmp_path, monkeypatch):
    """No test may write to the operator's real ~/.jarvis-os."""
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "env-home"))


# -- helpers -------------------------------------------------------------

def _fake_jarvis(home: str = "") -> SimpleNamespace:
    class _Bus:
        def subscribe(self, *args, **kwargs):
            return True

    class _Events:
        def count(self):
            return 0

        def types(self):
            return {}

        def record(self, *args, **kwargs):
            return None

    jarvis = SimpleNamespace()
    jarvis.config = SimpleNamespace(
        paths=SimpleNamespace(home=home),
        voice=SimpleNamespace(tts_provider="fake", profile="jarvis",
                              style="calm"),
        world=SimpleNamespace())
    jarvis.status = lambda: {"cycle": 0, "agents": {}}
    jarvis.bus = _Bus()
    jarvis.events = _Events()
    jarvis.policy = SimpleNamespace(approvals={}, _emergency_stop=lambda: False,
                                    conflicts=lambda: 0)
    jarvis.missions = SimpleNamespace(list=lambda: [],
                                      list_proposals=lambda: [])
    jarvis.dots = SimpleNamespace(list=lambda: [])
    jarvis.tasks = SimpleNamespace(stats=lambda: {"total": 0})
    jarvis.notifier = None
    jarvis.world = SimpleNamespace()
    jarvis.close = lambda: None
    jarvis.cycle_once = lambda text: SimpleNamespace(
        to_dict=lambda: {"ok": True, "response": "hi"})
    return jarvis


def _serve(jarvis, token: str = "") -> "tuple[object, int]":
    """Start the API on loopback with an ephemeral port."""
    from jarvis.api.server import JarvisAPI
    api = JarvisAPI(jarvis, host="127.0.0.1", port=0, token=token)
    api.serve_forever()
    return api, api.port


def _raw_request(port: int, request: str, read_body: bool = True) -> str:
    """Send a raw HTTP request and return the whole response.

    HTTP/1.0 without keep-alive: the server closes the connection
    after the response, so the body ends at EOF.
    """
    with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
        sock.sendall(request.encode())
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
        if read_body:
            while True:
                try:
                    chunk = sock.recv(4096)
                except OSError:
                    break
                if not chunk:
                    break
                data += chunk
        return data.decode(errors="replace")


def _status_line(response: str) -> str:
    return response.split("\r\n", 1)[0]


# -- doctor exit codes ---------------------------------------------------

def test_pi_doctor_exits_nonzero_when_a_check_fails(tmp_path, monkeypatch):
    from jarvis.device.pi_adapter import PiNodeAdapter
    monkeypatch.setattr(
        PiNodeAdapter, "doctor",
        lambda self: [{"name": "registry", "ok": False,
                        "detail": "no registry"}])
    assert main(["--home", str(tmp_path), "pi", "doctor"]) == 1


def test_device_fabric_doctor_exits_nonzero_when_a_check_fails(
        tmp_path, monkeypatch):
    from jarvis.device.fabric import DeviceFabric
    monkeypatch.setattr(
        DeviceFabric, "doctor",
        lambda self: [{"name": "policy", "ok": False,
                        "detail": "no policy engine"}])
    assert main(["--home", str(tmp_path), "device-fabric", "doctor"]) == 1


def test_integration_doctor_exits_nonzero_when_a_check_fails(
        tmp_path, monkeypatch):
    from jarvis.cognition import context as context_mod

    class _Broken:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("context engine down")

    monkeypatch.setattr(context_mod, "ContextEngine", _Broken)
    assert main(["--home", str(tmp_path), "integration", "doctor"]) == 1


def test_doctors_exit_zero_when_every_check_passes(tmp_path):
    assert main(["--home", str(tmp_path), "pi", "doctor"]) == 0
    assert main(["--home", str(tmp_path), "device-fabric", "doctor"]) == 0
    assert main(["--home", str(tmp_path), "integration", "doctor"]) == 0


# -- device approvals ----------------------------------------------------

def test_device_approvals_approve_failure_exits_nonzero(tmp_path, capsys):
    code = main(["--home", str(tmp_path), "device", "approvals",
                 "approve", "--approval", "no-such-token"])
    assert code == 1
    assert "cannot approve" in capsys.readouterr().out


def test_device_approvals_deny_failure_exits_nonzero(tmp_path, capsys):
    code = main(["--home", str(tmp_path), "device", "approvals",
                 "deny", "--approval", "no-such-token"])
    assert code == 1
    assert "cannot deny" in capsys.readouterr().out


def test_device_android_approve_failure_exits_nonzero(tmp_path, capsys):
    code = main(["--home", str(tmp_path), "device", "android",
                 "approve", "--approval", "no-such-token"])
    assert code == 1
    assert "cannot approve" in capsys.readouterr().out


def test_device_android_deny_failure_exits_nonzero(tmp_path, capsys):
    code = main(["--home", str(tmp_path), "device", "android",
                 "deny", "--approval", "no-such-token"])
    assert code == 1
    assert "cannot deny" in capsys.readouterr().out


# -- device-fabric command ------------------------------------------------

def test_device_fabric_command_denied_exits_nonzero(tmp_path, capsys):
    code = main(["--home", str(tmp_path), "device-fabric", "command",
                 "--device", "no-such-device", "--capability", "a.b"])
    assert code == 1
    assert "unknown device" in capsys.readouterr().out


def test_device_fabric_command_success_exits_zero(tmp_path, monkeypatch):
    from jarvis.device.fabric import DeviceFabric
    monkeypatch.setattr(
        DeviceFabric, "route_command",
        lambda self, actor, device_id, capability, args=None,
        approval_token="": {"ok": True, "result": "done"})
    assert main(["--home", str(tmp_path), "device-fabric", "command",
                 "--device", "dev-1", "--capability", "a.b"]) == 0


# -- security scan --------------------------------------------------------

def _scan_args(**kw):
    base = {"action": "scan", "target": ".", "mode": "quick",
            "timeout": 600.0, "allow_nonlocal": False, "yes": True,
            "json": False}
    base.update(kw)
    return SimpleNamespace(**base)


def test_security_scan_error_status_exits_3(tmp_path, monkeypatch):
    from jarvis.security import strix as strix_mod
    from jarvis.cli import _security_action
    monkeypatch.setattr(strix_mod, "run_scan", lambda *a, **kw: {
        "tool": "strix", "target": ".", "mode": "quick",
        "status": "error", "verification": "unknown", "findings": [],
        "summary": "scan launch failed: PermissionError", "duration_s": 0.0})
    code = _security_action(_fake_jarvis(str(tmp_path)), _scan_args())
    assert code == 3


def test_security_scan_unverified_no_findings_exits_nonzero(
        tmp_path, monkeypatch):
    from jarvis.security import strix as strix_mod
    from jarvis.cli import _security_action
    monkeypatch.setattr(strix_mod, "run_scan", lambda *a, **kw: {
        "tool": "strix", "target": ".", "mode": "quick",
        "status": "no-findings", "verification": "partial", "findings": [],
        "summary": "no findings", "duration_s": 0.0})
    code = _security_action(_fake_jarvis(str(tmp_path)), _scan_args())
    assert code == 1


def test_security_scan_verified_exits_zero(tmp_path, monkeypatch):
    from jarvis.security import strix as strix_mod
    from jarvis.cli import _security_action
    monkeypatch.setattr(strix_mod, "run_scan", lambda *a, **kw: {
        "tool": "strix", "target": ".", "mode": "quick",
        "status": "clean", "verification": "verified", "findings": [],
        "summary": "clean", "duration_s": 0.0})
    code = _security_action(_fake_jarvis(str(tmp_path)), _scan_args())
    assert code == 0


# -- approvals deny reason -------------------------------------------------

def test_approvals_deny_reason_reaches_the_audit_trail(tmp_path, capsys):
    from jarvis.cli import _approvals_action
    from jarvis.core.config import JarvisConfig
    from jarvis.core.types import ActionPlan
    from jarvis.policy.policy import PolicyEngine
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    config = JarvisConfig()
    config.paths.home = home
    policy = PolicyEngine(config)
    token = policy.request_approval(
        "security",
        ActionPlan(action="net_inventory x", args={"a": 1},
                   required_permissions=["sec.audit"]),
        type("D", (), {"risk": 0.9})())

    fake = SimpleNamespace(policy=policy, close=lambda: None)
    assert _approvals_action(fake, SimpleNamespace(
        json=False, action="deny", token=token, state="",
        reason="out of scope for tonight")) == 0
    capsys.readouterr()
    entry = policy.approvals[token]
    assert entry["status"] == "denied"
    assert entry["deny_reason"] == "out of scope for tonight"


# -- HTTP request bounds ---------------------------------------------------

def test_post_rejects_oversized_body_with_413():
    api, port = _serve(_fake_jarvis())
    try:
        response = _raw_request(port, (
            "POST /cycle HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{port}\r\n"
            "Content-Type: application/json\r\n"
            "Content-Length: 999999999\r\n"
            "\r\n"))
    finally:
        api.shutdown()
    assert "413" in _status_line(response)
    assert "too large" in response


def test_post_rejects_malformed_content_length_with_400():
    api, port = _serve(_fake_jarvis())
    try:
        response = _raw_request(port, (
            "POST /cycle HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{port}\r\n"
            "Content-Type: application/json\r\n"
            "Content-Length: not-a-number\r\n"
            "\r\n"))
    finally:
        api.shutdown()
    assert "400" in _status_line(response)
    assert "invalid Content-Length" in response


def test_post_within_the_cap_still_works():
    api, port = _serve(_fake_jarvis())
    try:
        response = _raw_request(port, (
            "POST /cycle HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{port}\r\n"
            "Content-Type: application/json\r\n"
            "Content-Length: 18\r\n"
            "\r\n"
            '{"input": "hello"}'))
    finally:
        api.shutdown()
    assert "200" in _status_line(response)


# -- board live feed --------------------------------------------------------

def test_board_websocket_url_carries_the_token():
    from jarvis.api.board import BOARD_HTML
    assert "?token=" in BOARD_HTML
    assert "encodeURIComponent(token)" in BOARD_HTML


def test_websocket_handshake_accepts_the_token_in_the_query():
    api, port = _serve(_fake_jarvis(), token="SECRET-TOKEN-123")
    try:
        good = _raw_request(port, (
            "GET /?token=SECRET-TOKEN-123 HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"), read_body=False)
        bad = _raw_request(port, (
            "GET / HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"), read_body=False)
    finally:
        api.shutdown()
    assert "101" in _status_line(good)
    assert "403" in _status_line(bad)


# -- see ------------------------------------------------------------------

def test_see_reports_nothing_recognized_and_exits_nonzero(
        tmp_path, monkeypatch, capsys):
    from jarvis.vision import observer as observer_mod
    fed: list[object] = []

    class _Obs:
        ok = True
        error = "nothing recognized"

        def summary(self):
            return "empty observation"

    class _FakeObserver:
        def __init__(self, config=None):
            self.config = config

        def see_file(self, path, question="", scene=True):
            return _Obs()

        def feed(self, obs, world=None, palace=None, mentalist=None):
            fed.append(obs)
            return {"memory_id": "mem-should-not-exist"}

    monkeypatch.setattr(observer_mod, "VisionObserver", _FakeObserver)
    code = main(["--home", str(tmp_path), "see", "file",
                 "--path", str(tmp_path / "shot.png")])
    out = capsys.readouterr().out
    assert code == 1
    assert "nothing recognized" in out
    assert "remembered as" not in out
    assert fed == []  # an empty observation is not filed as a memory


# -- --home on the one-shot front door ------------------------------------

def test_oneshot_honours_home_after_the_text(tmp_path, monkeypatch):
    import jarvis.cli as cli
    seen: dict[str, str] = {}
    real = cli._make_jarvis

    def _spy(home: str):
        seen["home"] = home
        assert home, "--home was dropped: the front door would use the real home"
        return real(home)

    monkeypatch.setattr(cli, "_make_jarvis", _spy)
    assert main(["hello there", "--home", str(tmp_path)]) == 0
    assert seen["home"] == str(tmp_path)
    assert (tmp_path / "events.db").exists()


def test_oneshot_honours_home_before_the_text(tmp_path, monkeypatch):
    import jarvis.cli as cli
    seen: dict[str, str] = {}
    real = cli._make_jarvis

    def _spy(home: str):
        seen["home"] = home
        return real(home)

    monkeypatch.setattr(cli, "_make_jarvis", _spy)
    assert main(["--home", str(tmp_path), "hello there"]) == 0
    assert seen["home"] == str(tmp_path)


def test_oneshot_without_a_home_value_fails_loudly(tmp_path, capsys):
    code = main(["hello there", "--home"])
    assert code == 2
    assert "--home needs a directory" in capsys.readouterr().err
