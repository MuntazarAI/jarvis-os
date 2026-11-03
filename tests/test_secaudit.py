"""Defensive security-audit tools tests. No network, no binaries needed."""

from __future__ import annotations

import inspect
import ipaddress
import json

import pytest

from jarvis.tools import secaudit
from jarvis.tools.tools import default_registry

SENTINEL = "S3NT1NEL-cracked-password-9f2a"
SYNTHETIC_HASH = "synthetic-hash-0001"


def test_target_validation():
    for good in ("192.168.1.10", "192.168.1.0/24", "10.0.0.5",
                 "172.16.4.4", "8.8.8.8", "2606:4700:4700::1111",
                 "fd00::/120", "router.local"):
        ok, reason = secaudit.validate_target(good)
        assert ok is True, (good, reason)
    for bad in ("", "0.0.0.0/0", "10.0.0.0/8", "*", "internet",
                "192.168.1.0/16", "224.0.0.1", "127.0.0.1", "127.1",
                "2130706433", "0x7f000001", "0177.0.0.1", "0.0.0.0",
                "::", "::1", "169.254.169.254", "fe80::1", "localhost",
                "app.localhost", "-p", "--script=http-shell", "-oN",
                "host\n-r", "bad host", "bad..host", "a" * 254,
                "host;rm -rf /", "host$(id)", "host|cat", "[::1]"):
        ok, reason = secaudit.validate_target(bad)
        assert ok is False, bad
        assert reason


def test_url_validation():
    # IP literals keep the checks deterministic: no DNS, no network.
    assert secaudit.validate_url("https://8.8.8.8/")[0] is True
    assert secaudit.validate_url("http://192.168.1.5:8080/x")[0] is True
    assert secaudit.validate_url("http://[2606:4700:4700::1111]/")[0] is True
    for bad in ("ftp://x/y", "http://localhost:8080/",
                "http:///non", "not a url",
                "http://127.0.0.1/", "http://127.1/",
                "http://2130706433/", "http://0x7f000001/",
                "http://0177.0.0.1/", "http://0.0.0.0/",
                "http://[::1]/", "http://[::ffff:127.0.0.1]/",
                "http://169.254.169.254/latest/meta-data/",
                "http://[fe80::1]/", "http://224.0.0.1/",
                "https://bad\\host/", "http://host:bad/"):
        ok, reason = secaudit.validate_url(bad)
        assert ok is False, bad
        assert reason


def test_validate_target_dns_check_is_opt_in(monkeypatch):
    """The legacy syntax-only check stays compatible; net_inventory opts in."""
    monkeypatch.setattr(
        secaudit, "_resolve_host_addresses",
        lambda host: [ipaddress.ip_address("127.0.0.1")])
    assert secaudit.validate_target("router.local")[0] is True
    ok, reason = secaudit.validate_target("router.local", resolve_dns=True)
    assert ok is False and "loopback" in reason


def test_net_inventory_resolves_hostnames_before_scan(monkeypatch):
    calls = []
    resolved = []

    def resolver(host):
        resolved.append(host)
        return [ipaddress.ip_address("8.8.8.8")]

    def fake_run(tool, argv, timeout_s, cap=20000):
        calls.append(list(argv))
        return {"ok": True, "tool": tool, "returncode": 0,
                "output": "", "stderr": ""}

    monkeypatch.setattr(secaudit, "_binary", lambda name: "/bin/x")
    monkeypatch.setattr(secaudit, "_resolve_host_addresses", resolver)
    monkeypatch.setattr(secaudit, "_run", fake_run)

    assert secaudit.net_inventory("example.com")["ok"] is True
    assert resolved == ["example.com"]
    assert calls and calls[0][-1] == "example.com"


@pytest.mark.parametrize("answers", [
    [ipaddress.ip_address("127.0.0.1")],
    [ipaddress.ip_address("8.8.8.8"),
     ipaddress.ip_address("169.254.169.254")],
    [ipaddress.ip_address("::1")],
    [],
])
def test_net_inventory_hostname_fails_closed(monkeypatch, answers):
    calls = []
    monkeypatch.setattr(secaudit, "_binary", lambda name: "/bin/x")
    monkeypatch.setattr(
        secaudit, "_resolve_host_addresses", lambda host: list(answers))
    monkeypatch.setattr(
        secaudit, "_run",
        lambda *a, **kw: calls.append(a) or {"ok": True, "tool": "x"})

    out = secaudit.net_inventory("attacker.example")
    assert out["ok"] is False
    assert out["error"]
    assert calls == []


