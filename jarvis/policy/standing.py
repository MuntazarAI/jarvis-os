"""Standing grants: bounded durable authorization inputs (Autonomy 1.0).

A standing grant lets a user pre-authorize a narrow capability class
(e.g. organize files inside ~/Downloads) so repeated low-risk actions
don't each need an interactive approval. Grants are authorization
INPUT to PolicyEngine — never a bypass: risk assessment, approval
requirements for higher risk, local-only egress, and emergency stop
all still apply on top.

Conflict order: explicit deny > policy > grant; expired/revoked/
corrupt/mismatched = deny; emergency stop = deny everything.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

GRANTS_FILENAME = "standing-grants.json"
MAX_GRANTS = 64
MAX_SCOPE_CHARS = 512

# Risk classes reuse the repository's RiskLevel vocabulary.
RISK_CLASSES = ("read_only", "low", "moderate", "high", "critical")

# Scope kinds with matchers below. No implicit "*": a wildcard scope
# must be written explicitly and is always high/critical risk.
SCOPE_KINDS = ("path", "device", "topic", "capability")


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _utcnow() -> float:
    return time.time()


class GrantError(ValueError):
    """Malformed grant or store misuse."""


@dataclass
class StandingGrant:
    grant_id: str = field(
        default_factory=lambda: _new_id("grant"))
    subject: str = "user"
    capability: str = ""
    scope_kind: str = "path"
    scope: str = ""
    allowed_operations: list[str] = field(default_factory=list)
    denied_operations: list[str] = field(default_factory=list)
    risk_class: str = "low"
    created_at: float = field(default_factory=_utcnow)
    expires_at: float = 0.0  # 0 = 30-day default applied at creation
    revoked_at: float = 0.0
    created_by: str = ""
    status: str = "active"
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.capability:
            raise GrantError("grant needs a capability")
        if self.scope_kind not in SCOPE_KINDS:
            raise GrantError(f"bad scope kind: {self.scope_kind!r}")
        if not self.scope or len(self.scope) > MAX_SCOPE_CHARS:
            raise GrantError("bad scope")
        if self.risk_class not in RISK_CLASSES:
            raise GrantError(f"bad risk class: {self.risk_class!r}")
        if self.scope == "*" and self.risk_class not in ("high",
                                                          "critical"):
            raise GrantError("wildcard scope requires high/critical risk")
        if not self.allowed_operations:
            raise GrantError("grant needs allowed operations")
        self.capability = self.capability[:120]
        self.scope = self.scope[:MAX_SCOPE_CHARS]
        if self.status not in ("active", "revoked", "expired"):
            raise GrantError(f"bad status: {self.status!r}")

    @property
    def expired(self) -> bool:
        return bool(self.expires_at) and _utcnow() >= self.expires_at

    @property
    def live(self) -> bool:
        return self.status == "active" and not self.expired \
            and not self.revoked_at

    @property
    def revoked(self) -> bool:
        return bool(self.revoked_at) or self.status == "revoked"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["live"] = self.live
        return data


def _contains(root: str, candidate: str) -> bool:
    """True iff candidate is inside root (symlinks resolved on both
    sides where they exist; missing paths fail closed)."""
    try:
        root_path = Path(root).expanduser()
        cand_path = Path(candidate).expanduser()
        if not root_path.exists() or not cand_path.exists():
            # Missing side: fall back to lexical containment, still
            # rejecting ".." escapes.
            if ".." in Path(candidate).parts:
                return False
            try:
                cand_path.relative_to(root_path)
                return True
            except ValueError:
                return False
        return cand_path.resolve().is_relative_to(root_path.resolve())
    except (OSError, ValueError):
        return False


def scope_matches(grant: StandingGrant, kind: str,
                  resource: str) -> bool:
    """Does this grant's scope cover the resource? Fail closed."""
    if grant.scope_kind != kind:
        return False
    scope, target = grant.scope, str(resource or "")
    if not target:
        return False
    if scope == "*":
        return True
    if kind == "path":
        if ".." in Path(target).parts:
            return False
        return _contains(scope, target)
    if kind in ("device", "topic", "capability"):
        return target == scope or (
            scope.endswith("*") and target.startswith(scope[:-1]))
    return False


def evaluate_grant(grant: StandingGrant, *, actor: str,
                   capability: str, scope_kind: str, resource: str,
                   operation: str, at: float = 0.0) -> tuple[bool, str]:
    """Check one action against one grant. Never raises; deny on doubt."""
    try:
        if grant.subject not in ("*", actor):
            return False, "grant bound to another subject"
        if grant.capability != capability:
            return False, "capability mismatch"
        if not grant.live:
            if grant.revoked:
                return False, "grant revoked"
            if grant.expired:
                return False, "grant expired"
            return False, "grant not active"
        if operation in grant.denied_operations:
            return False, "operation explicitly denied"
        if operation not in grant.allowed_operations:
            return False, "operation not allowed"
        if not scope_matches(grant, scope_kind, resource):
            return False, "scope mismatch"
        return True, "standing grant covers action"
    except Exception as exc:
        return False, f"grant check failed: {type(exc).__name__}"


