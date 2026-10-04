"""Defensive security-audit tools tests. No network, no binaries needed."""

from __future__ import annotations

import inspect

import pytest

from jarvis.tools import secaudit
from jarvis.tools.tools import default_registry


def test_target_validation():
    ok, _ = secaudit.validate_target("192.168.1.10")
    assert ok is True
    ok, _ = secaudit.validate_target("192.168.1.0/24")
    assert ok is True
    for bad in ("", "0.0.0.0/0", "10.0.0.0/8", "*", "internet",
                "192.168.1.0/16", "224.0.0.1"):
        ok, reason = secaudit.validate_target(bad)
        assert ok is False, bad
        assert reason


def test_url_validation():
    assert secaudit.validate_url("https://example.com/")[0] is True
    for bad in ("ftp://x/y", "http://localhost:8080/",
                "http:///non", "not a url"):
        assert secaudit.validate_url(bad)[0] is False, bad


def test_missing_resources_fail_honestly(tmp_path, monkeypatch):
    monkeypatch.setattr(secaudit, "_binary", lambda name: None)
    assert secaudit.net_inventory("192.168.1.1")["ok"] is False
    assert secaudit.web_audit("https://example.com/")["ok"] is False
    assert secaudit.sqli_scan("https://example.com/")["ok"] is False
    assert secaudit.capture_read(str(tmp_path / "nope.pcap"))["ok"] is False


def test_wordlist_and_hashfile_required(tmp_path, monkeypatch):
    monkeypatch.setattr(secaudit, "_binary", lambda name: "/bin/x")
    assert secaudit.dir_enum(
        "https://example.com/",
        str(tmp_path / "missing.txt"))["ok"] is False
    assert secaudit.hash_audit(
        str(tmp_path / "missing.hashes"),
        str(tmp_path / "missing.words"))["ok"] is False


def test_no_attack_parameters_exist():
    assert "dump" not in inspect.signature(secaudit.sqli_scan).parameters
    src = inspect.getsource(secaudit)
    for banned in ("shell=True", "os.system", "eval(", "hydra",
                   "aircrack", "deauth", "--os-shell", "--dump",
                   "msfconsole", "meterpreter"):
        assert banned not in src, banned


def test_registry_specs_are_high_risk_gated():
    reg = default_registry()
    for name in ("net_inventory", "web_audit", "dir_enum", "hash_audit",
                 "sqli_scan", "capture_read"):
        tool = reg.get(name)
        assert tool is not None, name
        assert tool.spec.risk.value == "high", name
        assert tool.spec.required_permissions == ["sec.audit"], name


def test_security_card_covers_audit_tools():
    from jarvis.agents.contract import SkillRegistry, role_cards
    cards = {c.role_id: c for c in role_cards()}
    assert "security.audit" in cards["security"].skills
    skills = SkillRegistry()
    audit = skills.get("security.audit")
    assert audit is not None
    assert set(audit.tools) == {"net_inventory", "web_audit",
                                "dir_enum", "hash_audit", "sqli_scan",
                                "capture_read"}


def test_gated_tool_month_denied_without_grant():
    from jarvis.agents.orchestrator import Budgets, Orchestrator
    from jarvis.agents.orchestrator import OrchestratorContext
    from jarvis.agents.agents import AgentRegistry, Planner
    from jarvis.policy.policy import PolicyEngine
    from jarvis.tools.tools import default_registry
    ctx = OrchestratorContext(
        registry=AgentRegistry(), planner=Planner(),
        policy=PolicyEngine(), tools=default_registry())
    orch = Orchestrator(ctx)
    state = {"tool_calls": 0, "agents_used": 0}
    result = orch._gated_tool("security", "net_inventory",
                              {"target": "192.168.1.0/24"},
                              state, Budgets(), "audit scan")
    assert result.success is False  # no sec.audit grant: policy denies
    assert state["tool_calls"] == 0


def test_gated_tool_allowed_with_grant():
    from jarvis.agents.orchestrator import Budgets, Orchestrator
    from jarvis.agents.orchestrator import OrchestratorContext
    from jarvis.agents.agents import AgentRegistry, Planner
    from jarvis.policy.policy import PolicyEngine
    from jarvis.tools.tools import default_registry
    policy = PolicyEngine()
    policy.grant("security", "sec.audit")
    ctx = OrchestratorContext(
        registry=AgentRegistry(), planner=Planner(),
        policy=policy, tools=default_registry())
    orch = Orchestrator(ctx)
    state = {"tool_calls": 0, "agents_used": 0}
    result = orch._gated_tool("coder", "net_inventory",
                              {"target": "192.168.1.0/24"},
                              state, Budgets(), "sneaky scan")
    assert result.success is False  # coder lacks the skill: gate denies
    assert "capabilities" in "; ".join(result.errors)


def test_scan_profiles_validated():
    assert secaudit.net_inventory(
        "192.168.1.1", profile="nukes")["ok"] is False
    out = secaudit.dir_enum("https://example.com/", "/nonexistent",
                            extensions="php,html", threads=99)
    assert out["ok"] is False  # missing wordlist, not bad options


def test_nmap_parser_fixture():
    sample = ("Nmap scan report for router.local (192.168.1.1)\n"
              "22/tcp   open  ssh     OpenSSH 9.2\n"
              "80/tcp   closed http\n")
    findings = secaudit._parse_nmap(sample)
    assert findings[0]["host"] == "router.local"
    assert findings[0]["ports"][0] == {
        "port": 22, "proto": "tcp", "state": "open",
        "service": "ssh", "version": "OpenSSH 9.2"}


def test_gobuster_parser_fixture():
    sample = "/admin (Status: 301)\n/login (Status: 200)\nnoise line\n"
    findings = secaudit._parse_gobuster(sample)
    assert findings == [{"path": "/admin", "status": 301},
                        {"path": "/login", "status": 200}]


def test_sqli_level_clamped():
    import inspect as _inspect
    params = _inspect.signature(secaudit.sqli_scan).parameters
    assert "level" in params  # bounded 1-2 inside
    assert "dump" not in params and "risk" not in params


def test_cracked_parser_fixture():
    sample = "5f4dcc3b5aa765d61d8327deb882cf99:password\nnoise\n"
    findings = secaudit._parse_cracked(sample)
    assert findings[0]["cracked"] == "password"
