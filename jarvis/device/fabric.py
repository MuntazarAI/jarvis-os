"""DeviceFabric: first-class JARVIS subsystem owning the device mesh.

The fabric is the ONLY path from agents/missions/tasks to node capabilities:
all execution flows through ``DeviceRouter`` (PolicyEngine-gated). The fabric
itself never auto-executes: registration, trust, heartbeats and commands are
explicit calls. World Model and Spatial Palace are *mirrors* (representation
only); the registry is the source of truth for connectivity/lifecycle.

Integrations (all optional/late-bindable, mirroring LiveIntelligenceService):
world_registry, spatial, proactive, dots, missions, palace (memory), bus,
policy, transport.
"""

from __future__ import annotations

import platform
from pathlib import Path
from typing import Any

from ..core.types import now
from .capabilities import Capability
from .identity import AuthContext, NodeIdentity, current_limitation
from .model import FABRIC_VERSION, PROTOCOL_VERSION, LifecycleState, TrustState
from .protocol import FabricMessage, MessageType
from .registry import DeviceRegistry, RegistryError
from .router import DeviceRouter
from .security import check_text, sanitize_text, scrub
from .telemetry import Telemetry
from .transport import InProcessTransport, LocalNode, Transport

LOCAL_CAPABILITIES = ("system.status", "system.telemetry")


class FabricError(RuntimeError):
    """Raised when the fabric is misused (unbound dependency, bad input)."""


