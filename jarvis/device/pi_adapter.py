"""Raspberry Pi node adapter: core-side facade (5.0).

Mirrors AndroidNodeAdapter's proven shape: enrollment, single-use
pairing codes, explicit trust, presence, bounded offline queues,
closed events, capability declaration. Differences are Pi-specific:
``pi-pairings.json`` / ``pi-queue.json`` files, GPIO allowlist
configuration, hardware telemetry validation, and a health model.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections import deque
from pathlib import Path
from typing import Any

from ..core.types import now
from .android import PairingError, PairingManager, PairingState
from .pi import (
    COMMAND_QUEUE_MAX,
    COMMAND_TTL_S,
    PI_ADAPTER_VERSION,
    PI_CAPABILITIES,
    PI_DEVICE_TYPE,
    PI_PLATFORM,
    PiCommandError,
    PiError,
    QueuedPiCommand,
    validate_command,
    validate_pi_event,
    validate_pi_metadata,
)

PI_QUEUE_FILENAME = "pi-queue.json"


class PiNodeAdapter:
    """Core-side facade for Raspberry Pi nodes. Wraps a DeviceFabric."""

    def __init__(self, fabric: Any, *,
                 pairing: PairingManager | None = None,
                 gpio_pins: dict[str, Any] | None = None) -> None:
        if fabric is None:
            raise PiError("PiNodeAdapter needs a DeviceFabric")
        self.fabric = fabric
        if pairing is not None:
            self.pairing = pairing
        else:
            home = getattr(fabric, "home", None)
            path = Path(home) / "pi-pairings.json" if home else None
            self.pairing = PairingManager(path=path)
        self._connected: dict[str, float] = {}
        self._queues: dict[str, deque] = {}
        self._dropped: dict[str, int] = {}
        self.gpio_pins: dict[str, dict[str, Any]] = dict(
            gpio_pins or {})
        self._load_queues()

    # -- enrollment / pairing --------------------------------------------------

    def _require_pi(self, device_id: str) -> Any:
        device = self.fabric.registry.require(device_id)
        if device.platform != PI_PLATFORM and not device.metadata.get(
                "is_pi"):
            raise PiError(f"not a raspberry pi node: {device_id}")
        return device

    def register_pi(self, name: str, metadata: dict[str, Any], *,
                    by: str = "user", owner: str = "",
                    pairing_code: str = "") -> dict[str, Any]:
        """Register a Pi node. Starts UNTRUSTED + PAIR_PENDING."""
        meta = validate_pi_metadata(metadata)
        info = self.fabric.register_device(
            name, PI_DEVICE_TYPE, by=by, platform=PI_PLATFORM,
            platform_version=meta["os"], owner=owner,
            metadata={"pi_model": meta["pi_model"],
                      "arch": meta["arch"],
                      "is_pi": True})
        self.fabric.registry.update(
            info["device_id"], node_version=meta["software_version"])
        info = self.fabric.info(info["device_id"])
        pairing = self.pairing.begin(info["device_id"], by=by,
                                     code=pairing_code)
        out = dict(info)
        out["pairing"] = pairing
        out["pairing_state"] = PairingState.PAIR_PENDING.value
        return out

    def discover_pi(self, name: str, *, by: str = "user") -> dict[str, Any]:
        return self.fabric.discover_device(name, PI_DEVICE_TYPE, by=by)

    def pair(self, device_id: str, code: str, *, by: str = "user",
             reason: str = "", node_id: str = "") -> dict[str, Any]:
        """Confirm pairing code, bind node_id, record trust decision."""
        self._require_pi(device_id)
        self.pairing.confirm(device_id, code)
        if node_id:
            device = self.fabric.registry.require(device_id)
            claimed = str(node_id)[:128]
            if device.node_id and device.node_id != claimed:
                raise PairingError(
                    f"node_id conflict: {device.node_id} != {claimed}")
            device.node_id = claimed
            self.fabric.registry.node_index[claimed] = device_id
        self.fabric.trust_device(device_id, by=by,
                                 reason=reason or "pairing code confirmed")
        return self.status(device_id)

    def pair_request_approval(self, device_id: str, code: str, *,
                              by: str = "socket-host",
                              node_id: str = "") -> dict[str, Any]:
        """Socket pairing step 1: verify the code, never trust."""
        from .model import LifecycleState
        self._require_pi(device_id)
        self.pairing.confirm(device_id, code)
        if node_id:
            device = self.fabric.registry.require(device_id)
            claimed = str(node_id)[:128]
            if device.node_id and device.node_id != claimed:
                raise PairingError(
                    f"node_id conflict: {device.node_id} != {claimed}")
            device.node_id = claimed
            self.fabric.registry.node_index[claimed] = device_id
        self.fabric.registry.transition(device_id,
                                         LifecycleState.TRUST_PENDING, by=by)
        return self.status(device_id)

    def unpair(self, device_id: str, *, by: str = "user",
               reason: str = "") -> dict[str, Any]:
        """Unpair = revoke (terminal, record kept for audit) + disconnect."""
        self._require_pi(device_id)
        self._connected.pop(device_id, None)
        self._queues.pop(device_id, None)
        self._save_queues()
        self.fabric.revoke_device(
            device_id, by=by, reason=reason or "unpaired by user")
        return self.status(device_id)

    def trust_pi(self, device_id: str, *, by: str = "user",
                 reason: str = "") -> dict[str, Any]:
        self._require_pi(device_id)
        self.pairing.cancel(device_id)
        info = self.fabric.trust_device(device_id, by=by, reason=reason)
        return self.status(device_id)

    def revoke_pi(self, device_id: str, *, by: str = "user",
                  reason: str = "") -> dict[str, Any]:
        self._require_pi(device_id)
        self._connected.pop(device_id, None)
        info = self.fabric.revoke_device(device_id, by=by, reason=reason)
        return self.status(device_id)

    def quarantine_pi(self, device_id: str, *, by: str = "user",
                      reason: str = "") -> dict[str, Any]:
        self._require_pi(device_id)
        self._connected.pop(device_id, None)
        info = self.fabric.quarantine_device(device_id, by=by, reason=reason)
        return self.status(device_id)

    def pairing_state(self, device_id: str) -> dict[str, Any]:
        self._require_pi(device_id)
        return {"device_id": device_id,
                "pairing": self.pairing.state(device_id).value}

    # -- presence ----------------------------------------------------------------

    def connect(self, device_id: str, *, by: str = "device") -> dict[str, Any]:
        """Mark the link connected; promote presence; drain queued commands."""
        self._require_pi(device_id)
        self._connected[device_id] = now()
        try:
            self.fabric.registry.mark_online(device_id)
        except Exception:
            pass
        self._bus("pi.connected", {"device_id": device_id})
        drained = self.drain(device_id)
        out = self.status(device_id)
        out["drained"] = drained
        return out

    def disconnect(self, device_id: str, *, by: str = "device",
                   reason: str = "") -> dict[str, Any]:
        self._require_pi(device_id)
        self._connected.pop(device_id, None)
        try:
            self.fabric.registry.mark_offline(
                device_id, reason=reason or "disconnect")
        except Exception:
            pass
        self._bus("pi.disconnected", {"device_id": device_id})
        return self.status(device_id)

    def is_connected(self, device_id: str) -> bool:
        return device_id in self._connected

    def heartbeat(self, device_id: str, report: dict[str, Any] | None = None,
                  *, by: str = "device") -> dict[str, Any]:
        """Heartbeat counts only while the link is connected."""
        self._require_pi(device_id)
        if not self.is_connected(device_id):
            raise PiError("node is not connected; heartbeat refused")
        telemetry = validate_pi_telemetry(dict(report or {}), device_id)
        info = self.fabric.heartbeat(device_id, telemetry, by=by)
        return {"device_id": device_id, "lifecycle": info.get("lifecycle", ""),
                "telemetry": telemetry}

    # -- capabilities --------------------------------------------------------------

    def declare_pi_capabilities(self, device_id: str,
                                declared: list[str],
                                *, by: str = "user") -> dict[str, Any]:
        """Declare the subset of PI_CAPABILITIES this node serves."""
        self._require_pi(device_id)
        granted = [c for c in declared if c in PI_CAPABILITIES]
        withheld = [c for c in declared if c not in PI_CAPABILITIES]
        device = self.fabric.registry.require(device_id)
        device.capabilities = {c: 1 for c in granted}
        try:
            self.fabric.registry.save()
        except Exception:
            pass
        return {"device_id": device_id, "granted": granted,
                "withheld": withheld}

    def configure_gpio(self, pins: dict[str, Any], *,
                       by: str = "user") -> dict[str, Any]:
        """Replace the GPIO allowlist. Empty = everything denied."""
        clean: dict[str, dict[str, Any]] = {}
        for pin, spec in (pins or {}).items():
            try:
                pin_no = int(pin)
            except (TypeError, ValueError):
                raise PiError(f"invalid gpio pin: {pin!r}")
            if not 0 <= pin_no <= 40:
                raise PiCommandError(
                    f"gpio pin out of range: {pin_no}")
            mode = str((spec or {}).get("mode", "read")).lower()
            if mode not in ("read", "write"):
                raise PiCommandError(
                    f"gpio pin {pin_no}: mode must be read|write")
            clean[str(pin_no)] = {
                "mode": mode,
                "owner": str((spec or {}).get("owner", by))[:64],
            }
        self.gpio_pins = clean
        return {"pins": sorted(clean), "by": by}

    # -- commands ------------------------------------------------------------------

    def send_command(self, actor: str, device_id: str, command: str,
                     args: dict[str, Any] | None = None,
                     approval_token: str = "") -> dict[str, Any]:
        """Send a typed command. Offline nodes queue (durable, expiring)."""
        self._require_pi(device_id)
        checked = validate_command(command, args, self.gpio_pins)
        if not self.is_connected(device_id):
            queued = self._enqueue(device_id, checked, actor)
            return {"ok": False, "queued": True, "command_id": queued.command_id,
                    "device_id": device_id, "command": command,
                    "error": "node offline: command queued (durable, expiring)"}
        device = self.fabric.registry.require(device_id)
        if not self.fabric.registry.capability_enabled(device,
                                                        checked["capability"]):
            return {"ok": False, "device_id": device_id, "command": command,
                    "error": f"capability not available on node: "
                             f"{checked['capability']}"}
        host = getattr(self, "socket_host", None)
        if host is not None and host.has_lane(device_id):
            return host.send_command(actor, device_id, command,
                                     checked["args"],
                                     approval_token=approval_token)
        return self.fabric.route_command(actor, device_id,
                                         checked["capability"],
                                         checked["args"],
                                         approval_token=approval_token)

    def _queue_path(self) -> Path | None:
        home = getattr(self.fabric, "home", None)
        if not home:
            return None
        return Path(home) / "pi-queue.json"

    def _save_queues(self) -> None:
        path = self._queue_path()
        if path is None:
            return
        payload = {"version": 1,
                   "queues": {device_id: [item.to_dict() for item in queue]
                              for device_id, queue in self._queues.items()},
                   "dropped": self._dropped}
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".pi-queue-",
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
        except OSError:
            pass

    def _load_queues(self) -> None:
        path = self._queue_path()
        if path is None or not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(raw, dict):
            return
        for device_id, items in (raw.get("queues") or {}).items():
            queue: deque = deque()
            for item in items or []:
                try:
                    queue.append(QueuedPiCommand.from_dict(item))
                except (TypeError, ValueError, KeyError):
                    continue
            while len(queue) > COMMAND_QUEUE_MAX:
                queue.popleft()
            if queue:
                self._queues[str(device_id)] = queue
        dropped = raw.get("dropped") or {}
        if isinstance(dropped, dict):
            self._dropped = {str(k): int(v) for k, v in dropped.items()
                             if isinstance(v, int)}

    def _enqueue(self, device_id: str, checked: dict[str, Any],
                 actor: str) -> QueuedPiCommand:
        queue = self._queues.setdefault(device_id, deque())
        item = QueuedPiCommand(
            device_id=device_id, command=checked["command"],
            capability=checked["capability"], args=checked["args"],
            actor=actor, expires_at=now() + COMMAND_TTL_S)
        queue.append(item)
        while len(queue) > COMMAND_QUEUE_MAX:
            queue.popleft()
            self._dropped[device_id] = self._dropped.get(device_id, 0) + 1
        self._save_queues()
        return item

    def drain(self, device_id: str) -> dict[str, Any]:
        """Dispatch queued commands that are still fresh. Stale ones rejected."""
        queue = self._queues.get(device_id, deque())
        if not queue:
            return {"dispatched": [], "rejected": [],
                    "dropped_while_offline": self._dropped.get(device_id, 0)}
        if not self.is_connected(device_id):
            return {"dispatched": [], "rejected": [],
                    "dropped_while_offline": self._dropped.get(device_id, 0),
                    "error": "node offline: queue held"}
        stamp = now()
        dispatched: list[str] = []
        rejected: list[dict[str, str]] = []
        remaining: deque = deque()
        for item in queue:
            if item.expired(stamp):
                rejected.append({"command_id": item.command_id,
                                 "command": item.command,
                                 "reason": "expired while offline"})
                continue
            try:
                host = getattr(self, "socket_host", None)
                if host is not None and host.has_lane(device_id):
                    result = host.send_command(item.actor, device_id,
                                               item.command, item.args)
                else:
                    result = self.fabric.route_command(
                        item.actor, device_id, item.capability, item.args)
            except Exception as exc:
                rejected.append({"command_id": item.command_id,
                                 "command": item.command,
                                 "reason": f"routing refused: {exc}"})
                continue
            if result.get("ok"):
                dispatched.append(item.command_id)
            else:
                remaining.append(item)
        self._queues[device_id] = remaining
        self._save_queues()
        return {"dispatched": dispatched, "rejected": rejected,
                "dropped_while_offline": self._dropped.get(device_id, 0)}

    def queue_depth(self, device_id: str) -> dict[str, Any]:
        queue = self._queues.get(device_id, deque())
        return {"device_id": device_id, "queued": len(queue),
                "dropped_while_offline": self._dropped.get(device_id, 0)}

    # -- events ----------------------------------------------------------------------

    def ingest_event(self, device_id: str, type: str,
                     payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Validate and fan out a Pi event. Untrusted text stays data."""
        self._require_pi(device_id)
        checked = validate_pi_event(type, payload)
        summary = sanitize_pi_text(
            f"{type} from {device_id}: "
            + str(payload.get("text", payload.get("summary", "")))[:120])
        self._bus(type, {"device_id": device_id, **payload})
        dots = self.fabric.route_dots({"type": type, "entity": device_id,
                                       "summary": summary})
        return {"ok": True, "dots": dots}

    # -- introspection -------------------------------------------------------------------

    def status(self, device_id: str) -> dict[str, Any]:
        info = self.fabric.info(device_id)
        info["pairing_state"] = self.pairing.state(device_id).value
        info["connected"] = self.is_connected(device_id)
        info["queue"] = self.queue_depth(device_id)
        info["is_pi"] = True
        return info

    def list_pi(self) -> list[dict[str, Any]]:
        out = []
        for device in self.fabric.registry.devices.values():
            if device.platform == PI_PLATFORM or device.metadata.get("is_pi"):
                out.append(self.status(device.device_id))
        return out

    def doctor(self) -> list[dict[str, Any]]:
        checks = [
            {"name": "pi-adapter", "ok": True,
             "detail": f"adapter v{PI_ADAPTER_VERSION}"},
            {"name": "registry", "ok": self.fabric.registry is not None,
             "detail": f"{len(self.fabric.registry.devices)} devices"},
            {"name": "pairing",
             "ok": True,
             "detail": f"{len(self.pairing.pending_devices())} pending"},
            {"name": "gpio-allowlist",
             "ok": True,
             "detail": f"{len(self.gpio_pins)} pins configured"},
        ]
        return checks

    # -- internal --------------------------------------------------------------------------

    def _bus(self, type: str, payload: dict[str, Any]) -> None:
        bus = getattr(self.fabric, "bus", None)
        if bus is None:
            return
        try:
            from ..events.store import Event
            bus.publish(Event(type=type, payload=payload,
                              source="pi-node"))
        except Exception:
            pass

