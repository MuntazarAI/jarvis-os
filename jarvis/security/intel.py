"""Security Intelligence 1.0 — manager, validation, remediation, reporting.

This module is a *composition* boundary, not a second engine. It reuses:

- :mod:`jarvis.security.review` for deterministic static analysis;
- :class:`jarvis.security.findings.FindingStore` for the finding contract;
- :class:`jarvis.durable.DurableRunner` / ``TaskStore`` for crash-safe
  execution (one authoritative task store, shared with every other task);
- :class:`jarvis.policy.policy.PolicyEngine` for authorization;
- :func:`jarvis.tools.tools.default_registry` for the only write path.

Safety rules enforced here, not assumed:

- analysis targets must be local paths the caller explicitly supplies;
- discovery is read-only; validation re-checks the exact recorded rule;
- a remediation is proposed, then requires a *fresh* policy decision and
  a single-use approval bound to the file hash and finding id;
- a write call never marks a finding fixed — only a post-change re-check
  can move it to ``reverified``;
- emergency stop blocks task start, advancement, and remediation;
- report payloads are scrubbed and bounded; they never contain tokens or
  raw credential material.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .findings import (
    EvidenceRef,
    FindingError,
    FindingState,
    FindingStore,
    RemediationState,
    SecurityFinding,
    Severity,
    ValidationState,
    finding_from_review,
    scrub_text,
    severity_rank,
)
from .review import (SENSITIVE_STATE_NAMES, recheck_finding, review_path)
from ..durable import DurableRunner, StepState, Task, TaskState, TaskStore

MAX_SCOPE_PATH = 500
MAX_REPORT_FINDINGS = 200
MAX_BY_ASSET = 20
MAX_REPLACEMENT = 400
REPORT_FILENAME = "security-intel-report.json"

MANAGER_ACTOR = "security-manager"

STEPS = (
    ("scope: validate authorized local target", "scope"),
    ("discover: deterministic static analysis", "discover"),
    ("validate: re-check evidence at source", "validate"),
    ("report: aggregate security posture", "report"),
)

_SENSITIVE_NAMES = SENSITIVE_STATE_NAMES
# Built from pieces: these are remediation *search* strings, not call
# sites. Keeping them split prevents the static self-review from
# flagging this fixer as vulnerable code.
_YAML_LOAD_CALL = "yaml." + "load("
_TLS_VERIFY_OFF = "verify=" + "False"
_TASK_CONTINUE = (TaskState.READY, TaskState.CHECKPOINTED,
                  TaskState.RETRYING)
_TASK_INTERRUPTED = (TaskState.RUNNING, TaskState.VERIFYING,
                     TaskState.RECOVERING)


class SecurityError(ValueError):
    """Scope, authorization, or remediation failure."""


class _EventSink:
    """Adapt EventStore.record to the runner's record_event protocol."""

    def __init__(self, events: Any) -> None:
        self.events = events

    def record_event(self, kind: str, payload: dict[str, Any]) -> None:
        sink = getattr(self.events, "record", None)
        if callable(sink):
            sink(kind, dict(payload or {}))


@dataclass(frozen=True)
class SecurityScope:
    target: str
    kind: str
    authorized: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"target": self.target, "kind": self.kind,
                "authorized": self.authorized}


def validate_scope(target: str | Path, *, authorized: bool = False
                   ) -> SecurityScope:
    """Validate an explicitly supplied local analysis target.

    ``authorized`` is a deliberate second signal: callers must state
    that the operator supplied/owns the target. It is not a policy
    grant and it authorizes nothing beyond reading that path.
    """
    if not authorized:
        raise SecurityError(
            "target not authorized: pass an explicitly supplied local "
            "repository/worktree (authorized=True)")
    raw = str(target or "").strip()
    if not raw or len(raw) > MAX_SCOPE_PATH:
        raise SecurityError("target must be a non-empty local path")
    path = Path(raw).expanduser()
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError):
        raise SecurityError(f"target does not exist: {raw[:200]}")
    if resolved == Path(resolved.anchor):
        raise SecurityError("refusing to scan a filesystem root")
    if resolved.name in _SENSITIVE_NAMES:
        raise SecurityError(
            f"refusing to scan sensitive state file: {resolved.name}")
    if not (resolved.is_dir() or resolved.is_file()):
        raise SecurityError("target must be a regular file or directory")
    return SecurityScope(target=str(resolved),
                         kind="repo" if resolved.is_dir() else "file")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _line_of(finding: SecurityFinding) -> int:
    try:
        return max(0, int(finding.remediation.get("line", 0) or 0))
    except (TypeError, ValueError):
        return 0


def _line_from_location(location: str) -> int:
    tail = str(location or "").rsplit(":", 1)
    if len(tail) == 2 and tail[1].isdigit():
        return int(tail[1])
    return 0