def test_net_inventory_allows_explicit_private_hostname(monkeypatch):
    calls = []
    monkeypatch.setattr(secaudit, "_binary", lambda name: "/bin/x")
    monkeypatch.setattr(
        secaudit, "_resolve_host_addresses",
        lambda host: [ipaddress.ip_address("192.168.1.10")])
    monkeypatch.setattr(
        secaudit, "_run",
        lambda tool, argv, timeout_s, cap=20000: (
            calls.append(list(argv)) or
            {"ok": True, "tool": tool, "returncode": 0,
             "output": "Nmap done\n", "stderr": ""}))

    out = secaudit.net_inventory("router.local")
    assert out["ok"] is True
    assert calls and calls[0][-1] == "router.local"


def test_url_validation_resolves_hostnames(monkeypatch):
    monkeypatch.setattr(
        secaudit, "_resolve_host_addresses",
        lambda host: [ipaddress.ip_address("8.8.8.8")])
    assert secaudit.validate_url("https://example.com/")[0] is True

    # Every resolved address must pass: one loopback answer fails closed.
    monkeypatch.setattr(
        secaudit, "_resolve_host_addresses",
        lambda host: [ipaddress.ip_address("8.8.8.8"),
                      ipaddress.ip_address("127.0.0.1")])
    assert secaudit.validate_url("https://example.com/")[0] is False

    # Resolution failure is not permission.
    monkeypatch.setattr(secaudit, "_resolve_host_addresses", lambda host: [])
    assert secaudit.validate_url("https://example.com/")[0] is False
    assert secaudit.validate_url("https://example.com/",
                                 resolve_dns=False)[0] is True


def test_missing_resources_fail_honestly(tmp_path, monkeypatch):
    monkeypatch.setattr(secaudit, "_binary", lambda name: None)
    assert secaudit.net_inventory("192.168.1.1")["ok"] is False
    assert secaudit.web_audit("https://8.8.8.8/")["ok"] is False
    assert secaudit.sqli_scan("https://8.8.8.8/")["ok"] is False
    assert secaudit.capture_read(str(tmp_path / "nope.pcap"))["ok"] is False


def test_wordlist_and_hashfile_required(tmp_path, monkeypatch):
    monkeypatch.setattr(secaudit, "_binary", lambda name: "/bin/x")
    assert secaudit.dir_enum(
        "https://8.8.8.8/",
        str(tmp_path / "missing.txt"))["ok"] is False
    assert secaudit.hash_audit(
        str(tmp_path / "missing.hashes"),
        str(tmp_path / "missing.words"))["ok"] is False


def _capture_run(monkeypatch):
    calls = []

    def fake_run(tool, argv, timeout_s, cap=20000):
        calls.append((tool, list(argv)))
        return {"ok": True, "tool": tool, "returncode": 0,
                "output": "", "stderr": ""}

    monkeypatch.setattr(secaudit, "_run", fake_run)
    return calls


def test_external_binaries_get_absolute_file_args(tmp_path, monkeypatch):
    """Files are resolved to absolute paths before argv construction, so a
    name like ``-w`` cannot become an external tool's option."""
    monkeypatch.setattr(secaudit, "_binary", lambda name: "/bin/x")
    words = tmp_path / "-w"
    words.write_text("admin\n")
    hashes = tmp_path / "-m"
    hashes.write_text("5f4dcc3b5aa765d61d8327deb882cf99\n")
    calls = _capture_run(monkeypatch)

    assert secaudit.dir_enum("https://8.8.8.8/", str(words))["ok"] is True
    assert secaudit.capture_read(str(hashes))["ok"] is True
    assert secaudit.hash_audit(str(hashes), str(words))["ok"] is True

    dir_argv = next(argv for tool, argv in calls if tool == "dir_enum")
    cap_argv = next(argv for tool, argv in calls if tool == "capture_read")
    hash_argv = next(argv for tool, argv in calls if tool == "hash_audit")
    assert dir_argv[dir_argv.index("-w") + 1] == str(words.resolve())
    assert cap_argv[cap_argv.index("-r") + 1] == str(hashes.resolve())
    assert f"--wordlist={words.resolve()}" in hash_argv
    assert str(hashes.resolve()) in hash_argv