class DeviceFabric:
    def __init__(self, home: str | Path, *, config: Any | None = None,
                 registry: DeviceRegistry | None = None,
                 policy: Any | None = None,
                 world_registry: Any | None = None,
                 spatial: Any | None = None,
                 proactive: Any | None = None,
                 dots: Any | None = None,
                 missions: Any | None = None,
                 palace: Any | None = None,
                 bus: Any | None = None,
                 transport: Transport | None = None) -> None:
        self.home = Path(home)
        self.config = config
        state_name = getattr(config, "state_path", "device-fabric.json") or "device-fabric.json"
        self.registry = registry or DeviceRegistry(
            self.home / state_name,
            heartbeat_timeout_s=float(getattr(config, "heartbeat_timeout_s", 120.0) or 120.0),
            max_devices=int(getattr(config, "max_devices", 64) or 64),
        )
        self.policy = policy
        self.world = world_registry
        self.spatial = spatial
        self.proactive = proactive
        self.dots = dots
        self.missions = missions
        self.palace = palace
        self.bus = bus
        self.transport = transport or InProcessTransport()
        self.local_device_id: str | None = self._find_local()
        self.router = DeviceRouter(self.registry, self.policy, self.transport,
                                   core_node_id=self.local_node_id())

    # -- local node ------------------------------------------------------

    def _find_local(self) -> str | None:
        for device in self.registry.list():
            if device.metadata.get("is_local"):
                return device.device_id
        return None

    def local_node_id(self) -> str:
        if self.local_device_id:
            device = self.registry.get(self.local_device_id)
            if device is not None and device.node_id:
                return device.node_id
        return "core"

    def register_local(self, *, name: str = "", by: str = "user") -> dict[str, Any]:
        """Enroll this machine as the local node (explicit; never automatic)."""
        if self.local_device_id:
            return self.info(self.local_device_id)
        host = platform.node() or "local"
        device = self.registry.register(
            name or host, self._local_type(),
            platform=platform.system(), platform_version=platform.release(),
            architecture=platform.machine(), hostname=host,
            network=self.transport.network_name or "",
            metadata={"is_local": True}, by=by,
        )
        device.node_id = device.node_id or f"node-local-{device.device_id}"
        self.registry.node_index[device.node_id] = device.device_id
        self.registry.declare_capabilities(device.device_id, [
            Capability(name="system.status", version=1,
                       title="Local system status",
                       description="Read-only host identity and fabric counters.",
                       risk=0.1, required_permissions=["device.system.status"],
                       read_only=True),
            Capability(name="system.telemetry", version=1,
                       title="Local system telemetry",
                       description="Read-only host telemetry snapshot.",
                       risk=0.1, required_permissions=["device.system.telemetry"],
                       read_only=True),
        ])
        # The local process is JARVIS itself: trust is explicit, recorded,
        # and bound to the local-process auth method (not to the LAN).
        self.registry.set_trust(
            device.device_id, True, by=by, reason="local node enrollment",
            auth=AuthContext(method="local-process", verified=True,
                             verified_by=by, verified_at=now(),
                             note="same process/machine as the core"),
        )
        self.registry.mark_online(device.device_id)
        self.local_device_id = device.device_id
        self.router.core_node_id = self.local_node_id()
        self._bind_local_handlers(device)
        self._after_change(device.device_id, "device.registered",
                           f"local node {device.name} enrolled", by=by,
                           remember=True, notify=True)
        self.registry.save()
        return self.info(device.device_id)

    @staticmethod
    def _local_type() -> str:
        system = platform.system().lower()
        if "darwin" in system or "windows" in system or "linux" in system:
            return "laptop"
        return "unknown"

    def _bind_local_handlers(self, device: Any) -> None:
        if not isinstance(self.transport, InProcessTransport):
            return
        node = LocalNode(device.node_id or device.device_id)
        fabric = self

        def _status(msg: FabricMessage) -> FabricMessage:
            return FabricMessage(
                sender_node=node.node_id, recipient_node=msg.sender_node,
                message_type=MessageType.COMMAND_RESULT.value,
                correlation_id=msg.message_id,
                payload={"ok": True, "result": {
                    "host": platform.node(), "system": platform.system(),
                    "release": platform.release(), "machine": platform.machine(),
                    "devices": fabric.registry.counts(),
                    "fabric_version": FABRIC_VERSION,
                }},
            )

        def _telemetry(msg: FabricMessage) -> FabricMessage:
            return FabricMessage(
                sender_node=node.node_id, recipient_node=msg.sender_node,
                message_type=MessageType.COMMAND_RESULT.value,
                correlation_id=msg.message_id,
                payload={"ok": True, "result": {
                    "online": True, "node_version": "3.8",
                    "source": "device-fabric-local",
                }},
            )

        node.on("system.status", _status)
        node.on("system.telemetry", _telemetry)
        self.transport.register_node(node)

    # -- enrollment ------------------------------------------------------

    def register_device(self, name: str, device_type: str = "unknown", *,
                        by: str = "user", **fields: Any) -> dict[str, Any]:
        device = self.registry.register(name, device_type, by=by, **fields)
        self._after_change(device.device_id, "device.registered",
                           f"device {device.name} registered ({device.device_type})",
                           by=by, remember=True, notify=True)
        return self.info(device.device_id)

    def discover_device(self, name: str, device_type: str = "unknown",
                        *, by: str = "user") -> dict[str, Any]:
        device = self.registry.discover(name, device_type, by=by)
        self._emit("device.discovered", {"device_id": device.device_id,
                                         "name": device.name})
        return self.info(device.device_id)

    def unregister_device(self, device_id: str, *, by: str = "user") -> bool:
        device = self.registry.get(device_id)
        name = device.name if device else device_id
        ok = self.registry.unregister(device_id, by=by)
        if ok:
            if self.local_device_id == device_id:
                self.local_device_id = None
            self._emit("device.unregistered", {"device_id": device_id,
                                               "name": name, "by": by})
        return ok

    # -- trust / lifecycle -------------------------------------------------

    def trust_device(self, device_id: str, *, by: str = "user",
                     reason: str = "") -> dict[str, Any]:
        device = self.registry.require(device_id)
        if device.metadata.get("is_local"):
            raise FabricError("local node trust is managed by enrollment")
        self.registry.set_trust(device_id, True, by=by, reason=reason,
                                auth=AuthContext(method="explicit-approval",
                                                 verified=True, verified_by=by,
                                                 verified_at=now(),
                                                 note=reason[:200]))
        return self._after_change(device_id, "device.trust_changed",
                                  f"device {device.name} trusted by {by}",
                                  by=by, remember=True, notify=True)

    def distrust_device(self, device_id: str, *, by: str = "user",
                        reason: str = "") -> dict[str, Any]:
        self.registry.set_trust(device_id, False, by=by, reason=reason)
        return self._after_change(device_id, "device.trust_changed",
                                  f"device trust revoked (pending) by {by}",
                                  by=by, remember=True, notify=True)

    def revoke_device(self, device_id: str, *, by: str = "user",
                      reason: str = "") -> dict[str, Any]:
        device = self.registry.require(device_id)
        if device.metadata.get("is_local"):
            raise FabricError("local node cannot be revoked")
        self.registry.revoke(device_id, by=by, reason=reason)
        return self._after_change(device_id, "device.revoked",
                                  f"device {device.name} revoked by {by}",
                                  by=by, remember=True, notify=True)

    def quarantine_device(self, device_id: str, *, by: str = "user",
                          reason: str = "") -> dict[str, Any]:
        self.registry.quarantine(device_id, by=by, reason=reason)
        device = self.registry.require(device_id)
        return self._after_change(device_id, "device.quarantined",
                                  f"device {device.name} quarantined by {by}",
                                  by=by, remember=True, notify=True)

    def release_device(self, device_id: str, *, by: str = "user") -> dict[str, Any]:
        self.registry.release(device_id, by=by)
        device = self.registry.require(device_id)
        return self._after_change(device_id, "device.trust_changed",
                                  f"device {device.name} released for re-evaluation",
                                  by=by, remember=False, notify=True)

    def enable_device(self, device_id: str, *, by: str = "user") -> dict[str, Any]:
        return self.release_device(device_id, by=by)

    def disable_device(self, device_id: str, *, by: str = "user",
                       reason: str = "") -> dict[str, Any]:
        device = self.registry.require(device_id)
        if device.metadata.get("is_local"):
            raise FabricError("local node cannot be disabled")
        self.registry.disable(device_id, by=by, reason=reason)
        return self._after_change(device_id, "device.disabled",
                                  f"device {device.name} disabled by {by}",
                                  by=by, remember=False, notify=True)

    # -- presence ----------------------------------------------------------

    def heartbeat(self, device_id: str,
                  telemetry: dict[str, Any] | Telemetry | None = None,
                  *, by: str = "device") -> dict[str, Any]:
        before = self.registry.require(device_id).lifecycle
        device = self.registry.heartbeat(device_id, telemetry)
        self._emit("device.heartbeat",
                   {"device_id": device_id, "name": device.name,
                    "lifecycle": device.lifecycle.value},
                   dedup=f"hb:{device_id}:{int(now() // 60)}")
        if before != device.lifecycle and device.lifecycle == LifecycleState.ONLINE:
            self._after_change(device_id, "device.online",
                               f"device {device.name} online", by=by,
                               remember=False, notify=False)
        return self.info(device_id)

    def sweep(self) -> list[str]:
        """Mark heartbeat-timed-out nodes OFFLINE. Explicit; no threads."""
        changed = self.registry.sweep_timeouts()
        for device_id in changed:
            device = self.registry.get(device_id)
            name = device.name if device else device_id
            self._after_change(device_id, "device.offline",
                               f"device {name} offline (heartbeat timeout)",
                               remember=False, notify=False)
        return changed

    # -- capabilities ------------------------------------------------------

    def declare_capabilities(self, device_id: str,
                             caps: list[dict[str, Any] | Capability],
                             *, by: str = "user") -> dict[str, Any]:
        device = self.registry.declare_capabilities(device_id, caps)
        self._sync_world(device)
        self._emit("device.capability_changed",
                   {"device_id": device_id, "name": device.name,
                    "capabilities": sorted(device.capabilities), "by": by})
        return self.info(device_id)

    def set_capability_enabled(self, device_id: str, capability: str,
                               enabled: bool, *, by: str = "user") -> dict[str, Any]:
        self.registry.set_capability_enabled(device_id, capability, enabled)
        device = self.registry.require(device_id)
        self._emit("device.capability_changed",
                   {"device_id": device_id, "name": device.name,
                    "capability": capability, "enabled": enabled, "by": by})
        return self.info(device_id)

    def set_location(self, device_id: str, room: str, *,
                     by: str = "user") -> dict[str, Any]:
        """Explicit location only. Empty room clears to UNKNOWN. Never guessed."""
        device = self.registry.update(device_id, location=(room or "")[:80])
        self._sync_world(device)
        self._sync_spatial(device)
        self._emit("device.location_changed",
                   {"device_id": device_id, "name": device.name,
                    "location": device.location or "UNKNOWN", "by": by})
        return self.info(device_id)

    # -- command routing -----------------------------------------------------

    def route_command(self, actor: str, device_id: str, capability: str,
                      args: dict[str, Any] | None = None,
                      approval_token: str = "") -> dict[str, Any]:
        if self.policy is None:
            raise FabricError("no policy engine bound: routing refused")
        self.sweep()
        result = self.router.route(actor, device_id, capability,
                                   args=args, approval_token=approval_token)
        status = "completed" if result["ok"] else "failed"
        self._emit(f"device.command_{status}",
                   {"device_id": device_id, "capability": capability,
                    "actor": actor, "ok": result["ok"],
                    "error": result.get("error", "")[:200]})
        return result

    # -- dots / proactive / memory -------------------------------------------

    def route_dots(self, event: dict[str, Any]) -> list[str]:
        if self.dots is None:
            return []
        scan = check_text(str(event.get("summary", "")))
        if not scan["clean"]:
            return []
        try:
            return list(self.dots.route_event(event))
        except Exception:
            return []

    def remember_fact(self, text: str, *, confidence: float = 0.7) -> Any:
        if self.palace is None:
            raise FabricError("no memory palace bound")
        return self.palace.store_fact(
            sanitize_text(text, 500), source="device-fabric",
            confidence=confidence,
            metadata={"origin": "observed"})

    # -- read ------------------------------------------------------------------

    def info(self, device_id: str) -> dict[str, Any]:
        device = self.registry.require(device_id)
        data = device.to_dict()
        data["connectivity"] = device.connectivity
        data["can_execute"] = device.can_execute()
        data["telemetry"] = scrub(self.registry.telemetry.get(device_id, {}))
        data["disabled_capabilities"] = device.metadata.get("disabled_capabilities", [])
        return data

    def list_devices(self, **filters: Any) -> list[dict[str, Any]]:
        return [self.info(d.device_id) for d in self.registry.list(**filters)]

    def describe(self, device_id: str) -> str:
        info = self.info(device_id)
        lines = [
            f"{info['name']} ({info['device_type']})",
            f"lifecycle={info['lifecycle']} trust={info['trust']} "
            f"connectivity={info['connectivity']}",
            f"capabilities={sorted(info['capabilities'])}",
            f"location={info['location'] or 'UNKNOWN'}",
        ]
        return sanitize_text("\n".join(lines), 1000)

    # -- status / doctor / persistence -------------------------------------------

    def status(self) -> dict[str, Any]:
        info = self.registry.status()
        info["fabric_version"] = FABRIC_VERSION
        info["protocol_version"] = PROTOCOL_VERSION
        info["transport"] = self.transport.status()
        info["transports_available"] = ["in-process"]
        info["local_device_id"] = self.local_device_id
        info["policy_bound"] = self.policy is not None
        info["world_bound"] = self.world is not None
        info["spatial_bound"] = self.spatial is not None
        info["trust_limitation"] = current_limitation()
        return info

    def doctor(self) -> list[dict[str, Any]]:
        checks: list[dict[str, Any]] = []
        checks.append({"name": "registry", "ok": True,
                       "detail": f"{len(self.registry.devices)} device(s)"})
        try:
            self.registry.path.parent.mkdir(parents=True, exist_ok=True)
            checks.append({"name": "persistence", "ok": True,
                           "detail": str(self.registry.path)})
        except OSError as exc:
            checks.append({"name": "persistence", "ok": False, "detail": str(exc)[:120]})
        checks.append({"name": "protocol", "ok": True,
                       "detail": "v1 typed messages; no remote execution"})
        checks.append({"name": "policy", "ok": self.policy is not None,
                       "detail": "PolicyEngine bound" if self.policy is not None
                       else "no policy engine: routing refused"})
        checks.append({"name": "world", "ok": True,
                       "detail": "bound" if self.world is not None else "not bound (mirroring off)"})
        checks.append({"name": "spatial", "ok": True,
                       "detail": "bound" if self.spatial is not None else "not bound (mirroring off)"})
        checks.append({"name": "transport", "ok": True,
                       "detail": f"{self.transport.name} (no listeners, no threads)"})
        if self.registry.errors:
            checks.append({"name": "load_errors", "ok": True,
                           "detail": f"{len(self.registry.errors)} recovered load error(s)"})
        return checks

    def save(self) -> None:
        self.registry.save()

    persist = save

    # -- internals ---------------------------------------------------------------

    def _emit(self, type: str, payload: dict[str, Any],
              dedup: str = "") -> None:
        if self.bus is None:
            return
        try:
            from ..events.store import Event
            self.bus.publish(Event(type=type, payload=scrub(payload),
                                   dedup_key=dedup))
        except Exception:
            pass

    def _notify_proactive(self, summary: str, entity: str,
                          payload: dict[str, Any]) -> None:
        if self.proactive is None:
            return
        try:
            from ..proactive.engine import ProactiveEvent
            event = ProactiveEvent(
                type="world_changed", source="device-fabric", entity=entity,
                summary=summary, payload=scrub(payload), confidence=0.6,
                provenance={"observer": "device-fabric"}, trusted=False)
            self.proactive.notify(event)
        except Exception:
            pass

    def _after_change(self, device_id: str, event_type: str, summary: str,
                      *, by: str = "", remember: bool = False,
                      notify: bool = False) -> dict[str, Any]:
        device = self.registry.require(device_id)
        self._sync_world(device)
        self._sync_spatial(device)
        payload = {"device_id": device_id, "name": device.name,
                   "lifecycle": device.lifecycle.value,
                   "trust": device.trust.value, "by": by}
        self._emit(event_type, payload)
        self.route_dots({"type": event_type, "entity": device.name,
                         "summary": summary})
        if notify:
            self._notify_proactive(summary, device.name, payload)
        if remember and self.palace is not None:
            try:
                self.remember_fact(f"{summary} (trust={device.trust.value})")
            except Exception:
                pass
        return self.info(device_id)

    def _sync_world(self, device: Any) -> None:
        if self.world is None:
            return
        try:
            entity, _ = self.world.upsert_entity(
                "device", device.name,
                state={"lifecycle": device.lifecycle.value,
                       "trust": device.trust.value,
                       "connectivity": device.connectivity,
                       "last_seen": device.last_seen,
                       "node_version": device.node_version,
                       "network": device.network},
                attributes={"device_id": device.device_id,
                            "node_id": device.node_id,
                            "device_type": device.device_type,
                            "platform": device.platform,
                            "capabilities": sorted(device.capabilities)},
                provenance={"observer": "device-fabric",
                            "source": "device-registry"},
                confidence=0.9)
            if device.network:
                net, _ = self.world.upsert_entity(
                    "network", device.network, provenance={"observer": "device-fabric"},
                    confidence=0.7)
                self.world.relate(entity.id, "connected_to", net.id,
                                  confidence=0.7,
                                  provenance={"observer": "device-fabric"})
            if device.location:
                loc, _ = self.world.upsert_entity(
                    "location", device.location,
                    provenance={"observer": "device-fabric"}, confidence=0.7)
                self.world.relate(entity.id, "located_at", loc.id,
                                  confidence=0.7,
                                  provenance={"observer": "device-fabric"})
            if device.owner:
                owner, _ = self.world.upsert_entity(
                    "person", device.owner,
                    provenance={"observer": "device-fabric"}, confidence=0.6)
                self.world.relate(owner.id, "owns", entity.id,
                                  confidence=0.6,
                                  provenance={"observer": "device-fabric"})
        except Exception:
            pass

    def _sync_spatial(self, device: Any) -> None:
        if self.spatial is None:
            return
        try:
            parent = None
            if device.location:
                try:
                    room = self.spatial.add_node("room", device.location,
                                                 confidence=0.7,
                                                 provenance={"observer": "device-fabric"})
                    parent = room.id
                except Exception:
                    parent = None
            self.spatial.add_node(
                "object", device.name,
                parent_id=parent,
                attributes={"device_id": device.device_id,
                            "device_type": device.device_type,
                            "node_id": device.node_id},
                confidence=0.8,
                provenance={"observer": "device-fabric",
                            "device_id": device.device_id})
        except Exception:
            pass
