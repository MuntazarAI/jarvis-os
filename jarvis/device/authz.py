"""Persistent per-device authorization: grants and suspension (4.2).

A grant authorizes ``actor`` to invoke ``capability`` on ``device_id``.
Default deny: with no active grant, nothing is authorized. Grants,
revocations, and device suspensions persist in
``<home>/device-grants.json`` (atomic write, merge-load) so they survive
process, server, and CLI restarts.

Enforcement point: :meth:`DeviceRouter.authorize` consults the store
*in addition to* PolicyEngine — existing ``required_permissions`` checks
are untouched, so nothing that passes today stops passing for routers
without a store attached (backward compatible), while routers with a
store deny anything the store does not allow (no bypass below).

Suspension is device-level and lives in the grant layer (presence and
trust are untouched: a suspended node keeps heartbeating; only commands
are refused). Lifecycle DISABLED is a separate fabric mechanism.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import tempfile
from pathlib import Path
from typing import Any

from ..core.types import now
from .audit import DeviceAudit
from .capabilities import validate_capability_name

GRANTS_FILENAME = "device-grants.json"

_GRANT_ID_BYTES = 8
_NAME_RE = re.compile(r"^[A-Za-z0-9 _.\-]{1,80}$")
_ACTOR_RE = re.compile(r"^[A-Za-z0-9_.@\-]{1,64}$")


def _new_grant_id() -> str:
    return "grt-" + secrets.token_hex(_GRANT_ID_BYTES)


def validate_grant_actor(actor: str) -> str:
    """Actors are ``*`` (any) or a tight slug. Never blank."""
    if actor == "*":
        return actor
    if not isinstance(actor, str) or not _ACTOR_RE.fullmatch(actor):
        raise ValueError(f"invalid grant actor: {actor!r}")
    return actor


def validate_grant_capability(capability: str) -> str:
    """Capabilities are ``*`` (any) or a valid capability name."""
    if capability == "*":
        return capability
    return validate_capability_name(capability)


class GrantError(ValueError):
    """Raised for grant misuse (unknown ids, invalid input)."""


class DeviceGrantStore:
    """Durable device/capability grants + device suspension."""

    def __init__(self, home: str | Path | None,
                 audit: DeviceAudit | None = None) -> None:
        self.home = Path(home) if home else None
        self.audit = audit or DeviceAudit(home)
        self._grants: dict[str, dict[str, Any]] = {}
        self._suspended: dict[str, dict[str, Any]] = {}
        self._loaded_mtime: float = 0.0
        self.load()

    # -- persistence -----------------------------------------------------

    @property
    def path(self) -> Path | None:
        if self.home is None:
            return None
        return self.home / GRANTS_FILENAME

    def load(self) -> int:
        """Merge disk state (per-grant overwrite, never delete)."""
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
        for gid, item in (raw.get("grants") or {}).items():
            if isinstance(item, dict) and item.get("grant_id"):
                self._grants[str(gid)] = item
                loaded += 1
        for device_id, item in (raw.get("suspended_devices") or {}).items():
            if isinstance(item, dict):
                self._suspended[str(device_id)] = item
        return loaded

    def _maybe_reload(self) -> None:
        """Pick up other processes' writes (mtime-gated, cheap)."""
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
                   "grants": self._grants,
                   "suspended_devices": self._suspended}
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".device-grants-",
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

    # -- mutations ---------------------------------------------------------

    def grant(self, device_id: str, capability: str, *,
              actor: str = "*", by: str = "",
              reason: str = "", ttl_s: float = 0.0) -> dict[str, Any]:
        """Authorize actor/capability on device. Returns the record."""
        if not device_id:
            raise GrantError("device_id is required")
        capability = validate_grant_capability(capability)
        actor = validate_grant_actor(actor)
        self._maybe_reload()
        stamp = now()
        record = {
            "grant_id": _new_grant_id(),
            "device_id": device_id,
            "capability": capability,
            "actor": actor,
            "status": "active",
            "created_by": by[:64],
            "reason": reason[:200],
            "created_at": stamp,
            "expires_at": (stamp + ttl_s) if ttl_s and ttl_s > 0 else 0.0,
            "history": [{"at": stamp, "event": "granted", "by": by[:64],
                         "reason": reason[:200]}],
        }
        self._grants[record["grant_id"]] = record
        self.save()
        self.audit.record("device.grant.created", actor=by,
                          device_id=device_id, ok=True,
                          reasons=[reason[:200]] if reason else [],
                          extra={"grant_id": record["grant_id"],
                                 "capability": capability,
                                 "grant_actor": actor})
        return dict(record)

    def revoke(self, device_id: str, capability: str, *,
               actor: str = "*", by: str = "",
               reason: str = "") -> dict[str, Any]:
        """Revoke matching active grants. Returns {revoked: [ids]}."""
        capability = validate_grant_capability(capability)
        actor = validate_grant_actor(actor)
        self._maybe_reload()
        revoked: list[str] = []
        stamp = now()
        for record in self._grants.values():
            if (record.get("device_id") == device_id
                    and record.get("capability") == capability
                    and record.get("actor") == actor
                    and record.get("status") == "active"):
                record["status"] = "revoked"
                record.setdefault("history", []).append(
                    {"at": stamp, "event": "revoked", "by": by[:64],
                     "reason": reason[:200]})
                revoked.append(record["grant_id"])
        self.save()
        self.audit.record("device.grant.revoked", actor=by,
                          device_id=device_id, ok=True,
                          reasons=[reason[:200]] if reason else [],
                          extra={"capability": capability,
                                 "grant_actor": actor,
                                 "revoked": revoked})
        return {"revoked": revoked}

    def suspend_device(self, device_id: str, *, by: str = "",
                       reason: str = "") -> dict[str, Any]:
        """Suspend a device: presence/trust untouched, commands refused."""
        if not device_id:
            raise GrantError("device_id is required")
        self._maybe_reload()
        self._suspended[device_id] = {"by": by[:64], "reason": reason[:200],
                                      "at": now()}
        self.save()
        self.audit.record("device.suspended", actor=by, device_id=device_id,
                          ok=True, reasons=[reason[:200]] if reason else [])
        return dict(self._suspended[device_id])

    def restore_device(self, device_id: str, *, by: str = "",
                       reason: str = "") -> bool:
        """Lift a suspension. Returns True when one existed."""
        self._maybe_reload()
        existed = self._suspended.pop(device_id, None) is not None
        if existed:
            self.save()
            self.audit.record("device.restored", actor=by,
                              device_id=device_id, ok=True,
                              reasons=[reason[:200]] if reason else [])
        return existed

    # -- checks --------------------------------------------------------------

    def is_suspended(self, device_id: str) -> bool:
        self._maybe_reload()
        return device_id in self._suspended

    def _grant_live(self, record: dict[str, Any], at: float) -> bool:
        if record.get("status") != "active":
            return False
        expires = float(record.get("expires_at") or 0.0)
        return not (expires and at >= expires)

    def is_allowed(self, actor: str, device_id: str,
                   capability: str) -> tuple[bool, str]:
        """Default deny. Returns (allowed, reason). Never raises."""
        try:
            self._maybe_reload()
            if device_id in self._suspended:
                return False, "device is suspended"
            stamp = now()
            for record in self._grants.values():
                if record.get("device_id") != device_id:
                    continue
                cap = record.get("capability")
                if cap != capability and cap != "*":
                    continue
                act = record.get("actor", "*")
                if act != actor and act != "*":
                    continue
                if self._grant_live(record, stamp):
                    return True, "grant " + str(record.get("grant_id"))
                if record.get("status") == "active":
                    return False, "grant expired"
            return False, "no grant for device/capability"
        except Exception as exc:
            return False, f"grant check failed (fail closed): {exc}"[:160]

    def grants_for(self, device_id: str) -> list[dict[str, Any]]:
        self._maybe_reload()
        return [dict(r) for r in self._grants.values()
                if r.get("device_id") == device_id]

    def suspended_devices(self) -> dict[str, dict[str, Any]]:
        self._maybe_reload()
        return {k: dict(v) for k, v in self._suspended.items()}


__all__ = [
    "DeviceGrantStore",
    "GrantError",
    "validate_grant_actor",
    "validate_grant_capability",
]