def test_option_like_target_never_reaches_argv(monkeypatch):
    monkeypatch.setattr(secaudit, "_binary", lambda name: "/bin/x")
    calls = _capture_run(monkeypatch)
    for target in ("-p", "--script=http-shell", "-oN", "-iL"):
        out = secaudit.net_inventory(target, profile="fast")
        assert out["ok"] is False
        assert "option" in out["error"] or "invalid" in out["error"]
    assert calls == []


def test_bounded_numbers_and_modes(tmp_path, monkeypatch):
    monkeypatch.setattr(secaudit, "_binary", lambda name: "/bin/x")
    words = tmp_path / "words.txt"
    words.write_text("x\n")
    hashes = tmp_path / "hashes.txt"
    hashes.write_text("x\n")
    _capture_run(monkeypatch)

    assert secaudit.dir_enum("https://8.8.8.8/", str(words),
                             threads="lots")["ok"] is False
    assert secaudit.sqli_scan("https://8.8.8.8/", level="x")["ok"] is False
    assert secaudit.capture_read(str(hashes),
                                 max_packets="x")["ok"] is False
    assert secaudit.hash_audit(str(hashes), str(words),
                               tool="hashcat",
                               mode="raw-md5")["ok"] is False
    assert secaudit.hash_audit(str(hashes), str(words),
                               mode="--format=bad")["ok"] is False


def test_oversized_inputs_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(secaudit, "_binary", lambda name: "/bin/x")
    monkeypatch.setattr(secaudit, "_MAX_HASHFILE_BYTES", 8)
    monkeypatch.setattr(secaudit, "_MAX_WORDLIST_BYTES", 8)
    hashes = tmp_path / "hashes.txt"
    hashes.write_text("abc\n")
    words = tmp_path / "words.txt"
    words.write_text("0123456789")
    assert secaudit.hash_audit(str(hashes), str(words))["ok"] is False
    assert "wordlist" in secaudit.hash_audit(str(hashes), str(words))["error"]
    big = tmp_path / "big.hashes"
    big.write_text("0123456789")
    assert secaudit.hash_audit(str(big), str(hashes))["ok"] is False
    assert "hash" in secaudit.hash_audit(str(big), str(hashes))["error"]


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