def validate_pi_telemetry(report: dict[str, Any],
                          device_id: str) -> dict[str, Any]:
    """Validate typed Pi telemetry. Ranges checked, values never invented."""
    out: dict[str, Any] = {}
    for key, low, high in (("cpu_percent", 0.0, 100.0),
                           ("memory_percent", 0.0, 100.0),
                           ("disk_percent", 0.0, 100.0),
                           ("temperature_c", -40.0, 120.0),
                           ("uptime_s", 0.0, 1e9)):
        if key in report:
            try:
                value = float(report[key])
            except (TypeError, ValueError):
                raise PiError(f"telemetry {key} is not numeric")
            if not low <= value <= high:
                raise PiError(f"telemetry {key} out of range")
            out[key] = value
    if "network" in report:
        network = report["network"]
        if not isinstance(network, str) or len(network) > 64:
            raise PiError("telemetry network must be a short string")
        out["network"] = network
    out["device_id"] = device_id
    return out


def pi_health(telemetry: dict[str, Any]) -> dict[str, Any]:
    """HEALTHY/DEGRADED/OFFLINE/UNKNOWN from telemetry. Facts only."""
    temp = telemetry.get("temperature_c")
    disk = telemetry.get("disk_percent")
    cpu = telemetry.get("cpu_percent")
    mem = telemetry.get("memory_percent")
    reasons = []
    if temp is not None and temp >= 80.0:
        reasons.append(f"temperature {temp:.1f}C >= 80")
    if disk is not None and disk >= 95.0:
        reasons.append(f"disk {disk:.1f}% >= 95")
    if cpu is not None and cpu >= 95.0:
        reasons.append(f"cpu {cpu:.1f}% >= 95")
    if mem is not None and mem >= 95.0:
        reasons.append(f"memory {mem:.1f}% >= 95")
    if not telemetry:
        return {"health": "UNKNOWN", "reasons": ["no telemetry"]}
    if reasons:
        return {"health": "DEGRADED", "reasons": reasons}
    return {"health": "HEALTHY", "reasons": []}


def sanitize_pi_text(text: str, limit: int = 500) -> str:
    """Quote Pi-supplied text as untrusted data for dots/summaries."""
    cleaned = str(text or "")
    for token in ("password", "secret", "token", "api_key", "private_key"):
        if token in cleaned.lower():
            return "[redacted: possible credential]"
    return cleaned[:limit]


__all__ = [
    "PiNodeAdapter",
    "PiError",
    "pi_health",
    "sanitize_pi_text",
    "validate_pi_telemetry",
]
