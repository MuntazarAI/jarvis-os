"""Policy-gated command router for the device fabric.

Sanctioned flow (mirrors the orchestrator's ``_gated_tool`` — no bypasses)::

    Agent / Mission / Task
            v
    PolicyEngine.evaluate(actor, ActionPlan)
            v
    Device Fabric (this router)
            v
    trust + lifecycle + capability checks
            v
    transport -> node -> capability handler
            v
    scrubbed, injection-scanned result

Every attempt is audited. Revoked/quarantined/offline/untrusted nodes can
never execute. Emergency stop blocks all routing. Approvals use the same
``request_approval`` / ``approved`` token flow as tools.
"""

from __future__ import annotations

from typing import Any

from ..core.types import ActionPlan, RiskLevel
from .model import Device
from .protocol import FabricMessage, MessageType
from .registry import DeviceRegistry
from .security import audit_record, check_text, sanitize_text, scrub
from .transport import Transport, TransportError


class RoutingError(RuntimeError):
    """Raised when a command cannot be routed (misuse, not policy)."""


class DeviceRouter:
    def __init__(self, registry: DeviceRegistry, policy: Any,
                 transport: Transport, *, core_node_id: str = "",
                 grant_store: Any = None,
                 approval_store: Any = None) -> None:
        self.registry = registry
        self.policy = policy
        self.transport = transport
        self.core_node_id = core_node_id
        #: Optional DeviceGrantStore (4.2 persistent grants). When attached,
        #: every authorization additionally requires an active grant —
        #: there is no path through authorize() around it.
        self.grant_store = grant_store
        #: Optional ApprovalStore (4.2 durable tokens). Consumed atomically
        #: here so a token authorizes exactly one call, cross-process.
        self.approval_store = approval_store
        self.audit: list[dict[str, Any]] = []

    def route(self, actor: str, device_id: str, capability: str,
              args: dict[str, Any] | None = None,
              approval_token: str = "") -> dict[str, Any]:
        """Route one capability command. Never raises for policy denials."""
        args = dict(args or {})
        authorized = self.authorize(actor, device_id, capability, args,
                                    approval_token=approval_token)
        if not authorized["authorized"]:
            return self._deny(actor, device_id, capability, args,
                              authorized["reasons"],
                              decision=authorized.get("decision"),
                              approval_token=authorized.get("approval_token"))
        device = authorized["device"]
        # 5. Dispatch over the transport to the node's handler.
        message = self.build_command_message(actor, device, capability, args)
        try:
            reply = self.transport.send(message)
        except (TransportError, Exception) as exc:
            return self._deny(actor, device_id, capability, args,
                              [f"transport delivery failed: {exc}"])
        if reply is None:
            return self._deny(actor, device_id, capability, args,
                              ["transport returned no reply"])
        return self.finish(actor, device, capability, message, reply)

    def authorize(self, actor: str, device_id: str, capability: str,
                  args: dict[str, Any] | None = None,
                  approval_token: str = "") -> dict[str, Any]:
        """Steps 1-4 of route(): e-stop, device, capability, policy.

        Returns ``{"authorized": bool, "reasons": [...], "device": Device
        | None, "decision": PolicyDecision | None, "approval_token": str}``.
        Never raises for policy denials. Async transports (socket poll)
        authorize here, deliver later, and finalize via finish().
        """
        args = dict(args or {})
        denied: dict[str, Any] = {"authorized": False, "reasons": [],
                                  "device": None, "decision": None,
                                  "approval_token": ""}
        # 1. Emergency stop blocks everything, before any other work.
        if self.policy is not None and hasattr(self.policy, "_emergency_stop"):
            try:
                if self.policy._emergency_stop():
                    denied["reasons"] = [
                        "EMERGENCY STOP engaged — all device actions blocked"]
                    return denied
            except Exception:
                pass
        # 2. Device must exist and be allowed to execute.
        try:
            device = self.registry.require(device_id)
        except Exception:
            denied["reasons"] = [f"unknown device: {device_id}"]
            return denied
        denied["device"] = device
        if not device.can_execute():
            denied["reasons"] = [device.block_reason() or "device cannot execute"]
            return denied
        # 3. Capability must be declared and enabled on that node.
        if capability not in device.capabilities:
            denied["reasons"] = [f"capability not declared by node: {capability}"]
            return denied
        if not self.registry.capability_enabled(device, capability):
            denied["reasons"] = [f"capability disabled on node: {capability}"]
            return denied
        # 3b. Persistent device grant (4.2). Attached stores deny
        # anything without an active grant — fail closed, before policy.
        if self.grant_store is not None:
            try:
                allowed, why = self.grant_store.is_allowed(
                    actor, device_id, capability)
            except Exception as exc:
                denied["reasons"] = [
                    f"device grant check failed (fail closed): {exc}"[:160]]
                return denied
            if not allowed:
                denied["reasons"] = [f"denied by device grant: {why}"[:200]]
                return denied
        # 4. PolicyEngine is authoritative.
        risk = self._capability_risk(device, capability)
        plan = ActionPlan(
            action=f"device.{capability} {device.name}".strip(),
            args={"device_id": device_id, "capability": capability,
                  "args": scrub(args)},
            required_permissions=[f"device.{capability}"],
            risk=RiskLevel.from_score(risk),
        )
        decision = self.policy.evaluate(actor, plan)
        denied["decision"] = decision
        if not decision.allow:
            denied["reasons"] = [
                f"blocked by policy: {'; '.join(decision.reasons)}"]
            return denied
        if decision.requires_approval:
            if approval_token and self.policy.approved(approval_token):
                approval_token = ""  # in-memory approval (compat path)
            elif approval_token and self.approval_store is not None and self._consume_durable(
                    actor, device_id, capability, args, approval_token):
                approval_token = ""  # durable token consumed: single use
            elif approval_token and self.approval_store is not None:
                denied["reasons"] = [self._durable_deny_reason]
                return denied
            else:
                token = self.policy.request_approval(actor, plan, decision)
                denied["reasons"] = [f"needs approval (token {token})"]
                denied["approval_token"] = token
                return denied
        return {"authorized": True, "reasons": [], "device": device,
                "decision": decision, "approval_token": approval_token}

    def _consume_durable(self, actor: str, device_id: str, capability: str,
                         args: dict[str, Any], approval_token: str) -> bool:
        """Consume a durable approval iff bound to this exact call."""
        self._durable_deny_reason = "durable approval rejected"
        if self.approval_store is None:
            self._durable_deny_reason = "no approval store attached"
            return False
        try:
            ok, reason = self.approval_store.consume(
                approval_token, actor=actor, device_id=device_id,
                capability=capability, args=args)
        except Exception as exc:
            self._durable_deny_reason = (
                f"approval consume failed (fail closed): {exc}"[:160])
            return False
        if not ok:
            self._durable_deny_reason = f"durable approval denied: {reason}"[:200]
        return ok

    def build_command_message(self, actor: str, device: Device,
                              capability: str,
                              args: dict[str, Any]) -> FabricMessage:
        """Build (and validate) the COMMAND_REQUEST for an authorized call."""
        message = FabricMessage(
            sender_node=self.core_node_id or "core",
            recipient_node=device.node_id or device.device_id,
            message_type=MessageType.COMMAND_REQUEST.value,
            capability=capability,
            payload={"device_id": device.device_id, "args": scrub(args)},
            provenance={"observer": "device-fabric", "actor": actor},
        )
        message.validate()
        return message

    def finish(self, actor: str, device: Device, capability: str,
               message: FabricMessage, reply: FabricMessage) -> dict[str, Any]:
        """Turn a COMMAND_RESULT reply into the audited result dict."""
        payload = reply.payload if isinstance(reply.payload, dict) else {}
        result_text = str(payload.get("result", payload.get("output", "")))
        scan = check_text(result_text)
        out: dict[str, Any] = {
            "ok": bool(payload.get("ok", False)),
            "device_id": device.device_id,
            "capability": capability,
            "result": sanitize_text(result_text, 2000),
            "injection": None if scan["clean"] else scan,
            "correlation_id": reply.correlation_id or message.message_id,
        }
        if not out["ok"]:
            out["error"] = str(payload.get("error", "capability failed"))[:500]
        self._audit(actor, device.device_id, capability, out["ok"],
                    ["routed"] if out["ok"] else [out.get("error", "failed")])
        return out

    def _capability_risk(self, device: Device, capability: str) -> float:
        # Device record stores name->version only; risk catalog lives here.
        # Unknown capabilities default to HIGH-ish: never assume safe.
        return 0.75

    def _deny(self, actor: str, device_id: str, capability: str,
              args: dict[str, Any], reasons: list[str],
              decision: Any = None, approval_token: str = "") -> dict[str, Any]:
        self._audit(actor, device_id, capability, False, reasons)
        out: dict[str, Any] = {
            "ok": False,
            "device_id": device_id,
            "capability": capability,
            "error": "; ".join(reasons)[:500],
            "requires_approval": False,
        }
        if decision is not None:
            out["policy"] = decision.to_dict() if hasattr(decision, "to_dict") else {}
        if approval_token:
            out["approval_token"] = approval_token
            out["requires_approval"] = True
        return out

    def _audit(self, actor: str, device_id: str, capability: str,
               ok: bool, reasons: list[str]) -> None:
        self.audit.append(audit_record("device:command", actor=actor,
                                       device_id=device_id, ok=ok,
                                       reasons=reasons,
                                       extra={"capability": capability}))
        if len(self.audit) > 200:
            self.audit = self.audit[-200:]
