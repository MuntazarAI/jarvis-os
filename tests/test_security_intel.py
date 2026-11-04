"""Security Intelligence 1.0: contracts, scope, durability, remediation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from jarvis.agents.contract import SkillRegistry, role_cards
from jarvis.agents.orchestrator import TEAMS
from jarvis.api.board import build_board
from jarvis.cli import main
from jarvis.core.config import JarvisConfig
from jarvis.policy.policy import PolicyEngine
from jarvis.security.bench import run_benchmark
from jarvis.security.findings import (
    EvidenceRef,
    FindingError,
    FindingState,
    FindingStore,
    SecurityFinding,
    make_finding_id,
    scrub_text,
)
from jarvis.security.intel import (
    MANAGER_ACTOR,
    SecurityError,
    SecurityManager,
    board_security_info,
    validate_scope,
)
from jarvis.security.review import recheck_finding, review_path
from jarvis.tools.tools import default_registry

SECRET_VALUE = "supersecret-value-123"


def _policy(home: Path) -> PolicyEngine:
    config = JarvisConfig()
    config.paths.home = str(home)
    return PolicyEngine(config)


def _manager(home: Path, *, grant: bool = True) -> SecurityManager:
    policy = _policy(home)
    if grant:
        policy.grant(MANAGER_ACTOR, "fs.write")
    return SecurityManager(home, policy=policy)


def _repo(tmp_path: Path, text: str = "DEBUG = True\n") -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text(text, encoding="utf-8")
    return repo


def _finding(**kw) -> SecurityFinding:
    data = dict(title="debug enabled", category="config",
                severity="low", asset="app.py", location="app.py:1",
                kind="pattern:debug-enabled", confidence=0.6,
                provenance="static-review:A05")
    data.update(kw)
    return SecurityFinding(**data)


# -- finding contract ------------------------------------------------------
def test_finding_ids_are_stable_and_location_scoped():
    first = make_finding_id("app.py", "pattern:debug-enabled", "app.py:1")
    second = make_finding_id("app.py", "pattern:debug-enabled", "app.py:1")
    other = make_finding_id("app.py", "pattern:debug-enabled", "app.py:2")
    root_one = make_finding_id("app.py", "pattern:debug-enabled",
                               "app.py:1", root="/repo-one")
    root_two = make_finding_id("app.py", "pattern:debug-enabled",
                               "app.py:1", root="/repo-two")
    assert first == second and first.startswith("sec-")
    assert first != other
    assert root_one != root_two  # same relative path, different repo


def test_finding_scrubs_credentials_and_bounds_text():
    text = scrub_text(
        'password = "hunter2" token: abcdef '
        "https://user:pass@example.com/x " + "z" * 1000)
    assert "hunter2" not in text and "abcdef" not in text
    assert "user:pass" not in text
    assert len(text) < 700


def test_finding_rejects_illegal_lifecycle():
    finding = _finding()
    with pytest.raises(FindingError):
        finding.mark_remediated(before_sha256="a", after_sha256="b")
    finding.mark_validated(by="test")
    with pytest.raises(FindingError):
        finding.mark_reverified(True)  # not remediated yet
    with pytest.raises(FindingError):
        finding.mark_false_positive("")


def test_proposal_is_not_a_fix():
    finding = _finding()
    finding.mark_validated(by="test")
    finding.remediation.update({"status": "proposed", "line": 1})
    assert finding.state is FindingState.VALIDATED
    with pytest.raises(FindingError):
        finding.mark_reverified(True)
    with pytest.raises(FindingError):
        finding.transition(FindingState.REMEDIATED)


def test_store_roundtrip_and_quarantine(tmp_path):
    store = FindingStore(tmp_path)
    finding = store.upsert(_finding())
    assert store.get(finding.finding_id).kind == "pattern:debug-enabled"
    reopened = FindingStore(tmp_path)
    assert reopened.get(finding.finding_id) is not None
    (tmp_path / "security-findings.json").write_text("{broken")
    corrupt = FindingStore(tmp_path)
    assert corrupt.corrupt
    assert corrupt.list() == []
    with pytest.raises(FindingError):
        corrupt.upsert(_finding())


# -- scope -----------------------------------------------------------------
def test_scope_requires_explicit_authorization(tmp_path):
    repo = _repo(tmp_path)
    with pytest.raises(SecurityError):
        validate_scope(repo, authorized=False)
    scope = validate_scope(repo, authorized=True)
    assert scope.kind == "repo"
    assert validate_scope(repo / "app.py", authorized=True).kind == "file"


def test_scope_refuses_missing_root_and_secret_state(tmp_path):
    with pytest.raises(SecurityError):
        validate_scope(tmp_path / "missing", authorized=True)
    with pytest.raises(SecurityError):
        validate_scope("/", authorized=True)
    secrets = tmp_path / "secrets.json"
    secrets.write_text("{}")
    with pytest.raises(SecurityError):
        validate_scope(secrets, authorized=True)


# -- durable intel ---------------------------------------------------------
def test_intel_runs_durable_task_and_validates_findings(tmp_path):
    repo = _repo(tmp_path)
    manager = _manager(tmp_path)
    result = manager.intel(repo, source="test")
    assert result["state"] == "completed"
    assert result["success"] is True
    assert result["counts"]["total"] >= 1
    assert all(f["state"] == "validated" for f in result["findings"])
    task = manager.tasks.get(result["task_id"])
    assert task is not None and task.provenance["domain"] == "security"
    assert task.provenance["discovered"] == result["counts"]["total"]
    report = tmp_path / "security-intel-report.json"
    assert report.exists()
    payload = json.loads(report.read_text())
    assert payload["counts"]["total"] >= 1
    assert any(row["task_id"] == result["task_id"]
               for row in payload["tasks"])


def test_interrupted_task_is_never_success(tmp_path):
    repo = _repo(tmp_path)
    manager = _manager(tmp_path)
    task = manager.start(repo)
    manager.runner.pause(task.task_id)
    result = manager.run(task.task_id)
    assert result["state"] == "paused"
    assert result["complete"] is False
    assert result["success"] is False
    assert result["verification"] == "unverified"


def test_changed_source_becomes_inconclusive_not_fixed(tmp_path):
    repo = _repo(tmp_path)
    manager = _manager(tmp_path)
    task = manager.start(repo)
    manager.runner.advance(task.task_id)   # scope
    manager.runner.advance(task.task_id)   # discover
    (repo / "app.py").write_text("DEBUG = False\n")
    manager.runner.advance(task.task_id)   # validate
    result = manager.run(task.task_id)     # report
    assert result["state"] == "completed"
    assert result["success"] is False
    assert result["verification"] == "partial"
    assert result["counts"]["open"] >= 1
    assert result["posture"] != "clear"
    states = {f["state"] for f in result["findings"]}
    assert states == {"inconclusive"}
    assert "false_positive" not in states
    assert "reverified" not in states


def test_emergency_stop_blocks_intel(tmp_path):
    repo = _repo(tmp_path)
    manager = _manager(tmp_path)
    manager.policy.engage_stop()
    with pytest.raises(SecurityError):
        manager.intel(repo)
    assert not [t for t in manager.tasks.list()
                if t.provenance.get("domain") == "security"]


def test_corrupt_store_fails_closed(tmp_path):
    repo = _repo(tmp_path)
    (tmp_path / "security-findings.json").write_text("{broken")
    manager = _manager(tmp_path)
    assert manager.findings.corrupt
    result = manager.intel(repo)
    assert result["complete"] is False
    assert result["success"] is False
    with pytest.raises(SecurityError):
        manager.discover(repo)


def test_same_relative_path_in_two_roots_does_not_collide(tmp_path):
    manager = _manager(tmp_path)
    findings = []
    for name in ("repo-a", "repo-b"):
        repo = tmp_path / name
        repo.mkdir()
        (repo / "app.py").write_text("DEBUG = True\n")
        result = manager.intel(repo)
        findings.append((result["task_id"],
                         {f["finding_id"] for f in result["findings"]}))
    ids_a, ids_b = findings[0][1], findings[1][1]
    assert ids_a and ids_b
    assert ids_a.isdisjoint(ids_b)
    assert manager.findings.get(next(iter(ids_a))).task_id == findings[0][0]
    assert manager.findings.get(next(iter(ids_b))).task_id == findings[1][0]


def test_emergency_stop_gates_validate_and_propose(tmp_path):
    manager, finding, _path = _validated_debug(tmp_path)
    manager.policy.engage_stop()
    with pytest.raises(SecurityError):
        manager.validate_findings()
    with pytest.raises(SecurityError):
        manager.propose_remediation(finding.finding_id)


def test_report_and_store_never_contain_secret_value(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "config.py").write_text(
        f'password = "{SECRET_VALUE}"\n', encoding="utf-8")
    manager = _manager(tmp_path)
    manager.intel(repo)
    for name in ("security-findings.json", "security-intel-report.json"):
        path = tmp_path / name
        assert path.exists()
        assert SECRET_VALUE not in path.read_text()


# -- remediation -----------------------------------------------------------
def _validated_debug(tmp_path) -> tuple[SecurityManager, SecurityFinding, Path]:
    repo = _repo(tmp_path)
    manager = _manager(tmp_path)
    manager.intel(repo)
    finding = next(f for f in manager.findings.list()
                   if f.kind == "pattern:debug-enabled")
    return manager, finding, repo / "app.py"


def test_remediation_requires_validation_and_approval(tmp_path):
    manager, finding, path = _validated_debug(tmp_path)
    proposal = manager.propose_remediation(finding.finding_id)
    assert proposal["status"] == "proposed"
    assert manager.findings.get(finding.finding_id).state is \
        FindingState.VALIDATED
    result = manager.apply_remediation(finding.finding_id)
    assert result["status"] == "needs_approval"
    assert path.read_text().strip() == "DEBUG = True"
    token = result["approval_token"]
    assert manager.policy.redeem(
        token, MANAGER_ACTOR, result["approval_action"], {}) is False


def test_remediation_denied_without_policy_grant(tmp_path):
    manager, finding, path = _validated_debug(tmp_path)
    manager.policy.revoke(MANAGER_ACTOR, "fs.write")
    manager.propose_remediation(finding.finding_id)
    result = manager.apply_remediation(finding.finding_id)
    assert result["status"] == "denied"
    assert "fs.write" in result["detail"]
    assert path.read_text().strip() == "DEBUG = True"


def test_remediation_applies_and_reverifies(tmp_path):
    manager, finding, path = _validated_debug(tmp_path)
    proposal = manager.propose_remediation(finding.finding_id)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    step = manager.apply_remediation(
        finding.finding_id, replacement=proposal["replacement"])
    assert step["status"] == "needs_approval"
    token = step["approval_token"]
    assert manager.policy.approve(token, by="test")
    applied = manager.apply_remediation(
        finding.finding_id, replacement=proposal["replacement"],
        approval=token)
    assert applied["status"] == "remediated", applied
    assert path.read_text().strip() == "DEBUG = False"
    stored = manager.findings.get(finding.finding_id)
    assert stored.state is FindingState.REMEDIATED
    assert stored.remediation["before_sha256"] == before
    assert stored.remediation["after_sha256"] == applied["after_sha256"]
    assert manager.policy.approvals[token]["status"] == "consumed"
    verified = manager.verify_remediation(finding.finding_id)
    assert verified["status"] == "reverified"
    assert manager.findings.get(finding.finding_id).state is \
        FindingState.REVERIFIED


def test_remediation_verification_fails_when_rule_remains(tmp_path):
    manager, finding, path = _validated_debug(tmp_path)
    replacement = "DEBUG = True  # reviewed but still true"
    manager.propose_remediation(finding.finding_id, replacement)
    step = manager.apply_remediation(finding.finding_id,
                                     replacement=replacement)
    token = step["approval_token"]
    manager.policy.approve(token, by="test")
    applied = manager.apply_remediation(
        finding.finding_id, replacement=replacement, approval=token)
    assert applied["status"] == "remediated"
    verified = manager.verify_remediation(finding.finding_id)
    assert verified["status"] == "still_present"
    assert verified["ok"] is False
    stored = manager.findings.get(finding.finding_id)
    assert stored.state is FindingState.INCONCLUSIVE
    assert stored.verification.value == "failed"


def test_stale_proposal_and_emergency_stop_fail_closed(tmp_path):
    manager, finding, path = _validated_debug(tmp_path)
    manager.propose_remediation(finding.finding_id)
    path.write_text("DEBUG = True\n# changed\n")
    stale = manager.apply_remediation(finding.finding_id)
    assert stale["status"] == "stale_proposal"
    manager.policy.engage_stop()
    with pytest.raises(SecurityError):
        manager.apply_remediation(finding.finding_id)


def test_remediation_only_touches_authorized_target(tmp_path):
    manager, finding, _path = _validated_debug(tmp_path)
    finding.asset = "../escape.py"
    finding.location = "../escape.py:1"
    manager.findings.save(finding)
    with pytest.raises(SecurityError):
        manager.propose_remediation(finding.finding_id)


def test_verify_rejects_file_changed_after_remediation(tmp_path):
    manager, finding, path = _validated_debug(tmp_path)
    proposal = manager.propose_remediation(finding.finding_id)
    step = manager.apply_remediation(
        finding.finding_id, replacement=proposal["replacement"])
    token = step["approval_token"]
    assert manager.policy.approve(token, by="test")
    applied = manager.apply_remediation(
        finding.finding_id, replacement=proposal["replacement"],
        approval=token)
    assert applied["status"] == "remediated"
    path.write_text("DEBUG = False\n# changed after the approved fix\n")
    result = manager.verify_remediation(finding.finding_id)
    assert result["status"] == "unknown"
    assert result["state"] == "remediated"
    assert manager.findings.get(finding.finding_id).state is \
        FindingState.REMEDIATED


def test_file_scope_cannot_touch_a_sibling(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("DEBUG = True\n")
    (repo / "sibling.py").write_text("DEBUG = True\n")
    manager = _manager(tmp_path)
    manager.intel(repo / "app.py")
    finding = next(f for f in manager.findings.list()
                   if f.kind == "pattern:debug-enabled")
    assert finding.asset == "app.py"
    finding.asset = "sibling.py"
    finding.location = "sibling.py:1"
    manager.findings.save(finding)
    with pytest.raises(SecurityError):
        manager.propose_remediation(finding.finding_id)


# -- board, roles, tool ----------------------------------------------------
def test_board_security_section_is_scrubbed(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "config.py").write_text(
        f'password = "{SECRET_VALUE}"\nDEBUG = True\n')
    manager = _manager(tmp_path)
    manager.intel(repo)
    info = board_security_info(tmp_path)
    assert info["posture"] in ("attention", "critical", "review")
    assert info["counts"]["total"] >= 1
    assert SECRET_VALUE not in json.dumps(info)
    assert all("evidence" not in row for row in info["findings"])

    jarvis = SimpleNamespace(
        config=SimpleNamespace(
            paths=SimpleNamespace(home=str(tmp_path)),
            voice=SimpleNamespace(tts_provider="fake", profile="jarvis",
                                  style="calm")),
        status=lambda: {"cycle": 1}, policy=_policy(tmp_path),
        events=SimpleNamespace(count=lambda: 0, types=lambda: {}),
        missions=None, dots=None, tasks=None, notifier=None, world=None)
    snapshot = build_board(jarvis)
    assert "security" in snapshot


def test_security_roles_and_team_are_least_privilege():
    cards = {c.role_id: c for c in role_cards()}
    expected = {"code-security", "dependency-security", "config-security",
                "web-security", "secrets-exposure", "remediation-verifier",
                "security-report"}
    assert expected <= set(cards)
    assert "security.intel" in cards["security"].skills
    assert "security.audit" not in cards["secrets-exposure"].skills
    assert cards["security-report"].may_act is False
    assert len(TEAMS["security"]) <= 8
    assert all(role in cards for role, _ in TEAMS["security"])
    registry = SkillRegistry()
    for name in ("security.intel", "security.code", "security.dependencies",
                 "security.config", "security.secrets",
                 "security.remediation", "security.report"):
        assert registry.get(name) is not None


def test_static_scan_tool_is_safe_and_redacted(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "config.py").write_text(
        f'password = "{SECRET_VALUE}"\n', encoding="utf-8")
    registry = default_registry()
    tool = registry.get("code_security_scan")
    assert tool is not None
    assert tool.spec.risk.value == "safe"
    assert tool.spec.required_permissions == ["fs.read"]
    result = registry.call("code_security_scan", target=str(repo))
    assert result.ok is True
    assert result.output["findings"]
    assert SECRET_VALUE not in json.dumps(result.output)


# -- scanner re-check ------------------------------------------------------
def test_recheck_helper_distinguishes_resolved_and_moved(tmp_path):
    path = tmp_path / "app.py"
    path.write_text("DEBUG = True\n")
    assert recheck_finding(path, "pattern:debug-enabled", 1)["state"] == \
        "still_present"
    path.write_text("# header\nDEBUG = True\n")
    moved = recheck_finding(path, "pattern:debug-enabled", 1)
    assert moved["state"] == "still_present" and moved["line"] == 2
    path.write_text("DEBUG = False\n")
    assert recheck_finding(path, "pattern:debug-enabled", 1)["state"] == \
        "resolved"
    path.unlink()
    assert recheck_finding(path, "pattern:debug-enabled", 1)["state"] == \
        "unknown"


def test_review_detects_manifests_and_config(tmp_path):
    (tmp_path / "requirements.txt").write_text(
        "requests\nflask==2.0.0\npytest==*\n"
        "--extra-index-url http://packages.example/simple\n")
    (tmp_path / "settings.py").write_text(
        'ALLOW_ORIGINS = ["*"]\nHOST = "0.0.0.0"\n'
        "verify=False\nDEBUG = True\n")
    kinds = {f["kind"] for f in review_path(tmp_path)["findings"]}
    assert {"dependency:unpinned", "dependency:wildcard",
            "dependency:insecure-index", "pattern:cors-wildcard",
            "pattern:bind-all", "pattern:tls-verify-off",
            "pattern:debug-enabled"} <= kinds


def test_review_handles_hidden_parents_and_symlinks(tmp_path):
    hidden = tmp_path / ".cache" / "repo"
    hidden.mkdir(parents=True)
    (hidden / "app.py").write_text("DEBUG = True\n")
    outside = tmp_path / "outside.py"
    outside.write_text('password = "hunter2example"\n')
    (hidden / "link.py").symlink_to(outside)
    report = review_path(hidden)
    assert report["scanned"] >= 1
    assert any(f["kind"] == "pattern:debug-enabled"
               for f in report["findings"])
    assert all(f["file"] != "link.py" for f in report["findings"])
    assert all("hunter2example" not in f["evidence"]
               for f in report["findings"])


def test_scan_limit_is_incomplete_not_a_clean_pass(tmp_path, monkeypatch):
    import jarvis.security.review as review_module
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("DEBUG = True\n")
    (repo / "b.py").write_text("DEBUG = True\n")
    monkeypatch.setattr(review_module, "MAX_FILES", 1)
    report = review_module.review_path(repo)
    assert report["truncated"] is True
    manager = _manager(tmp_path)
    result = manager.intel(repo)
    assert result["truncated"] is True
    assert result["success"] is False
    assert result["verification"] == "partial"
    with pytest.raises(SecurityError):
        manager.discover(repo)


# -- benchmark -------------------------------------------------------------
def test_benchmark_measures_detection_and_remediation(tmp_path):
    corpus = Path(__file__).parent / "fixtures" / "security_bench"
    manifest = corpus / "manifest.json"
    fixture = corpus / "cases" / "remediation_app" / "settings.py"
    before = (hashlib.sha256(manifest.read_bytes()).hexdigest(),
              hashlib.sha256(fixture.read_bytes()).hexdigest())
    result = run_benchmark(corpus, home=str(tmp_path))
    metrics = result["metrics"]
    assert result["passed"] is True
    assert metrics["precision"] == 1.0
    assert metrics["recall"] == 1.0
    assert metrics["false_positive"] == 0
    assert metrics["validation_rate"] == 1.0
    assert metrics["remediation_rate"] == 1.0
    assert metrics["line_accuracy"] == 1.0
    assert metrics["deterministic"] is True
    assert metrics["latency_ms"] >= 0
    assert metrics["cpu_ms"] >= 0
    assert metrics["ram_peak_mb"] > 0
    after = (hashlib.sha256(manifest.read_bytes()).hexdigest(),
             hashlib.sha256(fixture.read_bytes()).hexdigest())
    assert before == after  # the corpus is copied, never modified


# -- CLI -------------------------------------------------------------------
def _json_out(capsys) -> dict:
    text = capsys.readouterr().out.strip()
    start = text.find("{")
    assert start >= 0, text
    return json.loads(text[start:])


def test_cli_intel_findings_and_remediation_roundtrip(tmp_path, capsys):
    home = tmp_path / "home"
    repo = _repo(tmp_path, "DEBUG = True\n")
    assert main(["--home", str(home), "security", "intel",
                 "--target", str(repo), "--json"]) == 1
    intel = _json_out(capsys)
    assert intel["complete"] is True and intel["counts"]["total"] >= 1

    assert main(["--home", str(home), "security", "findings",
                 "--json"]) == 0
    listed = _json_out(capsys)
    finding = next(f for f in listed["findings"]
                   if f["kind"] == "pattern:debug-enabled")

    assert main(["--home", str(home), "security", "remediate",
                 "--finding", finding["finding_id"], "--actor", "coder",
                 "--json"]) == 2
    pending = _json_out(capsys)
    assert pending["status"] == "needs_approval"
    prefix = pending["approval_hint"].rstrip("…")
    assert (repo / "app.py").read_text().strip() == "DEBUG = True"

    assert main(["--home", str(home), "approvals", "approve",
                 "--token", prefix, "--json"]) == 0
    _json_out(capsys)

    assert main(["--home", str(home), "security", "remediate",
                 "--finding", finding["finding_id"], "--actor", "coder",
                 "--approval", prefix, "--json"]) == 0
    applied = _json_out(capsys)
    assert applied["status"] == "remediated"
    assert (repo / "app.py").read_text().strip() == "DEBUG = False"

    assert main(["--home", str(home), "security", "verify",
                 "--finding", finding["finding_id"], "--json"]) == 0
    verified = _json_out(capsys)
    assert verified["status"] == "reverified"


def test_cli_review_and_scan_exit_codes_are_preserved(tmp_path, capsys):
    home = tmp_path / "home"
    clean = tmp_path / "clean"
    clean.mkdir()
    (clean / "app.py").write_text("DEBUG = False\n")
    assert main(["--home", str(home), "security", "review",
                 "--target", str(clean), "--json"]) == 0
    _json_out(capsys)
    dirty = _repo(tmp_path, 'password = "hunter2example"\n')
    assert main(["--home", str(home), "security", "review",
                 "--target", str(dirty), "--json"]) == 1
    _json_out(capsys)
    assert main(["--home", str(home), "security", "scan",
                 "--target", "http://127.0.0.1:1", "--json"]) == 2
    _json_out(capsys)
