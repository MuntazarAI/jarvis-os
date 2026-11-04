"""JARVIS Security subsystem — defensive security intelligence.

Public API for the Security Intelligence Layer:

- SecurityFinding / FindingStore — structured findings with evidence,
  provenance, validation state machine (discovered → suspected →
  validated → remediated → re-verified), atomic persistence.
- SecurityManager — single authorized boundary: scope validation,
  deterministic static discovery, re-check validation, remediation
  proposal → policy/approval-gated apply → post-change re-verification.
- validate_scope — local target validation (operator-authorized only).
- board_security_info — secret-scrubbed snapshot for the read-only board.
- review_path / recheck_finding — offline heuristic SAST scanner.
- is_safe_url / scan_injection — SSRF and prompt-injection guards.
- SecretVault — local encrypted-at-rest secret store.

Safety: discovery is read-only; remediation requires a fresh policy
decision and single-use approval; a write never marks a finding fixed
— only a post-change re-check can move it to ``reverified``.
"""

from .findings import (
    SCHEMA_VERSION, STORE_FILENAME, MAX_FINDINGS,
    FindingError, Severity, FindingState, ValidationState,
    ReproductionState, VerificationState, RemediationState,
    ALLOWED_TRANSITIONS, EvidenceRef, SecurityFinding,
    FindingStore, finding_from_review, category_for_kind,
    make_finding_id, scrub_text, severity_rank,
)
from .intel import (
    SecurityError, SecurityScope, SecurityManager, validate_scope,
    board_security_info, MANAGER_ACTOR, REPORT_FILENAME, STEPS,
)
from .review import review_path, recheck_finding
from .guards import is_safe_url, scan_injection
from .security import SecretVault

__all__ = [
    # Findings contract
    "SCHEMA_VERSION", "STORE_FILENAME", "MAX_FINDINGS",
    "FindingError", "Severity", "FindingState", "ValidationState",
    "ReproductionState", "VerificationState", "RemediationState",
    "ALLOWED_TRANSITIONS", "EvidenceRef", "SecurityFinding",
    "FindingStore", "finding_from_review", "category_for_kind",
    "make_finding_id", "scrub_text", "severity_rank",
    # Security Manager
    "SecurityError", "SecurityScope", "SecurityManager",
    "validate_scope", "board_security_info", "MANAGER_ACTOR",
    "REPORT_FILENAME", "STEPS",
    # Static review
    "review_path", "recheck_finding",
    # Guards
    "is_safe_url", "scan_injection",
    # Secrets vault
    "SecretVault",
]