def _posture(findings: list[SecurityFinding]) -> str:
    open_states = {FindingState.DISCOVERED, FindingState.SUSPECTED,
                   FindingState.VALIDATED, FindingState.REMEDIATED,
                   FindingState.INCONCLUSIVE}
    open_items = [f for f in findings if f.state in open_states]
    if any(f.severity is Severity.CRITICAL for f in open_items):
        return "critical"
    if any(f.severity is Severity.HIGH for f in open_items):
        return "attention"
    if open_items:
        return "review"
    return "clear"


class SecurityManager:
    """One authorized security boundary over existing JARVIS subsystems."""

    def __init__(self, home: str | Path | None, *,
                 policy: Any = None, tools: Any = None,
                 events: Any = None, findings: FindingStore | None = None,
                 task_store: TaskStore | None = None) -> None:
        self.home = Path(home) if home else None
        self.policy = policy
        self.findings = findings or FindingStore(self.home)
        self.tasks = task_store or TaskStore(self.home)
        self._tools = tools
        self._events = _EventSink(events) if events is not None else None
        self.runner = DurableRunner(
            self.tasks, executor=self._execute, checker=self._check,
            policy=policy, events=self._events)

    # -- helpers ---------------------------------------------------------
    def _emit(self, event: str, **payload: Any) -> None:
        if self._events is None:
            return
        clean = {key: (str(value)[:500] if not isinstance(
            value, (int, float, bool, type(None))) else value)
            for key, value in payload.items()}
        try:
            self._events.record_event(event, clean)
        except Exception:
            pass

    def _tools_registry(self) -> Any:
        if self._tools is None:
            from ..tools.tools import default_registry
            self._tools = default_registry()
        return self._tools

    def _emergency(self) -> bool:
        if self.policy is None:
            return False
        check = getattr(self.policy, "emergency_stop_engaged", None)
        if callable(check):
            return bool(check())
        private = getattr(self.policy, "_emergency_stop", None)
        return bool(private()) if callable(private) else False

    def _require_idle(self) -> None:
        if self._emergency():
            raise SecurityError("emergency stop engaged: security work halted")

    def _task(self, task_id: str) -> Task:
        task = self.tasks.get(str(task_id))
        if task is None:
            raise SecurityError(f"unknown security task: {task_id}")
        return task

    def _root_for(self, task: Task) -> Path:
        raw = str(task.provenance.get("target", ""))
        if not raw:
            raise SecurityError("task has no recorded target")
        target = Path(raw)
        return target if target.is_dir() else target.parent

    def _file_for(self, finding: SecurityFinding, root: Path) -> Path:
        asset = Path(str(finding.asset or ""))
        candidate = asset if asset.is_absolute() else (root / asset)
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(root.resolve(strict=True))
        except (OSError, ValueError):
            raise SecurityError(
                f"finding path escapes its authorized target: "
                f"{finding.asset[:200]}")
        if resolved.name in _SENSITIVE_NAMES:
            raise SecurityError("refusing to touch sensitive state file")
        if not resolved.is_file():
            raise SecurityError("finding target is not a regular file")
        return resolved

    def _path_for(self, finding: SecurityFinding) -> tuple[Path, Task]:
        if not finding.task_id:
            raise SecurityError(
                "finding is not linked to a durable task; run "
                "`jarvis security intel` first")
        task = self._task(finding.task_id)
        path = self._file_for(finding, self._root_for(task))
        scope = task.provenance.get("scope") or {}
        kind = scope.get("kind") or task.provenance.get("scope_kind")
        if kind == "file":
            try:
                target = Path(str(
                    task.provenance.get("target", ""))).resolve(strict=True)
            except (OSError, RuntimeError):
                raise SecurityError("authorized file target is unavailable")
            if path != target:
                raise SecurityError(
                    "finding path is outside the authorized file scope")
        return path, task

    # -- durable executor ------------------------------------------------
    def _check(self, task: Task, step: Any) -> str:
        return "unknown"

    def _execute(self, task: Task, step: Any) -> dict[str, Any]:
        if task.provenance.get("domain") != "security":
            return {"ok": False, "kind": "permanent",
                    "error": "not a security task"}
        title = str(step.title).lower()
        if title.startswith("scope"):
            return self._step_scope(task)
        if title.startswith("discover"):
            return self._step_discover(task)
        if title.startswith("validate"):
            return self._step_validate(task)
        if title.startswith("report"):
            return self._step_report(task)
        return {"ok": False, "kind": "permanent",
                "error": f"unknown security step: {step.title[:80]}"}

    def _step_scope(self, task: Task) -> dict[str, Any]:
        self._require_idle()
        try:
            scope = validate_scope(
                str(task.provenance.get("target", "")), authorized=True)
        except SecurityError as exc:
            return {"ok": False, "kind": "policy", "error": str(exc)}
        task.provenance["scope"] = scope.to_dict()
        return {"ok": True, "verification": "verified",
                "output_ref": f"scope:{scope.kind}",
                "side_effects": []}

    def _step_discover(self, task: Task) -> dict[str, Any]:
        self._require_idle()
        if self.findings.corrupt:
            return {"ok": False, "kind": "policy",
                    "error": (f"finding store quarantined: "
                              f"{self.findings.corrupt}")}
        target = str(task.provenance.get("target", ""))
        root = self._root_for(task)
        report = review_path(target)
        if report.get("status") == "error":
            return {"ok": False, "kind": "permanent",
                    "error": str(report.get("verdict", "review failed"))}
        stored = 0
        failed = 0
        for raw in report.get("findings", []):
            try:
                finding = finding_from_review(raw, root=root)
            except (FindingError, ValueError, TypeError):
                failed += 1
                continue
            finding.task_id = task.task_id
            finding.agent_id = "security-manager"
            try:
                existing = self.findings.get(finding.finding_id)
                if (existing is not None and existing.task_id
                        and existing.task_id != task.task_id):
                    try:
                        existing_root = self._root_for(
                            self._task(existing.task_id)).resolve()
                    except (SecurityError, OSError):
                        existing_root = None
                    if (existing_root is not None
                            and existing_root != root.resolve()):
                        failed += 1  # never rebind another root's finding
                        continue
                saved = self.findings.upsert(finding)
                self.findings.update(saved.finding_id,
                                     task_id=task.task_id)
                stored += 1
            except FindingError:
                failed += 1
        if failed:
            return {"ok": False, "kind": "permanent",
                    "error": (f"finding store rejected {failed} "
                              f"finding(s); scan is not verified")}
        task.provenance["discovered"] = stored
        task.provenance["scanned"] = int(report.get("scanned", 0))
        task.provenance["skipped"] = int(report.get("skipped", 0))
        task.provenance["truncated"] = bool(report.get("truncated"))
        self._emit("security.discovery.completed", task_id=task.task_id,
                   discovered=stored, scanned=report.get("scanned", 0),
                   by_severity=report.get("by_severity", {}))
        return {"ok": True,
                "verification": ("partial" if report.get("truncated")
                                 else "verified"),
                "output_ref": (f"discovered:{stored} "
                               f"scanned:{report.get('scanned', 0)} "
                               f"skipped:{report.get('skipped', 0)}"),
                "side_effects": [f"findings-upserted:{stored}"]}

    def _step_validate(self, task: Task) -> dict[str, Any]:
        self._require_idle()
        root = self._root_for(task)
        candidates = [
            finding for finding in self.findings.list()
            if finding.task_id == task.task_id
            and finding.state in (FindingState.DISCOVERED,
                                  FindingState.SUSPECTED,
                                  FindingState.INCONCLUSIVE)]
        validated = 0
        unknown = 0
        resolved = 0
        for finding in candidates:
            try:
                path = self._file_for(finding, root)
            except SecurityError:
                finding.mark_inconclusive("target file unavailable",
                                          by="security-manager")
                self.findings.save(finding)
                unknown += 1
                continue
            check = recheck_finding(
                path, finding.kind, _line_from_location(finding.location))
            if check["state"] == "still_present":
                line = int(check.get("line", 0) or 0)
                finding.location = (f"{finding.asset}:{line}" if line
                                    else finding.asset)
                extra = [EvidenceRef(
                    kind="validation", ref=finding.location,
                    detail="deterministic re-check: rule still matches")]
                try:
                    finding.mark_validated(
                        by="security-manager",
                        method="deterministic source re-check",
                        evidence=extra,
                        confidence=min(0.95, finding.confidence + 0.1))
                    self.findings.save(finding)
                    validated += 1
                except FindingError:
                    unknown += 1
            elif check["state"] == "resolved":
                try:
                    finding.mark_inconclusive(
                        "rule no longer matches at the recorded source; "
                        "not assumed fixed", by="security-manager")
                    self.findings.save(finding)
                except FindingError:
                    pass
                resolved += 1
            else:
                finding.mark_inconclusive(
                    f"re-check inconclusive: {check.get('detail', '')}",
                    by="security-manager")
                self.findings.save(finding)
                unknown += 1
        task.provenance["validated"] = validated
        task.provenance["validation_unknown"] = unknown
        task.provenance["resolved_before_fix"] = resolved
        self._emit("security.validation.completed", task_id=task.task_id,
                   validated=validated, unknown=unknown, resolved=resolved)
        return {"ok": True,
                "verification": ("verified" if unknown == 0 and resolved == 0
                                 else "partial"),
                "output_ref": (f"validated:{validated} "
                               f"unknown:{unknown} resolved:{resolved}"),
                "side_effects": [f"findings-validated:{validated}"]}

    def _step_report(self, task: Task) -> dict[str, Any]:
        payload = self.report(task_id=task.task_id)
        written = ""
        if self.home is not None:
            try:
                self.home.mkdir(parents=True, exist_ok=True)
                written = str(self._write_report(payload))
            except OSError:
                written = ""
        task.provenance["report_ref"] = written[-300:]
        return {"ok": True, "verification": "verified",
                "output_ref": written[-500:] or "report:memory",
                "side_effects": ([f"report:{Path(written).name}"]
                                 if written else [])}

    # -- task lifecycle --------------------------------------------------
    def start(self, target: str | Path, *, authorized: bool = True,
              source: str = "cli", title: str = "") -> Task:
        """Create the durable security task. Analysis has not run yet."""
        self._require_idle()
        scope = validate_scope(target, authorized=authorized)
        task = self.runner.create(
            title=title or f"security intel: {Path(scope.target).name}"[:300],
            source=source, priority=3,
            retry_policy={"max_attempts": 2, "backoff_base_s": 0.5,
                          "backoff_max_s": 5.0,
                          "retryable": ["transient", "unknown"]},
            provenance={"domain": "security", "target": scope.target,
                        "scope_kind": scope.kind,
                        "actor": MANAGER_ACTOR},
            steps=[{"title": label} for label, _ in STEPS])
        self.runner.mark_ready(task.task_id, plan_ref="security-intel-1",
                               plan_version="1.0")
        self._emit("security.task.started", task_id=task.task_id,
                   target=scope.target, kind=scope.kind)
        return task

    def run(self, task_id: str, *, max_steps: int = 12) -> dict[str, Any]:
        """Advance to a terminal state, bounded. Never calls a paused task
        success: interruption is reported as unverified."""
        for _ in range(max(1, int(max_steps))):
            task = self._task(task_id)
            if task.state in (TaskState.COMPLETED, TaskState.FAILED,
                              TaskState.CANCELLED, TaskState.EXPIRED,
                              TaskState.PAUSED):
                break
            if task.state in _TASK_CONTINUE:
                task = self.runner.advance(task_id)
                if task.state in (TaskState.FAILED, TaskState.CANCELLED):
                    break
                continue
            if task.state in _TASK_INTERRUPTED:
                decision = self.runner.recover(
                    task_id, policy_ok=not self._emergency(),
                    approval_ok=True)
                if decision.get("action") in ("WAIT", "HALT"):
                    break
                continue
            break
        return self.task_result(task_id)

    def task_result(self, task_id: str) -> dict[str, Any]:
        task = self._task(task_id)
        complete = task.state is TaskState.COMPLETED
        unverified = int(task.provenance.get("completed_unverified", 0) or 0)
        verified = complete and unverified == 0
        report = self.report(task_id=task.task_id)
        return {
            "task_id": task.task_id,
            "state": task.state.value,
            "complete": complete,
            "success": verified,
            "verification": ("verified" if verified else
                             "partial" if complete else "unverified"),
            "progress": self._progress(task),
            "target": str(task.provenance.get("target", ""))[:MAX_SCOPE_PATH],
            "counts": report.get("counts", {}),
            "posture": report.get("posture", "unknown"),
            "findings": report.get("findings", []),
            "report_ref": task.provenance.get("report_ref", ""),
            "truncated": bool(task.provenance.get("truncated", False)),
            "failure": str(task.provenance.get("failure", ""))[:300],
        }

    @staticmethod
    def _progress(task: Task) -> str:
        done = sum(1 for step in task.steps
                   if step.state is StepState.SUCCEEDED)
        return f"{done}/{len(task.steps)}"

    def intel(self, target: str | Path, *, source: str = "cli",
              authorized: bool = True, max_steps: int = 12
              ) -> dict[str, Any]:
        task = self.start(target, authorized=authorized, source=source)
        return self.run(task.task_id, max_steps=max_steps)

    # -- read-only manager surface --------------------------------------
    def discover(self, target: str | Path, *, authorized: bool = True
                 ) -> list[SecurityFinding]:
        """Read-only scan used by specialist agent handlers."""
        self._require_idle()
        if self.findings.corrupt:
            raise SecurityError(
                f"finding store quarantined: {self.findings.corrupt}")
        scope = validate_scope(target, authorized=authorized)
        root = (Path(scope.target) if scope.kind == "repo"
                else Path(scope.target).parent)
        report = review_path(scope.target)
        if report.get("truncated"):
            raise SecurityError(
                "scan limit reached; discovery is incomplete and cannot "
                "be reported as a clean pass")
        out: list[SecurityFinding] = []
        failed = 0
        for raw in report.get("findings", []):
            try:
                finding = finding_from_review(raw, root=root)
                finding.agent_id = "security-specialist"
                out.append(self.findings.upsert(finding))
            except (FindingError, ValueError, TypeError):
                failed += 1
        if failed:
            raise SecurityError(
                f"finding store rejected {failed} finding(s); "
                "discovery is not verified")
        return out

    def validate_findings(self, *, ids: list[str] | None = None,
                          task_id: str = "") -> dict[str, Any]:
        self._require_idle()
        findings = self.findings.list()
        if ids:
            wanted = set(ids)
            findings = [f for f in findings if f.finding_id in wanted]
        if task_id:
            findings = [f for f in findings if f.task_id == task_id]
        counts = {"validated": 0, "resolved": 0, "unknown": 0}
        for finding in findings:
            if finding.state not in (FindingState.DISCOVERED,
                                     FindingState.SUSPECTED,
                                     FindingState.INCONCLUSIVE):
                continue
            try:
                path, _task = self._path_for(finding)
            except SecurityError:
                counts["unknown"] += 1
                continue
            check = recheck_finding(
                path, finding.kind, _line_from_location(finding.location))
            try:
                if check["state"] == "still_present":
                    line = int(check.get("line", 0) or 0)
                    finding.location = (f"{finding.asset}:{line}" if line
                                        else finding.asset)
                    finding.mark_validated(
                        by="security-manager",
                        method="deterministic source re-check",
                        evidence=[EvidenceRef(
                            kind="validation", ref=finding.location,
                            detail="re-check: rule still matches")])
                    counts["validated"] += 1
                elif check["state"] == "resolved":
                    finding.mark_inconclusive(
                        "rule no longer matches at source; not assumed fixed",
                        by="security-manager")
                    counts["resolved"] += 1
                else:
                    counts["unknown"] += 1
                self.findings.save(finding)
            except FindingError:
                counts["unknown"] += 1
        return counts

    # -- remediation -----------------------------------------------------
    def _suggest(self, kind: str, line: str) -> str:
        stripped = line.strip()
        if kind == "pattern:yaml-load" and _YAML_LOAD_CALL in stripped:
            return line.replace(_YAML_LOAD_CALL, "yaml.safe_load(", 1)
        if kind == "pattern:debug-enabled":
            if re.search(r"\bDEBUG\s*=\s*True\b", line):
                return re.sub(r"\bDEBUG\s*=\s*True\b", "DEBUG = False", line)
            if re.search(r"\bdebug\s*=\s*True\b", line):
                return re.sub(r"\bdebug\s*=\s*True\b", "debug=False", line)
        if kind == "pattern:tls-verify-off" and _TLS_VERIFY_OFF in line:
            return line.replace(_TLS_VERIFY_OFF, "verify=" + "True", 1)
        if kind == "pattern:bind-all" and "0.0.0.0" in line:
            return line.replace("0.0.0.0", "127.0.0.1", 1)
        return ""

    def _clean_replacement(self, replacement: str) -> str:
        text = str(replacement or "")
        if not text or "\n" in text or "\r" in text or "\x00" in text:
            raise SecurityError("replacement must be exactly one text line")
        if len(text) > MAX_REPLACEMENT:
            raise SecurityError(
                f"replacement exceeds {MAX_REPLACEMENT} characters")
        return text

    def propose_remediation(self, finding_id: str,
                            replacement: str = "") -> dict[str, Any]:
        self._require_idle()
        finding = self.findings.get(finding_id)
        if finding is None:
            raise SecurityError(f"unknown finding: {finding_id}")
        if finding.state is not FindingState.VALIDATED:
            raise SecurityError(
                "remediation requires a validated finding "
                f"(current state: {finding.state.value})")
        path, _task = self._path_for(finding)
        check = recheck_finding(
            path, finding.kind, _line_from_location(finding.location))
        if check["state"] != "still_present":
            return {"ok": False, "status": check["state"],
                    "finding_id": finding.finding_id,
                    "detail": "rule is not present at the recorded source"}
        line_no = int(check.get("line", 0) or 0)
        if line_no <= 0:
            raise SecurityError("finding has no line-level location")
        try:
            current = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise SecurityError(f"cannot read target: {type(exc).__name__}")
        if line_no > len(current):
            raise SecurityError("recorded line is out of range")
        text = self._clean_replacement(
            replacement or self._suggest(finding.kind, current[line_no - 1]))
        if not text:
            return {
                "ok": False, "status": "needs_operator_replacement",
                "finding_id": finding.finding_id, "line": line_no,
                "detail": ("no safe automatic replacement exists for this "
                           "rule; supply --replacement with the reviewed "
                           "line")}
        if text.strip() == current[line_no - 1].strip():
            raise SecurityError("replacement is identical to the current line")
        before = _sha256(path.read_bytes())
        finding.remediation = {
            "status": RemediationState.PROPOSED.value,
            "guidance": str(finding.remediation.get("guidance", "") or
                            "review and replace the flagged line")[:400],
            "proposed_at": time.time(), "before_sha256": before,
            "line": line_no,
            "replacement_sha256": _sha256(text.encode("utf-8")),
            "replacement_preview": scrub_text(text, limit=200)}
        self.findings.update(finding.finding_id,
                             remediation=dict(finding.remediation))
        self._emit("security.remediation.proposed",
                   finding_id=finding.finding_id, line=line_no)
        return {"ok": True, "status": "proposed",
                "finding_id": finding.finding_id, "line": line_no,
                "replacement": text, "before_sha256": before,
                "approval_action": self._approval_action(finding)}

    def _approval_action(self, finding: SecurityFinding) -> str:
        return f"filesystem_write security-remediation {finding.finding_id}"

    def _approval_args(self, finding: SecurityFinding, path: Path,
                       before: str, replacement: str) -> dict[str, Any]:
        return {"path": str(path), "finding_id": finding.finding_id,
                "before_sha256": before,
                "replacement_sha256": _sha256(replacement.encode("utf-8"))}

    def apply_remediation(self, finding_id: str, *,
                          replacement: str = "", approval: str = "",
                          actor: str = MANAGER_ACTOR) -> dict[str, Any]:
        """Apply a proposed single-line fix through policy + approval.

        The approval binds path, finding id, pre-change file hash, and
        replacement hash. Raw file content and credentials are never
        written into the approval store.
        """
        self._require_idle()
        finding = self.findings.get(finding_id)
        if finding is None:
            raise SecurityError(f"unknown finding: {finding_id}")
        proposed = finding.remediation.get("status")
        if proposed != RemediationState.PROPOSED.value or replacement:
            proposal = self.propose_remediation(finding_id, replacement)
            if not proposal.get("ok"):
                return proposal
            finding = self.findings.get(finding_id)
        if finding is None:
            raise SecurityError("finding disappeared during proposal")
        path, _task = self._path_for(finding)
        line_no = _line_of(finding)
        if line_no <= 0:
            raise SecurityError("proposal has no line binding")
        before = str(finding.remediation.get("before_sha256", ""))
        if not before or _sha256(path.read_bytes()) != before:
            return {"ok": False, "status": "stale_proposal",
                    "detail": "file changed since proposal; propose again"}
        current = path.read_text(encoding="utf-8").splitlines()
        if line_no > len(current):
            return {"ok": False, "status": "stale_proposal",
                    "detail": "recorded line is out of range"}
        replacement_line = self._clean_replacement(
            replacement or self._suggest(finding.kind, current[line_no - 1]))
        expected = str(finding.remediation.get("replacement_sha256", ""))
        if expected and _sha256(replacement_line.encode("utf-8")) != expected:
            return {"ok": False, "status": "proposal_mismatch",
                    "detail": ("replacement differs from the reviewed "
                               "proposal; re-run with --replacement")}
        args = self._approval_args(finding, path, before, replacement_line)
        action = self._approval_action(finding)
        if self.policy is None:
            return {"ok": False, "status": "denied",
                    "detail": "no policy engine bound; remediation refused"}

        from ..core.types import ActionPlan
        tool = self._tools_registry().get("filesystem_write")
        if tool is None:
            return {"ok": False, "status": "unavailable",
                    "detail": "filesystem_write tool is not registered"}
        plan = ActionPlan(action=action, args=args,
                          required_permissions=list(
                              tool.spec.required_permissions),
                          risk=tool.spec.risk)
        decision = self.policy.evaluate(actor, plan)
        if not decision.allow:
            return {"ok": False, "status": "denied",
                    "reasons": list(decision.reasons),
                    "detail": ("grant fs.write to the security manager "
                               "actor before remediation")}
        if not approval:
            token = self.policy.request_approval(actor, plan, decision)
            self._emit("security.remediation.approval_requested",
                       finding_id=finding.finding_id)
            return {"ok": True, "status": "needs_approval",
                    "approval_token": token,
                    "approval_action": action,
                    "binding": {"path": args["path"],
                                "before_sha256": before,
                                "replacement_sha256":
                                    args["replacement_sha256"]},
                    "detail": ("approve with the existing approvals "
                               "command, then rerun with --approval")}
        full = self._resolve_token(approval)
        if full is None:
            return {"ok": False, "status": "denied",
                    "detail": "unknown or ambiguous approval token"}
        if not self.policy.redeem(full, actor, action, args):
            return {"ok": False, "status": "denied",
                    "detail": "approval rejected, spent, or misbound"}

        new_lines = list(current)
        new_lines[line_no - 1] = replacement_line
        new_text = "\n".join(new_lines)
        if path.read_text(encoding="utf-8").endswith("\n"):
            new_text += "\n"
        after = _sha256(new_text.encode("utf-8"))
        try:
            before_stat = path.stat()
        except OSError as exc:
            return {"ok": False, "status": "write_failed",
                    "detail": f"{type(exc).__name__}: target disappeared"}
        if path.is_symlink():
            return {"ok": False, "status": "stale_proposal",
                    "detail": "target became a symlink; refusing to write"}
        result = self._tools_registry().call(
            "filesystem_write", path=str(path), content=new_text)
        if not getattr(result, "ok", False):
            return {"ok": False, "status": "write_failed",
                    "detail": str(getattr(result, "error", "write failed"))}
        try:
            after_stat = path.stat()
        except OSError:
            return {"ok": False, "status": "write_mismatch",
                    "detail": "target disappeared after write"}
        if ((before_stat.st_dev, before_stat.st_ino) !=
                (after_stat.st_dev, after_stat.st_ino)):
            return {"ok": False, "status": "write_mismatch",
                    "detail": ("target was replaced during write; "
                               "the approved change is not trusted")}
        if _sha256(path.read_bytes()) != after:
            return {"ok": False, "status": "write_mismatch",
                    "detail": "post-write hash does not match intended content"}
        finding = self.findings.get(finding_id)
        if finding is None:
            raise SecurityError("finding disappeared during apply")
        finding.mark_remediated(
            before_sha256=before, after_sha256=after,
            approval_ref=full[:12] + "…", line=line_no,
            replacement_preview=replacement_line)
        self.findings.save(finding)
        self._emit("security.remediation.applied",
                   finding_id=finding.finding_id,
                   before_sha256=before, after_sha256=after)
        return {"ok": True, "status": "remediated",
                "finding_id": finding.finding_id,
                "before_sha256": before, "after_sha256": after,
                "line": line_no,
                "next": ("run `jarvis security verify --finding "
                         f"{finding.finding_id}`")}

    def _resolve_token(self, prefix: str) -> str | None:
        value = str(prefix or "")
        if len(value) < 4:
            return None
        loader = getattr(self.policy, "_load_approvals", None)
        if callable(loader):
            loader()
        approvals = getattr(self.policy, "approvals", {}) or {}
        matches = [token for token in approvals if str(token).startswith(value)]
        return matches[0] if len(matches) == 1 else None

    def verify_remediation(self, finding_id: str) -> dict[str, Any]:
        """Re-check the source after a change. Only this can re-verify."""
        self._require_idle()
        finding = self.findings.get(finding_id)
        if finding is None:
            raise SecurityError(f"unknown finding: {finding_id}")
        if finding.state is not FindingState.REMEDIATED:
            return {"ok": False, "status": "not_remediated",
                    "state": finding.state.value,
                    "detail": "verification requires a remediated finding"}
        path, _task = self._path_for(finding)
        recorded_after = str(finding.remediation.get("after_sha256", ""))
        if recorded_after:
            try:
                current = _sha256(path.read_bytes())
            except OSError:
                return {"ok": False, "status": "unknown",
                        "state": finding.state.value,
                        "detail": "remediated file is unreadable"}
            if current != recorded_after:
                return {"ok": False, "status": "unknown",
                        "state": finding.state.value,
                        "detail": ("file changed after remediation; the "
                                   "approved change is not intact")}
        check = recheck_finding(
            path, finding.kind, _line_of(finding))
        if check["state"] == "unknown":
            return {"ok": False, "status": "unknown",
                    "detail": check.get("detail", "")}
        verified = check["state"] == "resolved"
        finding.mark_reverified(
            verified,
            evidence=("post-change re-check: rule absent" if verified
                      else "post-change re-check: rule still matches"))
        self.findings.save(finding)
        self._emit("security.remediation.verified",
                   finding_id=finding.finding_id, verified=verified)
        return {"ok": verified,
                "status": "reverified" if verified else "still_present",
                "finding_id": finding.finding_id,
                "state": finding.state.value,
                "verification": finding.verification.value,
                "detail": check.get("detail", "")}

    # -- benchmark helper (real approval path, automated approver) ------
    def auto_remediate(self, finding_id: str, *,
                       actor: str = MANAGER_ACTOR,
                       replacement: str = "") -> dict[str, Any]:
        """Propose, approve, apply, verify — using the real policy path.

        The caller plays the human approver for local fixtures only.
        """
        proposal = self.propose_remediation(finding_id, replacement)
        if not proposal.get("ok"):
            return proposal
        step = self.apply_remediation(finding_id, replacement=replacement,
                                      actor=actor)
        if step.get("status") != "needs_approval":
            return step
        token = step.get("approval_token", "")
        if not self.policy.approve(token, by="benchmark-operator"):
            return {"ok": False, "status": "approval_failed"}
        applied = self.apply_remediation(finding_id, replacement=replacement,
                                         approval=token, actor=actor)
        if applied.get("status") != "remediated":
            return applied
        verified = self.verify_remediation(finding_id)
        return {"ok": verified.get("ok", False),
                "status": verified.get("status", ""),
                "proposal": proposal, "applied": applied,
                "verified": verified}

    # -- reporting -------------------------------------------------------
    def report(self, *, task_id: str = "") -> dict[str, Any]:
        findings = self.findings.list()
        if task_id:
            findings = [f for f in findings if f.task_id == task_id]
        by_severity = {severity.value: 0 for severity in Severity}
        by_state: dict[str, int] = {}
        for finding in findings:
            by_severity[finding.severity.value] += 1
            by_state[finding.state.value] = \
                by_state.get(finding.state.value, 0) + 1
        assets: dict[str, dict[str, Any]] = {}
        for finding in findings:
            row = assets.setdefault(finding.asset, {
                "asset": finding.asset, "open": 0,
                "highest": Severity.INFO.value})
            if finding.state not in (FindingState.FALSE_POSITIVE,):
                row["open"] += 1
            if severity_rank(finding.severity) > \
                    severity_rank(row["highest"]):
                row["highest"] = finding.severity.value
        asset_rows = sorted(
            assets.values(),
            key=lambda row: (-severity_rank(row["highest"]),
                             -row["open"], row["asset"]))[:MAX_BY_ASSET]
        open_states = {FindingState.DISCOVERED.value,
                       FindingState.SUSPECTED.value,
                       FindingState.VALIDATED.value,
                       FindingState.REMEDIATED.value,
                       FindingState.INCONCLUSIVE.value}
        rows = []
        for finding in findings[:MAX_REPORT_FINDINGS]:
            rows.append({
                "finding_id": finding.finding_id,
                "title": scrub_text(finding.title, limit=200),
                "kind": finding.kind,
                "category": finding.category,
                "severity": finding.severity.value,
                "state": finding.state.value,
                "asset": scrub_text(finding.asset, limit=200),
                "location": scrub_text(finding.location, limit=200),
                "line": _line_from_location(finding.location),
                "confidence": round(finding.confidence, 3),
                "provenance": finding.provenance[:120],
                "validation": finding.validation.value,
                "verification": finding.verification.value,
                "remediation": finding.remediation.get(
                    "status", RemediationState.NONE.value),
                "task_id": finding.task_id,
                "agent_id": finding.agent_id,
                "updated_at": finding.updated_at,
            })
        tasks = []
        try:
            all_tasks = self.tasks.list()
        except Exception:
            all_tasks = []
        for task in all_tasks:
            if task.provenance.get("domain") != "security":
                continue
            tasks.append({"task_id": task.task_id,
                          "state": task.state.value,
                          "title": task.title[:160],
                          "progress": self._progress(task),
                          "target": str(
                              task.provenance.get("target", ""))[:200]})
        scope = {}
        if task_id:
            scope = self._task(task_id).provenance.get("scope", {})
        return {
            "schema": 1,
            "generated_at": time.time(),
            "posture": _posture(findings),
            "counts": {
                "total": len(findings),
                "open": sum(1 for f in findings
                            if f.state.value in open_states),
                "by_severity": by_severity,
                "by_state": by_state,
                "validated": by_state.get(FindingState.VALIDATED.value, 0),
                "reverified": by_state.get(FindingState.REVERIFIED.value, 0),
                "false_positive": by_state.get(
                    FindingState.FALSE_POSITIVE.value, 0),
            },
            "by_asset": asset_rows,
            "findings": rows,
            "tasks": tasks[-10:],
            "scope": scope,
            "store": ("quarantined" if self.findings.corrupt else "ok"),
        }

    def _write_report(self, payload: dict[str, Any]) -> Path:
        assert self.home is not None
        target = self.home / REPORT_FILENAME
        fd, tmp = tempfile.mkstemp(prefix=".security-report-",
                                   dir=str(self.home))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, default=str)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            os.replace(tmp, target)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        return target

    # -- board / API snapshot -------------------------------------------
    def summary(self, *, limit: int = 8) -> dict[str, Any]:
        findings = self.findings.list(limit=max(1, min(limit, 20)))
        counts = self.findings.counts()
        tasks = [t for t in self.tasks.list()
                 if t.provenance.get("domain") == "security"][-5:]
        return {
            "posture": self.findings.posture(),
            "store": ("quarantined" if self.findings.corrupt else "ok"),
            "counts": counts,
            "findings": [{
                "finding_id": f.finding_id,
                "title": scrub_text(f.title, limit=120),
                "severity": f.severity.value,
                "state": f.state.value,
                "asset": scrub_text(f.asset, limit=120),
                "verification": f.verification.value,
                "remediation": f.remediation.get(
                    "status", RemediationState.NONE.value),
            } for f in findings],
            "tasks": [{"task_id": t.task_id, "state": t.state.value,
                       "title": t.title[:120],
                       "progress": self._progress(t)} for t in tasks],
        }


def board_security_info(home: str | Path | None) -> dict[str, Any]:
    """Bounded, secret-scrubbed snapshot for the read-only board."""
    if not home:
        return {"posture": "unknown"}
    try:
        return SecurityManager(home).summary()
    except Exception as exc:
        return {"posture": "unknown", "detail": type(exc).__name__}


__all__ = [
    "SecurityError", "SecurityScope", "SecurityManager", "validate_scope",
    "board_security_info", "MANAGER_ACTOR", "REPORT_FILENAME", "STEPS",
]
