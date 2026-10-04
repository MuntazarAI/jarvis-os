"""Security review + Strix bridge: gates, bounds, honest verdicts.

No network, no real Strix binary (a stub script stands in), no mic.
DNS-touching paths use literal IPs only.
"""

import json
import os
import stat
from types import SimpleNamespace

import pytest

from jarvis.security import strix as strix_mod
from jarvis.security.review import review_path
from jarvis.security.strix import (classify_target, run_scan,
                                   strix_binary, to_evidence)


def _jarvis(policy=None):
    return SimpleNamespace(policy=policy, close=lambda: None)


def _args(**kw):
    base = {"action": "review", "target": ".", "mode": "quick",
            "timeout": 600.0, "allow_nonlocal": False, "yes": False,
            "json": False}
    base.update(kw)
    return SimpleNamespace(**base)


# -- static review ------------------------------------------------------------

def test_review_flags_planted_secret_as_high(tmp_path):
    target = tmp_path / "app.py"
    target.write_text('KEY = "AKIAIOSFODNN7EXAMPLE"\n')
    report = review_path(tmp_path)
    assert report["status"] == "fail"
    assert any(f["severity"] == "high" and "secret" in f["kind"]
               for f in report["findings"])
    # the secret value itself is never echoed back
    assert "AKIAIOSFODNN7EXAMPLE" not in json.dumps(report)


def test_review_flags_dangerous_pattern_as_medium(tmp_path):
    (tmp_path / "run.py").write_text("import os\nos.system('ls')\n")
    report = review_path(tmp_path)
    assert report["status"] == "pass"  # mediums don't fail the gate
    assert any("danger" in f["kind"] for f in report["findings"])


def test_review_clean_tree_and_missing_target(tmp_path):
    (tmp_path / "ok.py").write_text("print('hello')\n")
    report = review_path(tmp_path)
    assert report == {**report, "status": "pass", "verdict":
                      "no heuristic hits"}
    missing = review_path(tmp_path / "nope")
    assert missing["status"] == "error"


def test_review_bounds_and_skips(tmp_path):
    (tmp_path / "big.bin").write_bytes(b"\x00" * 100)
    (tmp_path / ".hidden.py").write_text("eval('x')\n")
    (tmp_path / "fine.py").write_text("x = 1\n")
    report = review_path(tmp_path)
    assert report["scanned"] == 1
    assert report["skipped"] == 2
    assert report["findings"] == []


def test_review_never_raises_on_unreadable(tmp_path):
    report = review_path(tmp_path / "ghost" / "deep")
    assert report["status"] == "error"


# -- target classification (offline) ------------------------------------------

def test_classify_local_path_and_loopback(tmp_path):
    assert classify_target(str(tmp_path))["kind"] == "path"
    assert classify_target("http://127.0.0.1:8765/board")["kind"] == \
        "loopback-url"


def test_classify_public_literal_ip_needs_no_dns():
    info = classify_target("http://93.184.216.0/")
    assert info["kind"] == "public-url"


def test_classify_rejects_garbage():
    assert classify_target("")["kind"] == "unsupported"
    assert classify_target("ftp://x/y")["kind"] == "unsupported"
    assert classify_target("nota path at all ??")["kind"] == \
        "unsupported"


# -- bridge gates (no binary needed: policy first) ------------------------------

def test_scan_refuses_without_authorization(tmp_path):
    result = run_scan(str(tmp_path), authorized=False)
    assert result["status"] == "refused"
    assert "authorization" in result["summary"]


def test_scan_refuses_nonlocal_without_flag():
    result = run_scan("http://93.184.216.0/", authorized=True)
    assert result["status"] == "refused"
    assert "non-local" in result["summary"]
    lan = run_scan("http://192.168.1.10/", authorized=True)
    assert lan["status"] == "refused"
    assert "LAN" in lan["summary"]


def test_scan_refuses_bad_mode_and_estop(tmp_path):
    assert run_scan(str(tmp_path), authorized=True,
                    mode="chaos")["status"] == "refused"

    class Stopped:
        def _emergency_stop(self):
            return True

    refused = run_scan(str(tmp_path), authorized=True, policy=Stopped())
    assert refused["status"] == "refused"
    assert "emergency" in refused["summary"]


def test_scan_unavailable_without_binary(tmp_path, monkeypatch):
    monkeypatch.setattr(strix_mod, "strix_binary", lambda: "")
    result = run_scan(str(tmp_path), authorized=True)
    assert result["status"] == "unavailable"
    assert "not installed" in result["summary"]


# -- bridge with a stub binary ---------------------------------------------------

def _stub_strix(tmp_path, body, code=0):
    script = tmp_path / "strix"
    script.write_text("#!/bin/sh\n"
                      f"echo '{body}'\n"
                      f"exit {code}\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(tmp_path)


def test_stub_clean_scan_reports_no_findings(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _stub_strix(bindir, "scan complete: 0 issues")
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep +
                       os.environ.get("PATH", ""))
    assert strix_binary()
    target = tmp_path / "app"
    target.mkdir()
    result = run_scan(str(target), authorized=True)
    assert result["status"] == "no-findings"
    # absence of findings is partial evidence, never proof
    assert result["verification"] == "partial"
    assert "not proof of safety" in result["summary"]


def test_stub_dirty_scan_counts_findings(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _stub_strix(
        bindir, "CRITICAL sql injection HIGH xss medium csrf low info",
        code=1)
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep +
                       os.environ.get("PATH", ""))
    target = tmp_path / "app"
    target.mkdir()
    result = run_scan(str(target), authorized=True)
    assert result["status"] == "findings"
    assert result["verification"] == "partial"  # tool claim ≠ proof
    assert result["findings"]["critical"] >= 1
    assert result["findings"]["high"] >= 1


def test_to_evidence_mapping():
    evidence = to_evidence({"target": "t", "mode": "quick",
                            "status": "findings",
                            "verification": "partial",
                            "summary": "s", "duration_s": 1.0})
    assert evidence["tool"] == "strix"
    assert evidence["verification"] == "partial"
    assert to_evidence({"target": "t", "status": "refused"}
                       )["verdict"] == "unavailable"


# -- CLI exit codes --------------------------------------------------------------

def test_cli_review_exit_codes(tmp_path, capsys):
    from jarvis.cli import _security_action
    (tmp_path / "bad.py").write_text('K = "AKIAIOSFODNN7EXAMPLE"\n')
    code = _security_action(_jarvis(), _args(action="review",
                                             target=str(tmp_path)))
    assert code == 1
    capsys.readouterr()
    (tmp_path / "bad.py").unlink()
    (tmp_path / "ok.py").write_text("x = 1\n")
    assert _security_action(_jarvis(), _args(
        action="review", target=str(tmp_path))) == 0


def test_cli_scan_refusal_is_exit_2(tmp_path, capsys):
    from jarvis.cli import _security_action
    code = _security_action(_jarvis(), _args(
        action="scan", target=str(tmp_path), yes=False))
    assert code == 2
    capsys.readouterr()
