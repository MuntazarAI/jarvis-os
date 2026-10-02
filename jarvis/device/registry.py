"""Persistent device registry for the fabric.

Owns device records, lifecycle transitions, heartbeats, offline detection,
capability declarations, and trust updates. State survives restart via
atomic JSON persistence; corrupt files recover to empty (the error is
recorded, never silent); corrupt entries are skipped individually.

Identity conflicts are never silently overwritten: registering a known
``device_id`` with a *different* ``node_id`` raises ``RegistryError``.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from ..core.types import now
from .capabilities import Capability, CapabilityRegistry
from .identity import AuthContext
from .model import (
    Device,
    DeviceError,
    LifecycleState,
    TrustState,
    check_transition,
    validate_device_name,
    validate_device_type,
)
from .security import audit_record, reject_secrets, scrub
from .telemetry import Telemetry, is_stale

STATE_VERSION = 1


class RegistryError(ValueError):
    """Raised for registration conflicts and unknown devices."""


class VersionConflict(RuntimeError):
    """Raised when expected_version does not match (CAS protection)."""


class DeviceRegistry:
    def __init__(self, path: str | Path, *,
                 heartbeat_timeout_s: float = 120.0,
                 max_devices: int = 64,
                 max_history: int = 200) -> None:
        self.path = Path(path)
        self.heartbeat_timeout_s = heartbeat_timeout_s
        self.max_devices = max_devices
        self.max_history = max_history
        self.devices: dict[str, Device] = {}
        self.node_index: dict[str, str] = {}  # node_id -> device_id
        self.telemetry: dict[str, dict[str, Any]] = {}  # device_id -> summary
        self.history: list[dict[str, Any]] = []
        self.errors: list[dict[str, Any]] = []
        self.load()

    # -- registration ----------------------------------------------------

    def register(self, name: str, device_type: str = "unknown", *,
                 node_id: str = "", platform: str = "",
                 platform_version: str = "", architecture: str = "",
                 hostname: str = "", capabilities: dict[str, int] | None = None,
                 metadata: dict[str, Any] | None = None,
                 heartbeat_interval_s: float = 60.0,
                 owner: str = "", network: str = "",
                 by: str = "user") -> Device:
        """Enroll a node. Starts at TRUST_PENDING — never trusted on sight."""
        validate_device_name(name)
        validate_device_type(device_type)
        clean_meta = dict(reject_secrets(dict(metadata or {}), "device metadata"))
        if node_id and node_id in self.node_index:
            existing = self.devices[self.node_index[node_id]]
            if existing.name == name and existing.device_type == device_type:
                return existing  # idempotent re-registration
            raise RegistryError(
                f"node_id {node_id} already belongs to device {existing.device_id}"
            )
        if len(self.devices) >= self.max_devices:
            raise RegistryError(f"device limit reached ({self.max_devices})")
        device = Device(
            name=name, device_type=device_type, node_id=node_id,
            platform=platform[:64], platform_version=platform_version[:64],
            architecture=architecture[:32], hostname=hostname[:128],
            capabilities=dict(capabilities or {}),
            lifecycle=LifecycleState.REGISTERED,
            trust=TrustState.PENDING,
            heartbeat_interval_s=max(5.0, float(heartbeat_interval_s)),
            owner=owner[:80], network=network[:80],
            metadata=clean_meta,
            provenance={"observer": "device-fabric", "by": by},
        )
        # REGISTERED is entered via the validated DISCOVERED -> REGISTERED edge.
        device.lifecycle = LifecycleState.DISCOVERED
        device.trust = TrustState.UNTRUSTED
        device.apply_lifecycle(LifecycleState.REGISTERED)
        device.touch()
        self.devices[device.device_id] = device
        if node_id:
            self.node_index[node_id] = device.device_id
        self._record("registered", device.device_id, by=by)
        self.save()
        return device

    def discover(self, name: str, device_type: str = "unknown", *,
                 by: str = "user") -> Device:
        """Note a sighted-but-unenrolled node. DISCOVERED, untrusted."""
        validate_device_name(name)
        validate_device_type(device_type)
        device = Device(name=name, device_type=device_type,
                        provenance={"observer": "device-fabric", "by": by})
        device.touch()
        self.devices[device.device_id] = device
        self._record("discovered", device.device_id, by=by)
        self.save()
        return device

    def unregister(self, device_id: str, *, by: str = "user") -> bool:
        device = self.devices.pop(device_id, None)
        if device is None:
            return False
        if device.node_id and self.node_index.get(device.node_id) == device_id:
            del self.node_index[device.node_id]
        self.telemetry.pop(device_id, None)
        self._record("unregistered", device_id, by=by)
        self.save()
        return True

    # -- lookup ----------------------------------------------------------

    def get(self, device_id: str) -> Device | None:
        return self.devices.get(device_id)

    def require(self, device_id: str) -> Device:
        device = self.get(device_id)
        if device is None:
            raise RegistryError(f"unknown device: {device_id}")
        return device

    def get_by_node(self, node_id: str) -> Device | None:
        device_id = self.node_index.get(node_id)
        return self.devices.get(device_id) if device_id else None

    def list(self, *, device_type: str = "",
             trust: TrustState | str = "",
             lifecycle: LifecycleState | str = "",
             capability: str = "") -> list[Device]:
        out = list(self.devices.values())
        if device_type:
            out = [d for d in out if d.device_type == device_type]
        if trust:
            want = trust.value if isinstance(trust, TrustState) else trust
            out = [d for d in out if d.trust.value == want]
        if lifecycle:
            want = lifecycle.value if isinstance(lifecycle, LifecycleState) else lifecycle
            out = [d for d in out if d.lifecycle.value == want]
        if capability:
            out = [d for d in out if capability in d.capabilities]
        return sorted(out, key=lambda d: d.name.lower())

    def find_by_capability(self, capability: str) -> list[Device]:
        return self.list(capability=capability)

    # -- lifecycle / trust -----------------------------------------------

    def transition(self, device_id: str, to: LifecycleState | str,
                   *, by: str = "user") -> Device:
        device = self.require(device_id)
        target = to if isinstance(to, LifecycleState) else LifecycleState(to)
        device.apply_lifecycle(target)
        self._record(f"lifecycle:{target.value}", device_id, by=by)
        self.save()
        return device

    def set_trust(self, device_id: str, trusted: bool, *,
                  by: str = "user", reason: str = "",
                  auth: AuthContext | None = None) -> Device:
        """Explicit trust decision, recorded with actor + reason.

        Trusting moves TRUST_PENDING -> TRUSTED; distrust moves back to
        TRUST_PENDING. Revocation/quarantine have their own methods.
        """
        device = self.require(device_id)
        auth = auth or AuthContext()
        if trusted:
            # Walk the validated path REGISTERED -> TRUST_PENDING -> TRUSTED.
            if device.lifecycle == LifecycleState.REGISTERED:
                device.apply_lifecycle(LifecycleState.TRUST_PENDING)
            check_transition(device.lifecycle, LifecycleState.TRUSTED)
            device.apply_lifecycle(LifecycleState.TRUSTED)
        else:
            if device.lifecycle in (LifecycleState.REVOKED,
                                    LifecycleState.QUARANTINED):
                raise RegistryError("use release() before changing trust here")
            # Invariant: ONLINE implies TRUSTED. Losing trust drops presence;
            # a fresh heartbeat re-promotes after re-trust.
            if device.lifecycle == LifecycleState.ONLINE:
                device.apply_lifecycle(LifecycleState.OFFLINE)
            device.trust = TrustState.PENDING
            device.updated_at = now()
        device.provenance["last_trust_decision"] = {
            "by": by, "reason": reason[:200], "auth": auth.to_dict(),
        }
        self._record("trust:trusted" if trusted else "trust:pending",
                     device_id, by=by, extra={"reason": reason[:200]})
        self.save()
        return device

    def revoke(self, device_id: str, *, by: str = "user",
               reason: str = "") -> Device:
        device = self.require(device_id)
        device.apply_lifecycle(LifecycleState.REVOKED)
        self._record("revoked", device_id, by=by, extra={"reason": reason[:200]})
        self.save()
        return device

    def quarantine(self, device_id: str, *, by: str = "user",
                   reason: str = "") -> Device:
        device = self.require(device_id)
        device.apply_lifecycle(LifecycleState.QUARANTINED)
        self._record("quarantined", device_id, by=by,
                     extra={"reason": reason[:200]})
        self.save()
        return device

    def release(self, device_id: str, *, by: str = "user") -> Device:
        """QUARANTINED/DISABLED -> TRUST_PENDING for re-evaluation."""
        device = self.require(device_id)
        device.apply_lifecycle(LifecycleState.TRUST_PENDING)
        self._record("released", device_id, by=by)
        self.save()
        return device

    def enable(self, device_id: str, *, by: str = "user") -> Device:
        return self.release(device_id, by=by)

    def disable(self, device_id: str, *, by: str = "user",
                reason: str = "") -> Device:
        device = self.require(device_id)
        device.apply_lifecycle(LifecycleState.DISABLED)
        self._record("disabled", device_id, by=by,
                     extra={"reason": reason[:200]})
        self.save()
        return device

    # -- heartbeat / presence --------------------------------------------

    def heartbeat(self, device_id: str, telemetry: Telemetry | dict[str, Any] | None = None,
                  *, at: float | None = None) -> Device:
        """Process a heartbeat. First heartbeat from TRUSTED promotes ONLINE."""
        device = self.require(device_id)
        stamp = at if at is not None else now()
        if isinstance(telemetry, dict):
            telemetry = Telemetry.from_dict({"device_id": device_id, **telemetry})
        if telemetry is not None:
            reject_secrets(dict(telemetry.extra or {}), "telemetry extra")
            self.telemetry[device_id] = telemetry.summary()
            if telemetry.node_version:
                device.node_version = telemetry.node_version[:32]
        device.touch(stamp)
        if device.lifecycle == LifecycleState.TRUSTED:
            device.apply_lifecycle(LifecycleState.ONLINE)
            self._record("online", device_id)
        elif device.lifecycle == LifecycleState.OFFLINE:
            device.apply_lifecycle(LifecycleState.ONLINE)
            self._record("online", device_id)
        self.save()
        return device

    def mark_online(self, device_id: str) -> Device:
        device = self.require(device_id)
        if device.lifecycle == LifecycleState.TRUSTED:
            device.apply_lifecycle(LifecycleState.ONLINE)
        elif device.lifecycle == LifecycleState.OFFLINE:
            device.apply_lifecycle(LifecycleState.ONLINE)
        else:
            check_transition(device.lifecycle, LifecycleState.ONLINE)
            device.apply_lifecycle(LifecycleState.ONLINE)
        device.touch()
        self.save()
        return device

    def mark_offline(self, device_id: str, *, reason: str = "") -> Device:
        device = self.require(device_id)
        if device.lifecycle == LifecycleState.ONLINE:
            device.apply_lifecycle(LifecycleState.OFFLINE)
            device.consecutive_misses += 1
            self._record("offline", device_id, extra={"reason": reason[:200]})
            self.save()
        return device

    def sweep_timeouts(self, at: float | None = None) -> list[str]:
        """Mark ONLINE nodes with stale heartbeats OFFLINE. Never deletes."""
        stamp = at if at is not None else now()
        changed = []
        for device in self.devices.values():
            if device.lifecycle != LifecycleState.ONLINE:
                continue
            timeout = max(device.heartbeat_interval_s * 3.0,
                          self.heartbeat_timeout_s)
            if is_stale(device.last_seen, stamp, timeout):
                device.apply_lifecycle(LifecycleState.OFFLINE)
                device.consecutive_misses += 1
                changed.append(device.device_id)
                self._record("offline", device.device_id,
                             extra={"reason": "heartbeat timeout"})
        if changed:
            self.save()
        return changed

    # -- update / capabilities -------------------------------------------

    def update(self, device_id: str, *,
               expected_version: int | None = None, **fields: Any) -> Device:
        """CAS-protected field update. Unknown/secret fields rejected."""
        device = self.require(device_id)
        if expected_version is not None and device.version != expected_version:
            raise VersionConflict(
                f"{device_id} is at version {device.version}, "
                f"caller expected {expected_version}"
            )
        editable = {"name", "platform", "platform_version", "architecture",
                    "hostname", "heartbeat_interval_s", "location",
                    "owner", "network", "node_version", "metadata"}
        for key, value in fields.items():
            if key not in editable:
                raise RegistryError(f"field not editable: {key}")
            if key == "name":
                validate_device_name(value)
            if key == "metadata":
                value = dict(reject_secrets(dict(value or {}), "device metadata"))
            if isinstance(value, str):
                value = value[:256]
            setattr(device, key, value)
        device.version += 1
        device.updated_at = now()
        self.save()
        return device

    def declare_capabilities(self, device_id: str,
                             caps: list[Capability | dict[str, Any]]) -> Device:
        device = self.require(device_id)
        registry = CapabilityRegistry()
        for name, version in device.capabilities.items():
            registry.declare(Capability(name=name, version=int(version)))
        for cap in caps:
            cap = cap if isinstance(cap, Capability) else Capability.from_dict(cap)
            registry.declare(cap)
        device.capabilities = {c.name: c.version for c in registry.list()}
        device.version += 1
        device.updated_at = now()
        self._record("capabilities", device_id,
                     extra={"capabilities": sorted(device.capabilities)})
        self.save()
        return device

    def set_capability_enabled(self, device_id: str, name: str,
                               enabled: bool) -> Device:
        device = self.require(device_id)
        if name not in device.capabilities:
            raise RegistryError(f"device has no capability: {name}")
        # Removal would lose the version; disabling keeps the declaration.
        if not enabled:
            device.metadata.setdefault("disabled_capabilities", [])
            if name not in device.metadata["disabled_capabilities"]:
                device.metadata["disabled_capabilities"].append(name)
        else:
            device.metadata.get("disabled_capabilities", [])
            if name in device.metadata.get("disabled_capabilities", []):
                device.metadata["disabled_capabilities"].remove(name)
        device.version += 1
        device.updated_at = now()
        self.save()
        return device

    def capability_enabled(self, device: Device, name: str) -> bool:
        return (name in device.capabilities
                and name not in device.metadata.get("disabled_capabilities", []))

    # -- persistence -----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": STATE_VERSION,
            "devices": {did: dev.to_dict() for did, dev in self.devices.items()},
            "node_index": dict(self.node_index),
            "telemetry": {did: dict(t) for did, t in self.telemetry.items()},
            "history": self.history[-self.max_history:],
            "errors": self.errors[-50:],
        }

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".device-fabric-",
                                   dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self.to_dict(), handle, indent=2, sort_keys=True,
                          default=str)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    persist = save

    def load(self) -> int:
        if not self.path.exists():
            return 0
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            self.errors.append({"event": "load_failed", "error": str(exc)[:200],
                                "at": now()})
            return 0
        if not isinstance(raw, dict):
            self.errors.append({"event": "load_failed",
                                "error": "root is not an object", "at": now()})
            return 0
        loaded = 0
        for device_id, item in (raw.get("devices") or {}).items():
            try:
                device = Device.from_dict(item)
                self.devices[device.device_id] = device
                loaded += 1
            except (DeviceError, TypeError, KeyError):
                continue  # corrupt entry skipped, rest recover
        for node_id, device_id in (raw.get("node_index") or {}).items():
            if device_id in self.devices:
                self.node_index[node_id] = device_id
        if isinstance(raw.get("telemetry"), dict):
            self.telemetry = {k: v for k, v in raw["telemetry"].items()
                              if isinstance(v, dict)}
        self.history = list(raw.get("history") or [])[-self.max_history:]
        self.errors = list(raw.get("errors") or [])[-50:]
        return loaded

    # -- introspection ---------------------------------------------------

    def _record(self, event: str, device_id: str, *, by: str = "",
                extra: dict[str, Any] | None = None) -> None:
        self.history.append(audit_record(f"device:{event}", actor=by,
                                         device_id=device_id,
                                         extra=scrub(extra or {})))
        if len(self.history) > self.max_history:
            self.history = self.history[-self.max_history:]

    def counts(self) -> dict[str, Any]:
        by_lifecycle: dict[str, int] = {}
        by_trust: dict[str, int] = {}
        by_type: dict[str, int] = {}
        for device in self.devices.values():
            by_lifecycle[device.lifecycle.value] = by_lifecycle.get(device.lifecycle.value, 0) + 1
            by_trust[device.trust.value] = by_trust.get(device.trust.value, 0) + 1
            by_type[device.device_type] = by_type.get(device.device_type, 0) + 1
        return {
            "devices": len(self.devices),
            "by_lifecycle": by_lifecycle,
            "by_trust": by_trust,
            "by_type": by_type,
        }

    def status(self) -> dict[str, Any]:
        info = self.counts()
        info["state_path"] = str(self.path)
        info["heartbeat_timeout_s"] = self.heartbeat_timeout_s
        info["history"] = len(self.history)
        info["errors"] = len(self.errors)
        return info
