"""Finish-all batch: proof, feedback, setup, profiles, remote, polish.

CLI-level tests run the real entry point in subprocesses against tmp
homes (no fakes to drift); server header tests use a live ephemeral
port. No network beyond localhost, no models, no mic.
"""

import json
import subprocess
import sys
import urllib.request

import pytest

from jarvis.api.remote import REMOTE_HTML

CLI = [sys.executable, "-m", "jarvis.cli"]


def run_cli(home, *args):
    proc = subprocess.run(
        CLI + ["--home", str(home)] + list(args),
        capture_output=True, text=True, timeout=120)
    return proc.returncode, proc.stdout, proc.stderr


def test_proof_finds_receipt_and_admits_absence(tmp_path):
    code, out, _ = run_cli(tmp_path, "remember", "the gate code is 4821")
    assert code == 0
    code, out, _ = run_cli(tmp_path, "proof", "gate code")
    assert code == 0
    assert "receipt(s)" in out
    assert "gate code is 4821" in out
    code, out, _ = run_cli(tmp_path, "proof",
                           "zebra xylophone quantum banana")
    assert code == 0
    assert "unverified" in out


def test_feedback_is_recorded_and_searchable(tmp_path):
    code, out, _ = run_cli(tmp_path, "feedback",
                           "the reminder was late")
    assert code == 0
    assert "noted" in out
    code, out, _ = run_cli(tmp_path, "proof", "reminder was late")
    assert "receipt(s)" in out


def test_setup_checklist_passes_on_healthy_home(tmp_path):
    code, out, _ = run_cli(tmp_path, "setup")
    assert code == 0
    assert "[ok ] home" in out
    assert "next:" in out


def test_voice_profile_save_and_effective(tmp_path):
    code, out, _ = run_cli(tmp_path, "voice", "profile",
                           "--style", "warning")
    assert code == 0
    assert "effective style: warning" in out
    saved = json.loads((tmp_path / "voice-profile.json").read_text())
    assert saved["style"] == "warning"
    code, out, _ = run_cli(tmp_path, "voice", "profile",
                           "--style", "silly")
    assert code == 2


def test_voice_profile_helpers_unit(tmp_path):
    from jarvis.voice.voice_profile import (effective_style,
                                            load_overrides,
                                            save_overrides)
    assert effective_style(str(tmp_path)) == "normal"
    save_overrides(str(tmp_path), {"style": "uncertain"})
    assert load_overrides(str(tmp_path))["style"] == "uncertain"
    assert effective_style(str(tmp_path)) == "uncertain"
    with pytest.raises(ValueError):
        save_overrides(str(tmp_path), {"nope": 1})
    corrupt = tmp_path / "voice-profile.json"
    corrupt.write_text("{broken")
    assert load_overrides(str(tmp_path)) == {}


def test_status_summary_and_remote_pointer(tmp_path):
    code, out, _ = run_cli(tmp_path, "status-summary")
    assert code == 0
    assert "STATUS" in out and "agents:" in out
    code, out, _ = run_cli(tmp_path, "remote")
    assert code == 0
    assert "/remote" in out


def test_remote_shell_has_no_secrets_and_relative_urls():
    lowered = REMOTE_HTML.lower()
    assert "src=\"http" not in lowered
    assert "href=\"http" not in lowered
    assert "fetch(\"cycle\"" in REMOTE_HTML
    assert "sessionStorage" in REMOTE_HTML


def test_board_and_api_send_no_store(tmp_path):
    from types import SimpleNamespace

    from jarvis.api.server import JarvisAPI

    class Bus:
        def subscribe(self, *a, **k):
            return True

    fake = SimpleNamespace(
        bus=Bus(), cycle=0,
        config=SimpleNamespace(
            paths=SimpleNamespace(home=str(tmp_path)),
            voice=SimpleNamespace(tts_provider="fake"),
            world=None))
    api = JarvisAPI(fake, host="127.0.0.1", port=0)
    api.serve_forever()
    try:
        base = f"http://127.0.0.1:{api.port}"
        for path in ("/board", "/remote", "/api/board"):
            with urllib.request.urlopen(base + path,
                                        timeout=10) as resp:
                assert resp.headers.get("Cache-Control") == \
                    "no-store", path
    finally:
        api.shutdown()


def test_cycle_still_gated_without_token():
    from types import SimpleNamespace

    from jarvis.api.server import JarvisAPI

    class Bus:
        def subscribe(self, *a, **k):
            return True

    fake = SimpleNamespace(
        bus=Bus(), cycle=0,
        config=SimpleNamespace(
            paths=SimpleNamespace(home=""),
            voice=SimpleNamespace(), world=None))
    api = JarvisAPI(fake, token="tok")
    code, _ = api.handle("POST", "/cycle", b'{"input": "hi"}', {})
    assert code == 401
    code, _ = api.handle("GET", "/remote", b"", {})
    assert code == 200  # shell public; the ACTION stays gated
