"""Durable approval tokens for device commands (4.2).

In-memory PolicyEngine approvals (``appr-``) die with the process. This
store persists approval state in ``<home>/device-approvals.json``
(atomic write, merge-load) so a CLI process and a long-running server
observe the same token lifecycle:

    PENDING -> APPROVED -> CONSUMED (single use)
    PENDING -> DENIED | REVOKED | EXPIRED (terminal)

Tokens are bound to (actor, device_id, capability, args-hash): a token
cannot be replayed, transferred to another device, or reused for
different arguments. Consumption is a single atomic state transition
(reload → check → mark → persist); the second consumer always loses.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import tempfile
from pathlib import Path
from typing import Any

from ..core.types import now
from .audit import DeviceAudit

APPROVALS_FILENAME = "device-approvals.json"
DEFAULT_APPROVAL_TTL_S = 300.0

PENDING = "pending"
APPROVED = "approved"
CONSUMED = "consumed"
EXPIRED = "expired"
REVOKED = "revoked"
DENIED = "denied"

_TERMINAL = frozenset({CONSUMED, EXPIRED, REVOKED, DENIED})


class ApprovalError(ValueError):
    """Raised for approval misuse (unknown tokens, invalid input)."""


def _new_token() -> str:
    # Distinct prefix from in-memory PolicyEngine (appr-) tokens.
    return "apd-" + secrets.token_hex(16)


def _args_hash(args: dict[str, Any] | None) -> str:
    try:
        canonical = json.dumps(dict(args or {}), sort_keys=True, default=str)
    except (TypeError, ValueError):
        canonical = repr(sorted((args or {}).items()))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ApprovalStore:
    """Durable, bound, single-use approval tokens."""

    def __init__(self, home: str | Path | None,
                 audit: DeviceAudit | None = None) -> None:
        self.home = Path(home) if home else None
        self.audit = audit or DeviceAudit(home)
        self._tokens: dict[str, dict[str, Any]] = {}
        self._loaded_mtime: float = 0.0
        self.load()

    # -- persistence -----------------------------------------------------

    @property
    def path(self) -> Path | None:
        if self.home is None:
            return None
        return self.home / APPROVALS_FILENAME

    def load(self) -> int:
        path = self.path
        self._loaded_mtime = 0.0
        if path is None or not path.exists():
            return 0
        try:
            self._loaded_mtime = path.stat().st_mtime
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return 0
        if not isinstance(raw, dict):
            return 0
        loaded = 0
        for token, item in (raw.get("approvals") or {}).items():
            if isinstance(item, dict) and item.get("token") == token:
                self._tokens[str(token)] = item
                loaded += 1
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
        payload = {"version": 1, "approvals": self._tokens}
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".device-approvals-",
                                       dir=str(path.parent))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, indent=2, sort_keys=True)
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

    # -- lifecycle ---------------------------------------------------------

    def _expired(self, record: dict[str, Any], at: float) -> bool:
        expires = float(record.get("expires_at") or 0.0)
        return bool(expires and at >= expires)

    def _mark_expired(self, record: dict[str, Any]) -> None:
        if record.get("state") == PENDING:
            record["state"] = EXPIRED
            record.setdefault("history", []).append(
                {"at": now(), "event": "expired"})

    def request(self, actor: str, device_id: str, capability: str,
                args: dict[str, Any] | None = None, *,
                by: str = "", reason: str = "",
                ttl_s: float = DEFAULT_APPROVAL_TTL_S) -> dict[str, Any]:
        """Create a PENDING token bound to actor/device/capability/args."""
        if not actor or not device_id or not capability:
            raise ApprovalError("actor, device_id and capability are required")
        self._maybe_reload()
        stamp = now()
        record = {
            "token": _new_token(),
            "state": PENDING,
            "actor": actor,
            "device_id": device_id,
            "capability": capability,
            "args_hash": _args_hash(args),
            "requested_by": by[:64],
            "reason": reason[:200],
            "created_at": stamp,
            "expires_at": stamp + ttl_s if ttl_s and ttl_s > 0 else 0.0,
            "history": [{"at": stamp, "event": "requested",
                         "by": by[:64], "reason": reason[:200]}],
        }
        self._tokens[record["token"]] = record
        self.save()
        self.audit.record("device.approval.requested", actor=by or actor,
                          device_id=device_id, ok=True,
                          reasons=[reason[:200]] if reason else [],
                          extra={"approval_id": record["token"],
                                 "capability": capability})
        return {k: v for k, v in record.items()}

    def _transition(self, token: str, *, expect: str, to: str,
                    by: str = "", event: str) -> bool:
        self._maybe_reload()
        record = self._tokens.get(token)
        if record is None:
            return False
        if self._expired(record, now()):
            self._mark_expired(record)
            self.save()
            return False
        if record.get("state") != expect:
            return False
        record["state"] = to
        record.setdefault("history", []).append(
            {"at": now(), "event": event, "by": by[:64]})
        self.save()
        return True

    def approve(self, token: str, *, by: str = "") -> bool:
        """PENDING -> APPROVED. Returns False unless it transitioned."""
        ok = self._transition(token, expect=PENDING, to=APPROVED,
                              by=by, event="approved")
        if ok:
            record = self._tokens[token]
            self.audit.record("device.approval.approved", actor=by,
                              device_id=str(record.get("device_id", "")),
                              ok=True,
                              extra={"approval_id": token,
                                     "capability": str(record.get("capability", ""))})
        return ok

    def deny(self, token: str, *, by: str = "", reason: str = "") -> bool:
        """PENDING -> DENIED."""
        ok = self._transition(token, expect=PENDING, to=DENIED,
                              by=by, event="denied")
        if ok:
            record = self._tokens[token]
            self.audit.record("device.approval.denied", actor=by,
                              device_id=str(record.get("device_id", "")),
                              ok=True, reasons=[reason[:200]] if reason else [],
                              extra={"approval_id": token})
        return ok

    def revoke(self, token: str, *, by: str = "", reason: str = "") -> bool:
        """PENDING/APPROVED -> REVOKED. Terminal states are untouched."""
        self._maybe_reload()
        record = self._tokens.get(token)
        if record is None:
            return False
        if record.get("state") not in (PENDING, APPROVED):
            return False
        record["state"] = REVOKED
        record.setdefault("history", []).append(
            {"at": now(), "event": "revoked", "by": by[:64],
             "reason": reason[:200]})
        self.save()
        self.audit.record("device.approval.revoked", actor=by,
                          device_id=str(record.get("device_id", "")),
                          ok=True, reasons=[reason[:200]] if reason else [],
                          extra={"approval_id": token})
        return True

    @staticmethod
    def _bindings_ok(record: dict[str, Any], *, actor: str,
                     device_id: str, capability: str,
                     args: dict[str, Any] | None) -> tuple[bool, str]:
        if record.get("actor") != actor:
            return False, "approval token bound to another actor"
        if record.get("device_id") != device_id:
            return False, "approval token bound to another device"
        if record.get("capability") != capability:
            return False, "approval token bound to another capability"
        if record.get("args_hash") != _args_hash(args):
            return False, "approval token bound to other arguments"
        return True, "approved"

    def peek(self, token: str, *, actor: str, device_id: str,
             capability: str,
             args: dict[str, Any] | None = None) -> tuple[bool, str]:
        """Check a token WITHOUT consuming it. Never raises."""
        try:
            self._maybe_reload()
            record = self._tokens.get(token)
            if record is None:
                return False, "unknown approval token"
            if self._expired(record, now()):
                return False, "approval token expired"
            if record.get("state") != APPROVED:
                return False, f"approval token is {record.get('state')}"
            return self._bindings_ok(record, actor=actor,
                                     device_id=device_id,
                                     capability=capability, args=args)
        except Exception as exc:
            return False, f"approval check failed (fail closed): {exc}"[:160]

    def consume(self, token: str, *, actor: str, device_id: str,
                capability: str,
                args: dict[str, Any] | None = None) -> tuple[bool, str]:
        """Atomically consume an APPROVED token iff every binding matches.

        Single use: the first consumer transitions APPROVED -> CONSUMED
        and wins; every later attempt loses. Bindings are re-verified
        after the reload so a concurrent mutation cannot slip through.
        Never raises.
        """
        try:
            self._maybe_reload()
            record = self._tokens.get(token)
            if record is None:
                return False, "unknown approval token"
            if self._expired(record, now()):
                self._mark_expired(record)
                self.save()
                return False, "approval token expired"
            if record.get("state") != APPROVED:
                return False, f"approval token is {record.get('state')}"
            ok, reason = self._bindings_ok(
                record, actor=actor, device_id=device_id,
                capability=capability, args=args)
            if not ok:
                return False, reason
            record["state"] = CONSUMED
            record.setdefault("history", []).append(
                {"at": now(), "event": "consumed", "by": actor[:64]})
            self.save()
            self.audit.record("device.approval.consumed", actor=actor,
                              device_id=device_id, ok=True,
                              extra={"approval_id": token,
                                     "capability": capability})
            return True, "consumed"
        except Exception as exc:
            return False, f"approval consume failed (fail closed): {exc}"[:160]

    def status(self, token: str) -> dict[str, Any] | None:
        self._maybe_reload()
        record = self._tokens.get(token)
        if record is None:
            return None
        return {k: v for k, v in record.items()}

    def list(self, state: str | None = None,
             limit: int = 100) -> list[dict[str, Any]]:
        """Operator-safe listing: tokens and secrets are never included.

        Returns newest-first summaries with id, device, capability,
        actor, state, timestamps — everything an operator needs except
        the token itself (passed separately via --approval).
        """
        self._maybe_reload()
        self.prune()
        records = sorted(self._tokens.values(),
                         key=lambda r: float(r.get("created_at") or 0.0),
                         reverse=True)
        out: list[dict[str, Any]] = []
        for record in records:
            if state is not None and record.get("state") != state:
                continue
            out.append({
                "approval_id": str(record.get("token", ""))[:12] + "…",
                "device_id": str(record.get("device_id", "")),
                "capability": str(record.get("capability", "")),
                "actor": str(record.get("actor", "")),
                "state": str(record.get("state", "")),
                "created_at": float(record.get("created_at") or 0.0),
                "expires_at": float(record.get("expires_at") or 0.0),
                "reason": str(record.get("reason", ""))[:120],
            })
            if len(out) >= max(1, limit):
                break
        return out

    def prune(self) -> int:
        """Mark expired PENDING records EXPIRED. Returns count changed."""
        self._maybe_reload()
        changed = 0
        stamp = now()
        for record in self._tokens.values():
            if record.get("state") == PENDING and self._expired(record, stamp):
                self._mark_expired(record)
                changed += 1
                self.audit.record("device.approval.expired", actor="",
                                  device_id=str(record.get("device_id", "")),
                                  ok=False, reasons=["ttl exceeded"],
                                  extra={"approval_id": str(record.get("token", ""))})
        if changed:
            self.save()
        return changed


__all__ = [
    "ApprovalStore",
    "ApprovalError",
    "PENDING",
    "APPROVED",
    "CONSUMED",
    "EXPIRED",
    "REVOKED",
    "DENIED",
]