def test_registry_descriptions_match_behavior():
    names = {t["name"]: t for t in default_registry().list_tools()}
    assert "no port scan" not in names["net_inventory"]["description"]
    assert "port/service" in names["net_inventory"]["description"]
    assert "level 1-2" in names["sqli_scan"]["description"]


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
    out = secaudit.dir_enum("https://8.8.8.8/", "/nonexistent",
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


def _hash_fixture(tmp_path):
    hashes = tmp_path / "hashes.txt"
    hashes.write_text(f"{SYNTHETIC_HASH}\n")
    words = tmp_path / "words.txt"
    words.write_text("not-a-real-wordlist\n")
    return hashes, words


def test_hash_audit_redacts_recovered_plaintext(tmp_path, monkeypatch):
    hashes, words = _hash_fixture(tmp_path)
    monkeypatch.setattr(secaudit, "_binary", lambda name: "/bin/x")
    monkeypatch.setattr(
        secaudit, "_run",
        lambda *a, **kw: {
            "ok": True, "tool": "hash_audit", "returncode": 0,
            "output": f"{SYNTHETIC_HASH}:{SENTINEL}\nstatus noise\n",
            "stderr": f"diagnostic {SENTINEL}\n"})

    out = secaudit.hash_audit(str(hashes), str(words))
    blob = json.dumps(out, default=str)
    assert SENTINEL not in blob
    assert SYNTHETIC_HASH not in blob  # only a short prefix is published
    assert out["sensitive"] is True and out["redacted"] is True
    assert out["cracked_count"] == 1
    assert out["findings"] == [{
        "hash": SYNTHETIC_HASH[:16] + "…",
        "cracked": "[redacted]", "recovered": True}]
    assert "withheld" in out["output"].lower()
    assert "withheld" in out["stderr"].lower()
    assert "withheld" in out["note"].lower()


def test_hash_audit_failure_also_withholds_raw_output(tmp_path, monkeypatch):
    hashes, words = _hash_fixture(tmp_path)
    monkeypatch.setattr(secaudit, "_binary", lambda name: "/bin/x")
    monkeypatch.setattr(
        secaudit, "_run",
        lambda *a, **kw: {
            "ok": False, "tool": "hash_audit", "returncode": 1,
            "output": f"{SYNTHETIC_HASH}:{SENTINEL}\n",
            "stderr": f"failed while handling {SENTINEL}\n"})

    out = secaudit.hash_audit(str(hashes), str(words))
    blob = json.dumps(out, default=str)
    assert out["ok"] is False
    assert SENTINEL not in blob
    assert out["findings"] == [] and out["cracked_count"] == 0
    assert "withheld" in out["output"].lower()


def test_hash_audit_result_is_classified_sensitive():
    reg = default_registry()
    assert reg.get("hash_audit").spec.sensitive_output is True
    assert reg.get("net_inventory").spec.sensitive_output is False


def test_hash_audit_sentinel_never_reaches_traces_or_agent_messages(
        tmp_path, monkeypatch):
    """The full orchestrator path must not persist or forward cracked values."""
    from jarvis.agents.agents import AgentRegistry, Planner
    from jarvis.agents.orchestrator import (
        Budgets, Orchestrator, OrchestratorContext)
    from jarvis.core.config import JarvisConfig
    from jarvis.policy.policy import PolicyEngine

    home = tmp_path / "home"
    home.mkdir()
    config = JarvisConfig()
    config.paths.home = home
    policy = PolicyEngine(config)
    policy.grant("security", "sec.audit")
    reg = default_registry()
    hashes, words = _hash_fixture(tmp_path)
    monkeypatch.setattr(secaudit, "_binary", lambda name: "/bin/x")
    monkeypatch.setattr(
        secaudit, "_run",
        lambda *a, **kw: {
            "ok": True, "tool": "hash_audit", "returncode": 0,
            "output": f"{SYNTHETIC_HASH}:{SENTINEL}\n",
            "stderr": f"diagnostic {SENTINEL}\n"})

    ctx = OrchestratorContext(
        registry=AgentRegistry(), planner=Planner(),
        policy=policy, tools=reg, home=str(home))
    orch = Orchestrator(ctx, Budgets(
        max_agents=1, max_tool_calls=1, max_runtime_s=30.0))
    args = {"hashfile": str(hashes), "wordlist": str(words)}
    holder = {"approval": ""}

    def handler(card, goal, board, task_id, state, budgets,
                deadline, depth, purpose):
        return orch._gated_tool("security", "hash_audit", args,
                                state, budgets, "audit",
                                approval=holder["approval"])

    orch._handlers["security"] = handler
    first = orch.run("audit hashes", roles=[("security", "audit")])
    assert first["ok"] is False
    pending = policy.list_approvals("pending")
    assert len(pending) == 1
    token = next(t for t in policy.approvals
                 if t.startswith(pending[0]["approval_id"][:12]))
    assert policy.approve(token, by="test") is True
    holder["approval"] = token

    second = orch.run("audit hashes", roles=[("security", "audit")])
    assert second["ok"] is True
    record = orch.runs[second["run_id"]]
    blobs = [
        json.dumps(second, default=str),
        json.dumps(record.to_dict(), default=str),
        json.dumps(reg.history[-1].to_dict(), default=str),
        orch.explain(second["task_id"]),
    ]
    blobs.extend(path.read_text()
                 for path in (home / "traces").glob("run-*.json"))
    blobs.extend(json.dumps(message.to_dict(), default=str)
                 for message in orch.bus.history(task_id=second["task_id"]))
    joined = "\n".join(blobs)
    assert SENTINEL not in joined
    assert SYNTHETIC_HASH not in joined
    assert "cracked_count" in joined
    assert reg.history[-1].sensitive is True