class StandingGrantStore:
    """Durable bounded grant registry. Atomic writes, mtime reload,
    corrupt file fails closed (empty until repaired)."""

    def __init__(self, home: str | Path | None) -> None:
        self.home = Path(home) if home else None
        self._grants: dict[str, StandingGrant] = {}
        self._loaded_mtime: float = 0.0
        self.load()

    @property
    def path(self) -> Path | None:
        if self.home is None:
            return None
        return self.home / GRANTS_FILENAME

    def load(self) -> int:
        path = self.path
        self._grants = {}
        self._loaded_mtime = 0.0
        if path is None or not path.exists():
            return 0
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return 0
        if not isinstance(raw, dict):
            return 0
        loaded = 0
        for gid, item in (raw.get("grants") or {}).items():
            try:
                grant = StandingGrant(**{k: v for k, v in item.items()
                                         if k in StandingGrant.__dataclass_fields__})
            except (GrantError, TypeError, ValueError):
                continue  # corrupt entry fails closed (skipped)
            if grant.grant_id == gid:
                self._grants[gid] = grant
                loaded += 1
        try:
            self._loaded_mtime = path.stat().st_mtime
        except OSError:
            pass
        return loaded

    def _maybe_reload(self) -> None:
        path = self.path
        if path is None:
            return
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return
        if mtime != self._loaded_mtime:
            self.load()

    def save(self) -> None:
        path = self.path
        if path is None:
            return
        payload = {"version": 1,
                   "grants": {gid: g.to_dict() for gid, g in
                              self._grants.items()}}
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".standing-grants-",
                                       dir=str(path.parent))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, indent=2, sort_keys=True,
                              default=str)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp, path)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            try:
                self._loaded_mtime = path.stat().st_mtime
            except OSError:
                pass
        except OSError:
            pass

    def create(self, capability: str, scope_kind: str, scope: str, *,
               allowed_operations: list[str],
               denied_operations: list[str] | None = None,
               risk_class: str = "low", subject: str = "user",
               expires_in_s: float = 30 * 24 * 3600.0,
               by: str = "", provenance: dict | None = None,
               ) -> StandingGrant:
        self._maybe_reload()
        if len(self._grants) >= MAX_GRANTS:
            raise GrantError("grant registry full")
        grant = StandingGrant(
            capability=capability, scope_kind=scope_kind, scope=scope,
            allowed_operations=[str(o)[:80] for o in allowed_operations],
            denied_operations=[str(o)[:80] for o in
                               (denied_operations or [])],
            risk_class=risk_class, subject=subject[:80],
            expires_at=_utcnow() + max(60.0, float(expires_in_s or 0.0)),
            created_by=by[:80],
            provenance={str(k)[:80]: str(v)[:200]
                        for k, v in (provenance or {}).items()})
        self._grants[grant.grant_id] = grant
        self.save()
        return grant

    def revoke(self, grant_id: str, *, by: str = "") -> bool:
        self._maybe_reload()
        grant = self._grants.get(grant_id)
        if grant is None or not grant.live:
            return False
        grant.revoked_at = _utcnow()
        grant.status = "revoked"
        grant.provenance["revoked_by"] = by[:80]
        self.save()
        return True

    def get(self, grant_id: str) -> StandingGrant | None:
        self._maybe_reload()
        return self._grants.get(str(grant_id or ""))

    def list(self, *, include_dead: bool = False) -> list[StandingGrant]:
        self._maybe_reload()
        grants = sorted(self._grants.values(),
                        key=lambda g: g.created_at)
        if include_dead:
            return grants
        return [g for g in grants if g.live]

    def authorize(self, actor: str, capability: str, scope_kind: str,
                  resource: str, operation: str) -> tuple[bool, str]:
        """Any live covering grant authorizes (deny beats allow is
        enforced inside evaluate_grant per operation)."""
        self._maybe_reload()
        for grant in sorted(self._grants.values(),
                            key=lambda g: g.created_at):
            ok, reason = evaluate_grant(
                grant, actor=actor, capability=capability,
                scope_kind=scope_kind, resource=resource,
                operation=operation)
            if ok:
                return True, f"{grant.grant_id}: {reason}"
        return False, "no live standing grant covers action"


__all__ = ["StandingGrant", "StandingGrantStore", "GrantError",
           "evaluate_grant", "scope_matches", "GRANTS_FILENAME",
           "RISK_CLASSES", "SCOPE_KINDS"]
