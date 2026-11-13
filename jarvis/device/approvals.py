"""Durable approval tokens for device commands (4.2).

In-memory PolicyEngine approvals (``appr-``) die with the process. This
store persists approval state in ``<home>/device-approvals.json``
(atomic write, replace-load) so a CLI process and a long-running server
observe the same token lifecycle:

    PENDING -> APPROVED -> CONSUMED (single use)
    PENDING -> DENIED | REVOKED | EXPIRED (terminal)

Tokens are bound to (actor, device_id, capability, args-hash): a token
cannot be replayed, transferred to another device, or reused for
different arguments. Consumption is a single atomic state transition
(reload → check → mark → persist) under a cross-process lock file; the
second consumer always loses, and a token is only reported consumed
after it is durably persisted.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ..core.types import now
from .audit import DeviceAudit
from .outbox import _lock_file

APPROVALS_FILENAME = "device-approvals.json"
APPROVALS_LOCKNAME = "device-approvals.lock"
DEFAULT_APPROVAL_TTL_S = 300.0

PENDING = "pending"
APPROVED = "approved"
CONSUMED = "consumed"
EXPIRED = "expired"
REVOKED = "revoked"
DENIED = "denied"

#: Approval states that end the request. A denial is final: the
#: request is never re-asked after one of these.
TERMINAL_STATES = frozenset({CONSUMED, EXPIRED, REVOKED, DENIED})
_TERMINAL = TERMINAL_STATES


class ApprovalError(ValueError):
    """Raised for approval misuse (unknown tokens, invalid input)."""


#: Minimum prefix length for operator token resolution. Full tokens stay
#: out of listings; operators act via unique prefixes instead.
MIN_PREFIX_LEN = 4


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

    @property
    def lock_path(self) -> Path | None:
        if self.home is None:
            return None
        return self.home / APPROVALS_LOCKNAME

    def load(self) -> int:
        """Replace memory with disk state.

        Disk is authoritative so revokes/consumes from another process
        propagate; corrupt or unreadable state quarantines to empty
        (fail closed).
        """
        path = self.path
        self._loaded_mtime = 0.0
        if path is None:
            return 0  # in-memory store: no disk state to replace
        if not path.exists():
            self._tokens = {}
            return 0
        try:
            self._loaded_mtime = path.stat().st_mtime
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._tokens = {}
            return 0
        if not isinstance(raw, dict):
            self._tokens = {}
            return 0
        fresh: dict[str, dict[str, Any]] = {}
        for token, item in (raw.get("approvals") or {}).items():
            if isinstance(item, dict) and item.get("token") == token:
                fresh[str(token)] = item
        self._tokens = fresh
        return len(fresh)

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

    @contextmanager
    def _mutate(self):
        """Lock, reload, yield. Every mutator runs under this.

        Disk is authoritative while the lock is held, so a mutation made
        from a view loaded before another process consumed a token cannot
        write the old APPROVED record back (a whole-file save would
        otherwise resurrect it).
        """
        lock = self.lock_path
        if lock is None:
            yield
            return
        with _lock_file(lock):
            self.load()
            yield

    def save(self) -> bool:
        """Persist atomically. Returns False when the write failed.

        Callers that grant or spend authority must check this: a token
        that could not be persisted must never be reported as consumed
        (it would come back APPROVED after a restart).
        """
        path = self.path
        if path is None:
            return True  # in-memory store: memory is authoritative
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
            return True
        except OSError:
            return False

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
        with self._mutate():
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
        with self._mutate():
            full = self.resolve_prefix(token) or token
            record = self._tokens.get(full)
            if record is None:
                return False
            if self._expired(record, now()):
                self._mark_expired(record)
                self.save()
                return False
            if record.get("state") != expect:
                return False
            previous = record.get("state")
            record["state"] = to
            record.setdefault("history", []).append(
                {"at": now(), "event": event, "by": by[:64]})
            if not self.save():
                record["state"] = previous
                return False
            return True

    def approve(self, token: str, *, by: str = "") -> bool:
        """PENDING -> APPROVED. Accepts a full token or unique prefix."""
        ok = self._transition(token, expect=PENDING, to=APPROVED,
                              by=by, event="approved")
        if ok:
            full = self.resolve_prefix(token) or token
            record = self._tokens[full]
            self.audit.record("device.approval.approved", actor=by,
                              device_id=str(record.get("device_id", "")),
                              ok=True,
                              extra={"approval_id": full,
                                      "capability": str(record.get("capability", ""))})
        return ok

    def deny(self, token: str, *, by: str = "", reason: str = "") -> bool:
        """PENDING -> DENIED. Accepts a full token or unique prefix."""
        ok = self._transition(token, expect=PENDING, to=DENIED,
                              by=by, event="denied")
        if ok:
            full = self.resolve_prefix(token) or token
            record = self._tokens[full]
            self.audit.record("device.approval.denied", actor=by,
                              device_id=str(record.get("device_id", "")),
                              ok=True, reasons=[reason[:200]] if reason else [],
                              extra={"approval_id": full})
        return ok

    def revoke(self, token: str, *, by: str = "", reason: str = "") -> bool:
        """PENDING/APPROVED -> REVOKED. Accepts full token or prefix."""
        with self._mutate():
            full = self.resolve_prefix(token) or token
            record = self._tokens.get(full)
            if record is None:
                return False
            if record.get("state") not in (PENDING, APPROVED):
                return False
            previous = record.get("state")
            record["state"] = REVOKED
            record.setdefault("history", []).append(
                {"at": now(), "event": "revoked", "by": by[:64],
                 "reason": reason[:200]})
            if not self.save():
                record["state"] = previous
                return False
        self.audit.record("device.approval.revoked", actor=by,
                          device_id=str(record.get("device_id", "")),
                          ok=True, reasons=[reason[:200]] if reason else [],
                          extra={"approval_id": full})
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
        and wins; every later attempt loses. The whole reload → check →
        mark → persist cycle runs under the store lock file, so a CLI
        and a long-running server cannot both spend one token. A token
        is only reported consumed after it is durably persisted; an
        unwritable store fails closed. Never raises.
        """
        try:
            lock = self.lock_path
            if lock is None:
                return self._consume_locked(
                    token, actor=actor, device_id=device_id,
                    capability=capability, args=args)
            with _lock_file(lock):
                return self._consume_locked(
                    token, actor=actor, device_id=device_id,
                    capability=capability, args=args)
        except Exception as exc:
            return False, f"approval consume failed (fail closed): {exc}"[:160]

    def _consume_locked(self, token: str, *, actor: str, device_id: str,
                        capability: str,
                        args: dict[str, Any] | None) -> tuple[bool, str]:
        self.load()  # disk is authoritative while the lock is held
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
        previous = record.get("state")
        record["state"] = CONSUMED
        record.setdefault("history", []).append(
            {"at": now(), "event": "consumed", "by": actor[:64]})
        if not self.save():
            record["state"] = previous
            return False, "approval consume failed: store unwritable"
        self.audit.record("device.approval.consumed", actor=actor,
                          device_id=device_id, ok=True,
                          extra={"approval_id": token,
                                 "capability": capability})
        return True, "consumed"

    def status(self, token: str) -> dict[str, Any] | None:
        self._maybe_reload()
        full = self.resolve_prefix(token) or token
        record = self._tokens.get(full)
        if record is None:
            return None
        return {k: v for k, v in record.items()}

    def resolve_prefix(self, prefix: str) -> str | None:
        """Resolve an operator token prefix to the full token.

        Returns the token iff exactly one stored token starts with the
        prefix (minimum length enforced). Ambiguous, too-short, or
        unknown prefixes resolve to None — the caller reports the
        failure without dumping tokens. Listings stay truncated; this
        is what makes them actionable without leaking secrets.
        """
        self._maybe_reload()
        prefix = str(prefix or "")
        if len(prefix) < MIN_PREFIX_LEN:
            return None
        matches = [token for token in self._tokens
                   if token.startswith(prefix)]
        if len(matches) != 1:
            return None
        return matches[0]

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
        with self._mutate():
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
    "TERMINAL_STATES",
    "ApprovalError",
    "PENDING",
    "APPROVED",
    "CONSUMED",
    "EXPIRED",
    "REVOKED",
    "DENIED",
]
