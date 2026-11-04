"""Security finding contracts and durable finding store.

One finding shape for every security surface: static review, audit tools,
Strix evidence, and the security manager. A finding is a *lead with
evidence*, never proof of exploitability; `validated` means the evidence
was re-checked, not that the issue is exploitable.

Rules:
- Every field is bounded and validated; malformed findings fail closed.
- Secret-shaped values are redacted before they enter a finding.
- State transitions are explicit. A patch proposal never marks a finding
  fixed; only a post-change re-check can move it to `reverified`.
- The store is atomic and quarantines corrupt state instead of parsing it
  into authority.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = 1
STORE_FILENAME = "security-findings.json"
MAX_FINDINGS = 1000
MAX_TEXT = 600
MAX_TITLE = 200
MAX_EVIDENCE = 8
MAX_HISTORY = 20
MAX_ASSET = 500
MAX_LOCATION = 200
MAX_ID = 80


class FindingError(ValueError):
    """Malformed finding data or an illegal state transition."""


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"
    UNKNOWN = "unknown"


class FindingState(str, Enum):
    DISCOVERED = "discovered"
    SUSPECTED = "suspected"
    VALIDATED = "validated"
    REMEDIATED = "remediated"
    REVERIFIED = "reverified"
    FALSE_POSITIVE = "false_positive"
    INCONCLUSIVE = "inconclusive"


class ValidationState(str, Enum):
    UNVALIDATED = "unvalidated"
    VALIDATED = "validated"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"


class ReproductionState(str, Enum):
    NOT_ATTEMPTED = "not_attempted"
    REPRODUCED = "reproduced"
    NOT_REPRODUCED = "not_reproduced"
    INCONCLUSIVE = "inconclusive"


class VerificationState(str, Enum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"


class RemediationState(str, Enum):
    NONE = "none"
    PROPOSED = "proposed"
    APPLIED = "applied"
    VERIFIED = "verified"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


ALLOWED_TRANSITIONS: dict[FindingState, frozenset[FindingState]] = {
    FindingState.DISCOVERED: frozenset({
        FindingState.SUSPECTED, FindingState.VALIDATED,
        FindingState.FALSE_POSITIVE, FindingState.INCONCLUSIVE}),
    FindingState.SUSPECTED: frozenset({
        FindingState.VALIDATED, FindingState.FALSE_POSITIVE,
        FindingState.INCONCLUSIVE}),
    FindingState.VALIDATED: frozenset({
        FindingState.REMEDIATED, FindingState.FALSE_POSITIVE,
        FindingState.INCONCLUSIVE}),
    # A regression may reopen a remediated finding with fresh evidence.
    FindingState.REMEDIATED: frozenset({
        FindingState.REVERIFIED, FindingState.INCONCLUSIVE,
        FindingState.VALIDATED}),
    # A regression may reopen a re-verified finding with fresh evidence.
    FindingState.REVERIFIED: frozenset({FindingState.VALIDATED}),
    FindingState.FALSE_POSITIVE: frozenset(),
    FindingState.INCONCLUSIVE: frozenset({
        FindingState.SUSPECTED, FindingState.VALIDATED,
        FindingState.FALSE_POSITIVE}),
}

_SEVERITY_RANK = {
    Severity.CRITICAL: 5, Severity.HIGH: 4, Severity.MEDIUM: 3,
    Severity.LOW: 2, Severity.INFO: 1, Severity.UNKNOWN: 0,
}

_SECRET_ASSIGN_RE = re.compile(
    r"(?i)\b(password|passwd|secret|token|api[_-]?key|apikey|"
    r"authorization|passphrase)\b(\s*[:=]\s*)([^\s,;]+)")
_BEARER_RE = re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]+")
_URL_USERINFO_RE = re.compile(r"(?i)\b(https?://)[^/@\s]+@")


def scrub_text(value: Any, *, limit: int = MAX_TEXT) -> str:
    """Redact credential-shaped spans and bound the text."""
    text = str(value if value is not None else "")
    try:
        from ..perception.contract import redact_secret_spans
        text, _ = redact_secret_spans(text)
    except Exception:
        pass
    text = _SECRET_ASSIGN_RE.sub(
        lambda m: f"{m.group(1)}{m.group(2)}[redacted]", text)
    text = _BEARER_RE.sub(lambda m: f"{m.group(1)}[redacted]", text)
    text = _URL_USERINFO_RE.sub(lambda m: f"{m.group(1)}[redacted]@", text)
    if len(text) > limit:
        text = text[:limit] + "…[truncated]"
    return text


def _value(value: Any) -> str:
    return value.value if isinstance(value, Enum) else str(value)


def severity_rank(value: Severity | str) -> int:
    try:
        return _SEVERITY_RANK[Severity(_value(value))]
    except ValueError:
        raise FindingError(f"bad severity: {value!r}")


def make_finding_id(asset: str, kind: str, location: str, *,
                    root: str = "") -> str:
    """Stable ID: same rule/location under the same authorized root.

    The root is part of the identity so identical relative paths in two
    repositories cannot overwrite or rebind each other's findings.
    """
    raw = "|".join((str(asset), str(kind), str(location), str(root)))
    return "sec-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


@dataclass(frozen=True)
class EvidenceRef:
    kind: str = "file"
    ref: str = ""
    detail: str = ""
    digest: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", str(self.kind or "file")[:40])
        object.__setattr__(self, "ref", scrub_text(self.ref, limit=300))
        object.__setattr__(self, "detail", scrub_text(self.detail))
        if not self.digest:
            digest = hashlib.sha256(
                self.detail.encode("utf-8")).hexdigest()[:16]
            object.__setattr__(self, "digest", digest)
        else:
            object.__setattr__(self, "digest", str(self.digest)[:32])

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "ref": self.ref,
                "detail": self.detail, "digest": self.digest}


def _timestamps(data: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for key in ("created_at", "updated_at", "validated_at",
                "remediated_at", "verified_at"):
        try:
            value = float(data.get(key, 0.0) or 0.0)
        except (TypeError, ValueError):
            raise FindingError(f"bad timestamp: {key}")
        if value < 0:
            raise FindingError(f"negative timestamp: {key}")
        out[key] = value
    return out


@dataclass
class SecurityFinding:
    finding_id: str = ""
    schema_version: int = SCHEMA_VERSION
    title: str = ""
    category: str = "code"
    severity: Severity = Severity.MEDIUM
    asset: str = ""
    location: str = ""
    kind: str = ""
    evidence: list[EvidenceRef] = field(default_factory=list)
    confidence: float = 0.5
    provenance: str = "static-review"
    state: FindingState = FindingState.DISCOVERED
    validation: ValidationState = ValidationState.UNVALIDATED
    reproduction: ReproductionState = ReproductionState.NOT_ATTEMPTED
    verification: VerificationState = VerificationState.UNVERIFIED
    remediation: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    validated_at: float = 0.0
    remediated_at: float = 0.0
    verified_at: float = 0.0
    task_id: str = ""
    agent_id: str = ""
    trace_id: str = ""
    history: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if int(self.schema_version) != SCHEMA_VERSION:
            raise FindingError(
                f"unsupported finding schema: {self.schema_version}")
        self.title = scrub_text(self.title, limit=MAX_TITLE)
        self.category = str(self.category or "code")[:40]
        self.asset = scrub_text(self.asset, limit=MAX_ASSET)
        self.location = scrub_text(self.location, limit=MAX_LOCATION)
        self.kind = str(self.kind or "heuristic")[:80]
        self.provenance = str(self.provenance or "static-review")[:200]
        self.task_id = str(self.task_id or "")[:MAX_ID]
        self.agent_id = str(self.agent_id or "")[:MAX_ID]
        self.trace_id = str(self.trace_id or "")[:MAX_ID]
        try:
            self.severity = Severity(_value(self.severity))
            self.state = FindingState(_value(self.state))
            self.validation = ValidationState(_value(self.validation))
            self.reproduction = ReproductionState(_value(self.reproduction))
            self.verification = VerificationState(
                _value(self.verification))
        except ValueError as exc:
            raise FindingError(str(exc)) from exc
        try:
            self.confidence = float(self.confidence)
        except (TypeError, ValueError) as exc:
            raise FindingError("confidence must be numeric") from exc
        if not 0.0 <= self.confidence <= 1.0:
            raise FindingError("confidence out of range 0..1")
        if not self.title:
            self.title = self.kind
        refs: list[EvidenceRef] = []
        for item in list(self.evidence or [])[:MAX_EVIDENCE]:
            if isinstance(item, EvidenceRef):
                refs.append(item)
            elif isinstance(item, dict):
                refs.append(EvidenceRef(**{
                    k: item.get(k, "") for k in
                    ("kind", "ref", "detail", "digest")}))
            else:
                refs.append(EvidenceRef(detail=str(item)))
        self.evidence = refs
        self._clean_remediation()
        now = time.time()
        self.created_at = float(self.created_at or now)
        self.updated_at = float(self.updated_at or self.created_at)
        if not self.history:
            self.history = [{"state": self.state.value,
                             "at": self.created_at, "by": "ingest",
                             "reason": "initial state"}]
        clean_history = []
        for item in list(self.history)[-MAX_HISTORY:]:
            if not isinstance(item, dict):
                continue
            clean_history.append({
                "state": str(item.get("state", ""))[:40],
                "at": float(item.get("at", 0.0) or 0.0),
                "by": scrub_text(item.get("by", ""), limit=80),
                "reason": scrub_text(item.get("reason", ""), limit=200)})
        self.history = clean_history
        if not self.finding_id:
            self.finding_id = make_finding_id(
                self.asset, self.kind, self.location)
        self.finding_id = str(self.finding_id)[:MAX_ID]
        if not self.finding_id.startswith("sec-"):
            raise FindingError("finding_id must start with 'sec-'")

    def _clean_remediation(self) -> None:
        raw = dict(self.remediation or {})
        keep = ("status", "guidance", "proposed_at", "applied_at",
                "verified_at", "before_sha256", "after_sha256",
                "replacement_sha256", "approval_ref", "patch_ref", "line",
                "replacement_preview")
        clean: dict[str, Any] = {}
        for key in keep:
            if key not in raw:
                continue
            value = raw[key]
            if key in ("status", "before_sha256", "after_sha256",
                       "replacement_sha256", "approval_ref", "patch_ref"):
                clean[key] = str(value or "")[:80]
            elif key in ("proposed_at", "applied_at", "verified_at"):
                clean[key] = float(value or 0.0)
            elif key == "line":
                clean[key] = max(0, int(value or 0))
            else:
                clean[key] = scrub_text(value, limit=400)
        status = clean.get("status", "none")
        try:
            clean["status"] = RemediationState(_value(status)).value
        except ValueError:
            clean["status"] = RemediationState.UNKNOWN.value
        self.remediation = clean

    def transition(self, to: FindingState | str, *,
                   by: str = "manager", reason: str = "") -> None:
        target = (to if isinstance(to, FindingState)
                  else FindingState(_value(to)))
        if target == self.state:
            return
        if target not in ALLOWED_TRANSITIONS.get(self.state, frozenset()):
            raise FindingError(
                f"illegal finding transition {self.state.value}"
                f"->{target.value}")
        if target is FindingState.REMEDIATED:
            if self.validation is not ValidationState.VALIDATED:
                raise FindingError(
                    "cannot remediate an unvalidated finding")
            if self.remediation.get("status") != RemediationState.APPLIED.value:
                raise FindingError(
                    "cannot remediate without an applied change")
        if target is FindingState.REVERIFIED:
            if self.verification is not VerificationState.VERIFIED:
                raise FindingError(
                    "cannot re-verify without a verified re-check")
        stamp = time.time()
        self.state = target
        self.updated_at = stamp
        if target is FindingState.VALIDATED:
            self.validated_at = stamp
        elif target is FindingState.REMEDIATED:
            self.remediated_at = stamp
        elif target is FindingState.REVERIFIED:
            self.verified_at = stamp
        self.history.append({"state": target.value, "at": stamp,
                             "by": scrub_text(by, limit=80),
                             "reason": scrub_text(reason, limit=200)})
        self.history = self.history[-MAX_HISTORY:]

    def mark_validated(self, *, by: str = "re-scan",
                       method: str = "re-scan",
                       evidence: Iterable[EvidenceRef | dict] = (),
                       confidence: float | None = None) -> None:
        if evidence:
            extra = list(evidence)
            for item in extra:
                if isinstance(item, dict):
                    item = EvidenceRef(**{
                        k: item.get(k, "") for k in
                        ("kind", "ref", "detail", "digest")})
                if len(self.evidence) < MAX_EVIDENCE:
                    self.evidence.append(item)
        self.validation = ValidationState.VALIDATED
        if confidence is not None:
            try:
                self.confidence = max(0.0, min(1.0, float(confidence)))
            except (TypeError, ValueError):
                raise FindingError("confidence must be numeric")
        self.transition(FindingState.VALIDATED, by=by,
                        reason=f"validated by {method}")

    def mark_false_positive(self, reason: str, *,
                            by: str = "manager") -> None:
        if not str(reason or "").strip():
            raise FindingError("false positive needs a reason")
        self.validation = ValidationState.FAILED
        self.transition(FindingState.FALSE_POSITIVE, by=by, reason=reason)

    def mark_inconclusive(self, reason: str, *,
                          by: str = "manager") -> None:
        self.validation = ValidationState.INCONCLUSIVE
        if self.verification is not VerificationState.FAILED:
            self.verification = VerificationState.INCONCLUSIVE
        self.transition(FindingState.INCONCLUSIVE, by=by, reason=reason)

    def mark_remediated(self, *, before_sha256: str, after_sha256: str,
                        approval_ref: str = "", patch_ref: str = "",
                        line: int = 0, replacement_preview: str = "",
                        by: str = "security-remediation") -> None:
        if self.state is not FindingState.VALIDATED:
            raise FindingError("remediation requires a validated finding")
        stamp = time.time()
        self.remediation.update({
            "status": RemediationState.APPLIED.value,
            "applied_at": stamp,
            "before_sha256": str(before_sha256)[:64],
            "after_sha256": str(after_sha256)[:64],
            "approval_ref": str(approval_ref)[:80],
            "patch_ref": str(patch_ref)[:80],
            "line": max(0, int(line)),
            "replacement_preview": scrub_text(replacement_preview,
                                              limit=200)})
        self.transition(FindingState.REMEDIATED, by=by,
                        reason="change applied through authorized tools")

    def mark_reverified(self, verified: bool, *, evidence: str = "",
                        by: str = "remediation-verifier") -> None:
        if self.state is not FindingState.REMEDIATED:
            raise FindingError("re-verification requires a remediated finding")
        stamp = time.time()
        if verified:
            self.verification = VerificationState.VERIFIED
            self.remediation["status"] = RemediationState.VERIFIED.value
            self.remediation["verified_at"] = stamp
            if evidence:
                if len(self.evidence) < MAX_EVIDENCE:
                    self.evidence.append(EvidenceRef(
                        kind="verification", ref=self.location,
                        detail=evidence))
            self.transition(FindingState.REVERIFIED, by=by,
                            reason="post-change scan no longer matches")
        else:
            self.verification = VerificationState.FAILED
            self.mark_inconclusive(
                evidence or "post-change scan still matches", by=by)

    def reopen(self, reason: str, *, by: str = "re-scan") -> None:
        if self.state in (FindingState.REMEDIATED,
                          FindingState.REVERIFIED):
            self.verification = VerificationState.UNVERIFIED
            self.remediation["status"] = RemediationState.APPLIED.value
            self.transition(FindingState.VALIDATED, by=by, reason=reason)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "finding_id": self.finding_id,
            "title": self.title,
            "category": self.category,
            "severity": self.severity.value,
            "asset": self.asset,
            "location": self.location,
            "kind": self.kind,
            "evidence": [item.to_dict() for item in self.evidence],
            "confidence": round(self.confidence, 4),
            "provenance": self.provenance,
            "state": self.state.value,
            "validation": self.validation.value,
            "reproduction": self.reproduction.value,
            "verification": self.verification.value,
            "remediation": dict(self.remediation),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "validated_at": self.validated_at,
            "remediated_at": self.remediated_at,
            "verified_at": self.verified_at,
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "trace_id": self.trace_id,
            "history": list(self.history),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SecurityFinding":
        if not isinstance(data, dict):
            raise FindingError("finding must be an object")
        if int(data.get("schema_version", 0) or 0) != SCHEMA_VERSION:
            raise FindingError("unsupported finding schema")
        required = ("finding_id", "kind", "asset")
        missing = [key for key in required if not data.get(key)]
        if missing:
            raise FindingError(f"missing finding fields: {missing}")
        stamps = _timestamps(data)
        return cls(
            finding_id=str(data.get("finding_id", "")),
            schema_version=SCHEMA_VERSION,
            title=str(data.get("title", "")),
            category=str(data.get("category", "code")),
            severity=data.get("severity", "unknown"),
            asset=str(data.get("asset", "")),
            location=str(data.get("location", "")),
            kind=str(data.get("kind", "")),
            evidence=data.get("evidence") or [],
            confidence=data.get("confidence", 0.5),
            provenance=str(data.get("provenance", "unknown")),
            state=data.get("state", "discovered"),
            validation=data.get("validation", "unvalidated"),
            reproduction=data.get("reproduction", "not_attempted"),
            verification=data.get("verification", "unverified"),
            remediation=data.get("remediation") or {},
            task_id=str(data.get("task_id", "")),
            agent_id=str(data.get("agent_id", "")),
            trace_id=str(data.get("trace_id", "")),
            history=data.get("history") or [],
            **stamps)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


_CATEGORY_RULES = (
    ("secret:", "secrets"),
    ("injection", "injection"),
    ("dependency", "dependencies"),
    ("supply", "dependencies"),
    ("debug", "config"),
    ("tls", "config"),
    ("cors", "config"),
    ("bind", "config"),
    ("sql", "web"),
    ("xss", "web"),
    ("ssrf", "web"),
)


def category_for_kind(kind: str) -> str:
    lowered = str(kind or "").lower()
    for needle, category in _CATEGORY_RULES:
        if needle in lowered:
            return category
    return "code"


def finding_from_review(item: dict[str, Any], *,
                        root: str | Path | None = None) -> SecurityFinding:
    """Adapt one ``review_path`` hit into the stable finding contract."""
    raw_file = str(item.get("file", ""))
    asset = raw_file
    if root:
        try:
            asset = str(Path(raw_file).resolve().relative_to(
                Path(root).resolve()))
        except (ValueError, OSError):
            asset = Path(raw_file).name
    line = 0
    try:
        line = max(0, int(item.get("line", 0) or 0))
    except (TypeError, ValueError):
        line = 0
    location = f"{asset}:{line}" if line else asset
    kind = str(item.get("kind", "heuristic"))[:80]
    detail = str(item.get("detail", "") or "heuristic hit")
    severity = str(item.get("severity", "medium")).lower()
    if severity not in {s.value for s in Severity}:
        severity = "unknown"
    confidence = {"critical": 0.85, "high": 0.75, "medium": 0.6,
                  "low": 0.45}.get(severity, 0.3)
    evidence = [
        EvidenceRef(kind="scan-line", ref=location,
                    detail=str(item.get("evidence", ""))),
        EvidenceRef(kind="rule", ref=kind, detail=detail),
    ]
    finding = SecurityFinding(
        title=detail, category=category_for_kind(kind),
        severity=severity, asset=asset, location=location, kind=kind,
        evidence=evidence, confidence=confidence,
        provenance=f"static-review:{item.get('owasp', '')}".rstrip(":"),
        state=FindingState.DISCOVERED,
        remediation={"status": "none", "guidance": detail})
    if root:
        try:
            root_key = str(Path(root).resolve())
        except (OSError, RuntimeError):
            root_key = str(root)
        finding.finding_id = make_finding_id(
            finding.asset, finding.kind, finding.location, root=root_key)
    return finding


class FindingStore:
    """Atomic finding store. Corrupt state is quarantined, never trusted."""

    def __init__(self, home: str | Path | None,
                 filename: str = STORE_FILENAME,
                 max_findings: int = MAX_FINDINGS) -> None:
        self.home = Path(home) if home else None
        self.filename = filename
        self.max_findings = max(1, int(max_findings))
        self._lock = threading.RLock()
        self._findings: dict[str, SecurityFinding] = {}
        self.corrupt = ""
        self.quarantined = ""
        self._load()

    @property
    def path(self) -> Path | None:
        return self.home / self.filename if self.home else None

    def _load(self) -> None:
        path = self.path
        if path is None or not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            self._quarantine(f"{type(exc).__name__}")
            return
        if not isinstance(raw, dict):
            self._quarantine("root not an object")
            return
        if int(raw.get("version", 0) or 0) != SCHEMA_VERSION:
            self._quarantine("unsupported version")
            return
        items = raw.get("findings")
        if not isinstance(items, list):
            self._quarantine("findings not a list")
            return
        loaded = 0
        for item in items[:self.max_findings]:
            try:
                finding = SecurityFinding.from_dict(item)
            except (FindingError, TypeError, ValueError):
                self._quarantine("malformed finding")
                return
            self._findings[finding.finding_id] = finding
            loaded += 1
        if loaded == 0 and items:
            self._quarantine("no valid findings")

    def _quarantine(self, reason: str) -> None:
        self.corrupt = str(reason)[:200]
        path = self.path
        if path is None or not path.exists():
            self._findings = {}
            return
        target = path.with_name(
            f"{path.stem}.corrupt-{int(time.time())}{path.suffix}")
        try:
            os.replace(path, target)
            self.quarantined = str(target)
        except OSError:
            self.quarantined = ""
        self._findings = {}

    def _save(self) -> None:
        path = self.path
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": SCHEMA_VERSION,
                   "findings": [finding.to_dict()
                                for finding in self._findings.values()]}
        fd, tmp = tempfile.mkstemp(prefix=".findings-", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, default=str)
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def _require_writeable(self) -> None:
        if self.corrupt:
            raise FindingError(
                f"finding store quarantined: {self.corrupt}; "
                "inspect the .corrupt file before rerunning")

    def _make_room(self) -> None:
        if len(self._findings) < self.max_findings:
            return
        for state in (FindingState.FALSE_POSITIVE,
                      FindingState.INCONCLUSIVE,
                      FindingState.DISCOVERED):
            candidates = sorted(
                (f for f in self._findings.values() if f.state is state),
                key=lambda f: f.updated_at)
            if candidates:
                self._findings.pop(candidates[0].finding_id, None)
                return
        raise FindingError("finding store full of non-droppable findings")

    def save(self, finding: SecurityFinding) -> SecurityFinding:
        """Persist a finding's current state without discovery semantics."""
        if not isinstance(finding, SecurityFinding):
            raise FindingError("save requires a SecurityFinding")
        with self._lock:
            self._require_writeable()
            self._findings[finding.finding_id] = finding
            self._save()
            return finding

    def upsert(self, finding: SecurityFinding) -> SecurityFinding:
        if not isinstance(finding, SecurityFinding):
            raise FindingError("upsert requires a SecurityFinding")
        with self._lock:
            self._require_writeable()
            existing = self._findings.get(finding.finding_id)
            if existing is None:
                self._make_room()
                self._findings[finding.finding_id] = finding
            elif existing is finding:
                pass  # same object: state was changed deliberately
            else:
                # Discovery refreshes evidence but never silently
                # downgrades a validated/remediated finding.
                existing.title = finding.title
                existing.category = finding.category
                existing.severity = finding.severity
                existing.asset = finding.asset
                existing.location = finding.location
                existing.kind = finding.kind
                existing.evidence = finding.evidence
                existing.confidence = finding.confidence
                existing.provenance = finding.provenance
                existing.updated_at = time.time()
                if finding.state is FindingState.DISCOVERED and \
                        existing.state in (FindingState.REMEDIATED,
                                           FindingState.REVERIFIED):
                    existing.reopen("observed again after remediation")
                self._findings[existing.finding_id] = existing
                finding = existing
            self._save()
            return finding


    def get(self, finding_id: str) -> SecurityFinding | None:
        with self._lock:
            return self._findings.get(str(finding_id))

    def list(self, *, state: str = "", severity: str = "",
             category: str = "", limit: int = 0) -> list[SecurityFinding]:
        with self._lock:
            items = list(self._findings.values())
        if state:
            items = [f for f in items if f.state.value == state]
        if severity:
            items = [f for f in items if f.severity.value == severity]
        if category:
            items = [f for f in items if f.category == category]
        items.sort(key=lambda f: (
            -severity_rank(f.severity), f.asset, f.location))
        if limit:
            items = items[:max(0, int(limit))]
        return items

    def counts(self) -> dict[str, Any]:
        with self._lock:
            items = list(self._findings.values())
        by_severity = {s.value: 0 for s in Severity}
        by_state = {s.value: 0 for s in FindingState}
        for finding in items:
            by_severity[finding.severity.value] += 1
            by_state[finding.state.value] += 1
        open_states = {FindingState.DISCOVERED.value,
                       FindingState.SUSPECTED.value,
                       FindingState.VALIDATED.value,
                       FindingState.REMEDIATED.value,
                       FindingState.INCONCLUSIVE.value}
        return {
            "total": len(items),
            "by_severity": by_severity,
            "by_state": by_state,
            "open": sum(1 for f in items
                        if f.state.value in open_states),
            "validated": by_state[FindingState.VALIDATED.value],
            "reverified": by_state[FindingState.REVERIFIED.value],
            "false_positive": by_state[FindingState.FALSE_POSITIVE.value],
        }

    def posture(self) -> str:
        if self.corrupt:
            return "unknown"
        items = self.list()
        open_states = {FindingState.DISCOVERED, FindingState.SUSPECTED,
                       FindingState.VALIDATED, FindingState.REMEDIATED}
        open_items = [f for f in items if f.state in open_states]
        if any(f.severity is Severity.CRITICAL for f in open_items):
            return "critical"
        if any(f.severity is Severity.HIGH for f in open_items):
            return "attention"
        if open_items:
            return "review"
        return "clear"

    def update(self, finding_id: str, **changes: Any) -> SecurityFinding:
        """Update descriptive fields only; state moves through methods."""
        allowed = {"title", "category", "severity", "asset", "location",
                   "kind", "evidence", "confidence", "provenance",
                   "remediation", "task_id", "agent_id", "trace_id"}
        with self._lock:
            self._require_writeable()
            finding = self._findings.get(str(finding_id))
            if finding is None:
                raise FindingError(f"unknown finding: {finding_id}")
            for key, value in changes.items():
                if key not in allowed:
                    raise FindingError(
                        f"field not directly updateable: {key}")
                setattr(finding, key, value)
            finding.__post_init__()
            self._save()
            return finding


__all__ = [
    "SCHEMA_VERSION", "STORE_FILENAME", "MAX_FINDINGS",
    "FindingError", "Severity", "FindingState", "ValidationState",
    "ReproductionState", "VerificationState", "RemediationState",
    "ALLOWED_TRANSITIONS", "EvidenceRef", "SecurityFinding",
    "FindingStore", "finding_from_review", "category_for_kind",
    "make_finding_id", "scrub_text", "severity_rank",
]
