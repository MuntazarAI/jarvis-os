"""High-level device command service + outbox drainer (4.2).

``DeviceCommandService`` is the single sanctioned entry for executing
device commands::

    request -> authorize (grant + policy) -> [approval] -> enqueue
      -> drain -> transport -> verify -> complete

It never touches sockets: delivery goes through the existing
``AndroidSocketHost.send_command`` / ``DeviceRouter.route`` APIs, which
re-authorize every call. Attaching the grant/approval stores to the
shared fabric router at construction closes every lower-level path too —
``adapter.send_command``, ``router.route`` and ``host.send_command``
all funnel through the same ``authorize()``.
"""

from __future__ import annotations

from typing import Any

from ..core.types import now
from .approvals import ApprovalStore
from .audit import DeviceAudit
from .authz import DeviceGrantStore
from .outbox import (
    APPROVED,
    COMPLETED,
    DISPATCHING,
    QUEUED,
    SENT,
    TERMINAL,
    CommandOutbox,
    OutboxError,
)

APPROVAL_DEFER_S = 30.0
LANE_DEFER_S = 30.0
DENY_DEFER_S = 60.0
MAX_PER_TICK = 25


class CommandServiceError(RuntimeError):
    """Raised for service misuse (unknown ids, bad input)."""


class DeviceCommandService:
    """Durable, audited device control above the transport."""

    def __init__(self, adapter: Any, *, host: Any = None,
                 grant_store: DeviceGrantStore | None = None,
                 approval_store: ApprovalStore | None = None,
                 outbox: CommandOutbox | None = None,
                 audit: DeviceAudit | None = None,
                 home: Any = None) -> None:
        if adapter is None:
            raise CommandServiceError("adapter is required")
        self.adapter = adapter
        self.host = host if host is not None else getattr(
            adapter, "socket_host", None)
        self.home = home or getattr(
            getattr(adapter, "fabric", None), "home", None)
        self.audit = audit or DeviceAudit(self.home)
        self.grants = grant_store or DeviceGrantStore(
            self.home, audit=self.audit)
        self.approvals = approval_store or ApprovalStore(
            self.home, audit=self.audit)
        self.outbox = outbox or CommandOutbox(self.home, audit=self.audit)
        # Close every lower-level path: the shared fabric router enforces
        # grants and consumes durable approvals for ALL callers, not just
        # this service (adapter.send_command, host.send_command, route).
        router = getattr(getattr(adapter, "fabric", None), "router", None)
        self.router = router
        if router is not None:
            if getattr(router, "grant_store", None) is None:
                router.grant_store = self.grants
            if getattr(router, "approval_store", None) is None:
                router.approval_store = self.approvals

    # -- helpers -----------------------------------------------------------

    def _validate(self, device_id: str, command: str,
                  args: dict[str, Any] | None) -> tuple[bool, dict[str, Any]]:
        """Shape-check a command. Returns (ok, {capability, args}|error)."""
        args = dict(args or {})
        validator = getattr(self.adapter, "validate_command", None)
        if validator is None:
            try:
                from .android import validate_command as android_validate
                validator = android_validate
            except ImportError:
                validator = None
        if validator is None:
            from .capabilities import validate_capability_name
            try:
                capability = validate_capability_name(command)
            except Exception as exc:
                return False, {"error": f"malformed command: {exc}"[:200]}
            return True, {"capability": capability, "args": args}
        try:
            checked = validator(command, args)
        except Exception as exc:
            return False, {"error": f"malformed command: {exc}"[:200]}
        return True, checked

    def _lane_gated(self, command: str) -> bool:
        """True when delivery needs a live socket lane (Android host)."""
        if self.host is None:
            return False
        validator = getattr(self.adapter, "validate_command", None)
        if validator is None:
            try:
                from .android import validate_command as android_validate
                validator = android_validate
            except ImportError:
                return False
        try:
            validator(command, {})
            return True
        except Exception:
            return False

    # -- public API ----------------------------------------------------------

    def preview(self, actor: str, device_id: str, command: str,
                args: dict[str, Any] | None = None, *,
                approval_id: str = "") -> dict[str, Any]:
        """Validate + authorize WITHOUT enqueuing or consuming anything.

        Pure check for gates (e.g. the cognitive loop policy stage):
        durable approvals are peeked, never consumed here.
        """
        args = dict(args or {})
        ok, checked = self._validate(device_id, command, args)
        if not ok:
            return {"authorized": False, "reasons": [checked["error"]],
                    "device": None, "decision": None, "approval_token": ""}
        if self.router is None:
            return {"authorized": False, "reasons": ["no router"],
                    "device": None, "decision": None, "approval_token": ""}
        gate = self.router.authorize(
            actor, device_id, checked["capability"], checked["args"],
            approval_token=approval_id)
        return gate

    def request_command(self, actor: str, device_id: str, command: str,
                        args: dict[str, Any] | None = None, *,
                        approval_id: str = "") -> dict[str, Any]:
        """Shape-check, enqueue durably, and attempt immediate delivery.

        Authorization happens exactly once, inside _deliver(): the
        single-use approval (if any) is consumed at most once per call.
        Hard denials still produce a FAILED record (auditable) rather
        than a silent refusal; only malformed commands are refused
        without a record.
        """
        if not actor or not device_id or not command:
            raise CommandServiceError(
                "actor, device_id and command are required")
        args = dict(args or {})
        ok, checked = self._validate(device_id, command, args)
        if not ok:
            self.audit.record("device.command.rejected", actor=actor,
                              device_id=device_id, ok=False,
                              reasons=[checked["error"]],
                              extra={"command": command})
            return {"ok": False, "device_id": device_id, "command": command,
                    "error": checked["error"]}
        record = self.outbox.enqueue(
            device_id, checked["capability"], command, checked["args"],
            actor=actor, approval_id=approval_id)
        self.audit.record("device.command.requested", actor=actor,
                          device_id=device_id, ok=True,
                          extra={"command_id": record["command_id"],
                                 "capability": checked["capability"]})
        return self._deliver(record)

    def approve_command(self, approval_id: str, *, by: str = "") -> bool:
        """Human approval for a parked command. Returns transitioned or not."""
        try:
            return self.approvals.approve(approval_id, by=by)
        except Exception:
            return False

    def deny_command(self, approval_id: str, *, by: str = "",
                     reason: str = "") -> bool:
        """Human denial for a parked command."""
        try:
            return self.approvals.deny(approval_id, by=by, reason=reason)
        except Exception:
            return False

    def command_status(self, command_id: str) -> dict[str, Any] | None:
        record = self.outbox.get(command_id)
        if record is None:
            return None
        return self._enrich(record)

    def commands_list(self, state: str | None = None,
                      limit: int = 100) -> list[dict[str, Any]]:
        """Newest-first command summaries with derived display states."""
        try:
            self.outbox._maybe_reload()
            records = sorted(self.outbox._commands.values(),
                             key=lambda r: float(r.get("created_at") or 0.0),
                             reverse=True)
        except Exception:
            return []
        out: list[dict[str, Any]] = []
        for record in records:
            view = self._enrich(dict(record))
            if state is not None and view["display_state"] != state:
                continue
            out.append(view)
            if len(out) >= max(1, limit):
                break
        return out

    @staticmethod
    def _display_state(record: dict[str, Any],
                       approval_state: str = "") -> str:
        """Operator-facing state derived from stored states (no explosion).

        Stored outbox states are the source of truth; approval coupling
        refines QUEUED into WAITING_APPROVAL/APPROVED, and SENT/ACK into
        DELIVERED.
        """
        state = str(record.get("state", ""))
        if state == "queued":
            if approval_state == "pending":
                return "WAITING_APPROVAL"
            if approval_state == "approved":
                return "APPROVED"
            return "QUEUED"
        if state in ("sent", "acknowledged"):
            return "DELIVERED"
        return state.upper()

    def _enrich(self, record: dict[str, Any]) -> dict[str, Any]:
        approval_state = ""
        approval_id = str(record.get("approval_id", ""))
        if approval_id:
            try:
                info = self.approvals.status(approval_id)
                approval_state = str((info or {}).get("state", ""))
            except Exception:
                approval_state = ""
        view = dict(record)
        view["display_state"] = self._display_state(record, approval_state)
        view["approval_state"] = approval_state
        result = record.get("result")
        if isinstance(result, dict):
            view["result_summary"] = str(result.get("result", result.get(
                "error", "")))[:200]
        elif result is not None:
            view["result_summary"] = str(result)[:200]
        else:
            view["result_summary"] = str(record.get("error", ""))[:200]
        return view

    def cancel_command(self, command_id: str, *, by: str = "",
                       reason: str = "") -> dict[str, Any]:
        return self.outbox.cancel(command_id, by=by, reason=reason)

    def outbox_status(self) -> dict[str, Any]:
        return self.outbox.depth()

    def approval_status(self, approval_id: str) -> dict[str, Any] | None:
        return self.approvals.status(approval_id)

    def audit_tail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.audit.tail(limit)

    # -- drainer ---------------------------------------------------------------

    def tick(self, max_per_tick: int = MAX_PER_TICK) -> dict[str, int]:
        """Recover, sweep, and dispatch due records. Returns counts."""
        counts = {"dispatched": 0, "completed": 0, "failed": 0,
                  "deferred": 0, "recovered": 0, "expired": 0}
        try:
            counts["recovered"] = self.outbox.recover().get("recovered", 0)
        except OutboxError:
            pass
        try:
            counts["expired"] = self.outbox.sweep().get("expired", 0)
        except OutboxError:
            pass
        try:
            due = self.outbox.claim_due()
        except OutboxError:
            return counts
        for record in due[:max(0, max_per_tick)]:
            outcome = self._deliver(record)
            if outcome.get("ok"):
                counts["completed"] += 1
            elif outcome.get("deferred"):
                counts["deferred"] += 1
            elif outcome.get("dispatched"):
                counts["dispatched"] += 1
            else:
                counts["failed"] += 1
        return counts

    def _deliver(self, record: dict[str, Any]) -> dict[str, Any]:
        """Deliver one outbox record through the existing transport."""
        command_id = str(record.get("command_id", ""))
        device_id = str(record.get("device_id", ""))
        capability = str(record.get("capability", ""))
        command = str(record.get("command", ""))
        args = dict(record.get("args") or {})
        actor = str(record.get("actor", ""))
        approval_id = str(record.get("approval_id", ""))
        try:
            live = self.outbox.get(command_id)
        except OutboxError:
            return {"ok": False, "error": "command vanished"}
        if live is None or live.get("state") not in (QUEUED, APPROVED):
            state = (live or {}).get("state", "missing")
            return {"ok": False, "command_id": command_id,
                    "deferred": state not in ("missing",),
                    "error": f"not deliverable (state={state})"}
        # Lane first: never burn a single-use approval on a dead lane,
        # and never route socket commands around a missing lane.
        if self._lane_gated(command):
            try:
                lane_live = bool(self.host.has_lane(device_id))
            except Exception:
                lane_live = False
            if not lane_live:
                self.outbox.defer(command_id, LANE_DEFER_S,
                                  detail="no live socket lane")
                return {"ok": False, "command_id": command_id,
                        "deferred": True,
                        "error": "no live socket lane (deferred)"}
        # Authorize (grant + policy + durable consume), then dispatch.
        gate = self.router.authorize(
            actor, device_id, capability, args,
            approval_token=approval_id) if self.router is not None else {
                "authorized": False, "reasons": ["no router"]}
        if not gate.get("authorized"):
            return self._handle_deny(record, list(gate.get("reasons", [])),
                                     gate.get("approval_token", ""))
        self.audit.record("device.command.authorized", actor=actor,
                          device_id=device_id, ok=True,
                          extra={"command_id": command_id,
                                 "capability": capability})
        try:
            self.outbox.transition(command_id, DISPATCHING,
                                   detail=f"actor={actor}")
        except OutboxError as exc:
            return {"ok": False, "command_id": command_id,
                    "error": str(exc)[:200]}
        try:
            reply = self._send(actor, device_id, command, capability,
                               args, approval_id)
        except Exception as exc:
            failed = self.outbox.fail(command_id, f"lane delivery failed: {exc}",
                                      retryable=True)
            return {"ok": False, "command_id": command_id,
                    "dispatched": True, "error": str(failed.get("error", ""))[:300]}
        return self._finish(record, reply)

    def _send(self, actor: str, device_id: str, command: str,
              capability: str, args: dict[str, Any],
              approval_id: str) -> dict[str, Any]:
        """Dispatch via the existing sanctioned APIs (never raw sockets)."""
        if self._lane_gated(command):
            out = self.host.send_command(actor, device_id, command, args,
                                         approval_token=approval_id)
        else:
            out = self.router.route(actor, device_id, capability, args,
                                    approval_token=approval_id)
        if not isinstance(out, dict):
            raise CommandServiceError("transport returned no result")
        return out

    def _finish(self, record: dict[str, Any],
                reply: dict[str, Any]) -> dict[str, Any]:
        """Verify a typed reply belongs to the command, then complete."""
        command_id = str(record.get("command_id", ""))
        device_id = str(record.get("device_id", ""))
        capability = str(record.get("capability", ""))
        actor = str(record.get("actor", ""))
        if (reply.get("device_id") and reply.get("device_id") != device_id) \
                or (reply.get("capability")
                    and reply.get("capability") != capability):
            failed = self.outbox.fail(
                command_id, "reply identity mismatch (fail closed)",
                retryable=False)
            return {"ok": False, "command_id": command_id,
                    "error": str(failed.get("error", ""))[:300]}
        if not reply.get("ok"):
            failed = self.outbox.fail(
                command_id, str(reply.get("error", "capability failed")),
                retryable=True)
            return {"ok": False, "command_id": command_id,
                    "dispatched": True,
                    "error": str(failed.get("error", ""))[:300]}
        try:
            self.outbox.transition(command_id, SENT, detail="reply received")
        except OutboxError as exc:
            return {"ok": False, "command_id": command_id,
                    "error": str(exc)[:200]}
        self.audit.record("device.command.delivered", actor=actor,
                          device_id=device_id, ok=True,
                          extra={"command_id": command_id,
                                 "capability": capability})
        ok, msg = self.outbox.complete(command_id, {
            "result": reply.get("result"),
            "correlation_id": reply.get("correlation_id", ""),
            "capability": capability,
            "device_id": device_id,
        })
        if not ok and "duplicate" not in msg:
            return {"ok": False, "command_id": command_id, "error": msg}
        self.audit.record("device.command.dispatched", actor="drainer",
                          device_id=device_id, ok=True,
                          extra={"command_id": command_id,
                                 "capability": capability})
        out = dict(reply)
        out["command_id"] = command_id
        return out

    def _handle_deny(self, record: dict[str, Any], reasons: list[str],
                     fresh_token: str) -> dict[str, Any]:
        """Gate denial at drain time: approval flow, deferral, or fail."""
        command_id = str(record.get("command_id", ""))
        actor = str(record.get("actor", ""))
        joined = "; ".join(reasons)
        if "needs approval" in joined or "durable approval denied" in joined:
            presented = str(record.get("approval_id", ""))
            if presented:
                try:
                    known = self.approvals.status(presented)
                except Exception:
                    known = None
                state = (known or {}).get("state", "")
                if state == "pending":
                    # Approval requested, human has not decided: wait.
                    self.outbox.defer(command_id, APPROVAL_DEFER_S,
                                      detail="awaiting approval")
                    return {"ok": False, "command_id": command_id,
                            "deferred": True, "requires_approval": True,
                            "approval_id": presented,
                            "error": joined[:300]}
                if known is None:
                    # Unknown token: hard deny, never mint on junk.
                    failed = self.outbox.fail(
                        command_id, "unknown approval token",
                        retryable=False)
                    return {"ok": False, "command_id": command_id,
                            "error": str(failed.get("error", ""))[:300]}
            # First request, or a spent/expired/denied token: mint a fresh
            # durable approval and park the command for the human.
            approval = self.approvals.request(
                actor, str(record.get("device_id", "")),
                str(record.get("capability", "")),
                dict(record.get("args") or {}), by=actor,
                reason=joined[:200])
            self._set_approval(command_id, approval["token"])
            self.outbox.defer(command_id, APPROVAL_DEFER_S,
                              detail="awaiting approval")
            self.audit.record("device.command.awaiting_approval", actor=actor,
                              device_id=str(record.get("device_id", "")),
                              ok=True, reasons=reasons,
                              extra={"command_id": command_id,
                                     "approval_id": approval["token"]})
            return {"ok": False, "command_id": command_id,
                    "deferred": True, "requires_approval": True,
                    "approval_id": approval["token"],
                    "error": joined[:300]}
        if "suspended" in joined or "not online" in joined \
                or "no live socket lane" in joined:
            self.outbox.defer(command_id, DENY_DEFER_S, detail=joined[:200])
            return {"ok": False, "command_id": command_id,
                    "deferred": True, "error": joined[:300]}
        failed = self.outbox.fail(command_id, joined, retryable=False)
        self.audit.record("device.command.denied", actor=actor,
                          device_id=str(record.get("device_id", "")),
                          ok=False, reasons=reasons,
                          extra={"command_id": command_id})
        return {"ok": False, "command_id": command_id,
                "error": str(failed.get("error", joined))[:300]}

    def _set_approval(self, command_id: str, token: str) -> None:
        record = self.outbox.get(command_id)
        if record is None or record.get("state") not in (QUEUED, APPROVED):
            return
        # Direct store update under the outbox lock (no state change).
        with self.outbox._mutate():
            live = self.outbox._commands.get(command_id)
            if live is not None and live.get("state") not in TERMINAL:
                live["approval_id"] = token
                live["updated_at"] = now()
                live.setdefault("history", []).append(
                    {"at": live["updated_at"], "event": "approval_attached",
                     "detail": token[:12] + "…"})


__all__ = ["DeviceCommandService", "CommandServiceError"]
