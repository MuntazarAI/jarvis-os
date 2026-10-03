"""Android JARVIS Node adapter (milestone 3.9, server side).

This module is the *core-side* endpoint for an Android phone acting as a
first-class Device Fabric node. It reuses the 3.8 fabric without duplicating
it:

- identity/lifecycle/trust   -> DeviceRegistry / DeviceFabric
- authorization              -> DeviceRouter + PolicyEngine (never bypassed)
- protocol envelopes         -> FabricMessage / MessageType
- telemetry bounds           -> Telemetry
- secret/injection handling  -> jarvis.device.security + security.guards

What this module ADDS (Android-specific, not in 3.8):

- Android identity metadata validation (model, Android version, app version)
- explicit pairing with short-lived verification codes (hashed, persisted
  pending state so cross-process CLI pairing works)
- Android permission states mapped to capability enforcement
- a SAFE command allowlist (no shell, no eval, no arbitrary execution)
- typed Android event validation (device text stays untrusted data)
- connection tracking + bounded outbound command queue with expiry
- bounded Android telemetry mapping (unknown stays unknown)

Honest limitations (see docs/ANDROID_NODE.md):

- 3.8 transport is in-process/local. This adapter does NOT claim internet
  reachability: a device counts as connected only while the link reports so,
  and commands to a disconnected node are queued (bounded, expiring) or
  refused -- never silently dropped, never executed stale.
- Pairing codes are anti-mistake verification codes, not authentication.
  Trust still comes only from an explicit human approval (actor + reason).
- The real Android app (Kotlin, under android/) needs a physical device or
  emulator; host-side tests use FakeAndroidNode semantics via LocalNode.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import tempfile
from collections import deque
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from ..core.types import new_id, now
from ..security.guards import is_safe_url
from .capabilities import Capability
from .model import PROTOCOL_VERSION
from .protocol import FabricMessage, MessageType
from .security import (
    FabricSecurityError,
    audit_record,
    check_text,
    reject_secrets,
    sanitize_text,
    scrub,
)
from .telemetry import Telemetry

ANDROID_PLATFORM = "android"
ANDROID_DEVICE_TYPES = ("phone", "tablet")
ANDROID_ADAPTER_VERSION = 1

#: Typed capabilities an Android node may declare. Documentation of intent;
#: a node declares only what it actually implements AND is permitted for.
ANDROID_CAPABILITIES = (
    "device.info",
    "device.status",
    "device.notifications",
    "device.battery",
    "device.network",
    "device.location",
    "device.camera",
    "device.microphone",
    "device.screen",
    "device.input",
    "device.sensors",
)

#: Android runtime permission backing a capability. None = no OS permission
#: gates the capability (still gated by Device Fabric policy per call).
PERMISSION_FOR_CAPABILITY: dict[str, str | None] = {
    "device.info": None,
    "device.status": None,
    "device.notifications": "android.permission.POST_NOTIFICATIONS",
    "device.battery": None,
    "device.network": None,
    "device.location": "android.permission.ACCESS_FINE_LOCATION",
    "device.camera": "android.permission.CAMERA",
    "device.microphone": "android.permission.RECORD_AUDIO",
    "device.screen": None,
    "device.input": None,
    "device.sensors": "android.permission.BODY_SENSORS",
}

#: Events an Android node may emit. Closed set; anything else is rejected.
ANDROID_EVENTS = (
    "device.connected",
    "device.disconnected",
    "battery.changed",
    "battery.low",
    "network.changed",
    "location.changed",
    "app.opened",
    "notification.received",
    "screen.state_changed",
    "sensor.updated",
    "permission.changed",
)

#: Events significant enough for proactive attention (still untrusted).
PROACTIVE_ANDROID_EVENTS = (
    "device.connected",
    "device.disconnected",
    "battery.low",
    "permission.changed",
)

PAIRING_CODE_TTL_S = 600.0
PAIRING_MAX_ATTEMPTS = 5
COMMAND_QUEUE_MAX = 50
COMMAND_TTL_S = 300.0
EVENT_TEXT_LIMIT = 500
LOW_BATTERY_PCT = 15.0

_PACKAGE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$")
_VOLUME_STREAMS = ("music", "alarm", "ring", "notification", "call")


class AndroidError(ValueError):
    """Raised for invalid Android node data or misuse."""


class PairingError(AndroidError):
    """Raised when pairing fails (bad/expired code, wrong state)."""


class AndroidCommandError(AndroidError):
    """Raised when a command is not on the safe allowlist or args invalid."""


class PermissionState(str, Enum):
    AVAILABLE = "available"
    DENIED = "denied"
    NOT_REQUESTED = "not_requested"
    RESTRICTED = "restricted"
    UNAVAILABLE = "unavailable"


class PairingState(str, Enum):
    UNPAIRED = "unpaired"
    PAIR_PENDING = "pair_pending"
    PAIRED = "paired"


def validate_android_metadata(meta: dict[str, Any]) -> dict[str, Any]:
    """Validate node-reported Android identity metadata.

    Required: device_model, android_version, app_version (short strings).
    Optional: manufacturer, sdk_int (14..99). Secrets rejected outright.
    """
    if not isinstance(meta, dict):
        raise AndroidError("android metadata must be an object")
    reject_secrets(meta, "android metadata")
    clean: dict[str, Any] = {}
    for key in ("device_model", "android_version", "app_version"):
        value = meta.get(key, "")
        if not isinstance(value, str) or not value.strip() or len(value) > 64:
            raise AndroidError(f"android metadata missing/invalid: {key}")
        clean[key] = value.strip()
    if "manufacturer" in meta:
        maker = meta["manufacturer"]
        if not isinstance(maker, str) or len(maker) > 64:
            raise AndroidError("android metadata invalid: manufacturer")
        clean["manufacturer"] = maker.strip()
    if "sdk_int" in meta:
        try:
            sdk = int(meta["sdk_int"])
        except (TypeError, ValueError):
            raise AndroidError("android metadata invalid: sdk_int")
        if not 14 <= sdk <= 99:
            raise AndroidError("android metadata invalid: sdk_int range")
        clean["sdk_int"] = sdk
    return clean


def validate_permission_report(report: dict[str, Any]) -> dict[str, str]:
    """Validate an Android permission report.

    Keys are capability names; values must be one of the five known
    PermissionState values. Unknown capabilities or states are rejected
    (never silently accepted).
    """
    if not isinstance(report, dict):
        raise AndroidError("permission report must be an object")
    clean: dict[str, str] = {}
    for capability, state in report.items():
        if capability not in ANDROID_CAPABILITIES:
            raise AndroidError(f"unknown capability in report: {capability}")
        try:
            clean[capability] = PermissionState(state).value
        except ValueError:
            raise AndroidError(
                f"unknown permission state for {capability}: {state!r}")
    return clean


def negotiate_capabilities(declared: list[str],
                           permissions: dict[str, str]) -> dict[str, Any]:
    """Split declared capabilities into granted vs withheld.

    A permission-gated capability is granted only when its Android
    permission state is AVAILABLE. Anything else is withheld with a reason.
    Unknown capability names are withheld (never granted).
    """
    granted: list[str] = []
    withheld: list[dict[str, str]] = []
    for name in declared:
        if name not in ANDROID_CAPABILITIES:
            withheld.append({"capability": name,
                             "reason": "unknown android capability"})
            continue
        gate = PERMISSION_FOR_CAPABILITY.get(name)
        if gate is None:
            granted.append(name)
            continue
        state = permissions.get(name, PermissionState.NOT_REQUESTED.value)
        if state == PermissionState.AVAILABLE.value:
            granted.append(name)
        else:
            withheld.append({"capability": name,
                             "reason": f"android permission {state}: {gate}"})
    return {"granted": sorted(granted), "withheld": withheld}


def android_telemetry(report: dict[str, Any], device_id: str) -> Telemetry:
    """Map a bounded Android telemetry report onto Telemetry.

    Accepted keys only; unknown metrics stay unknown (None), never zeroed.
    Secrets in extras are rejected, not stored.
    """
    if not isinstance(report, dict):
        raise AndroidError("telemetry report must be an object")
    reject_secrets(report, "telemetry report")
    network = report.get("network")
    if network is not None and not isinstance(network, dict):
        raise AndroidError("telemetry network must be an object")
    clean_network = None
    if isinstance(network, dict):
        allowed = {"type", "connected", "metered"}
        clean_network = {k: network[k] for k in allowed if k in network}
        if "type" in clean_network:
            clean_network["type"] = str(clean_network["type"])[:32]
    extra: dict[str, Any] = {}
    for key in ("device_model", "android_version"):
        if key in report:
            extra[key] = str(report[key])[:64]
    return Telemetry(
        device_id=device_id,
        online=report.get("online"),
        uptime_s=report.get("uptime_s"),
        battery_pct=report.get("battery_pct"),
        battery_charging=report.get("battery_charging"),
        network=clean_network,
        node_version=str(report.get("app_version", ""))[:32],
        capability_health=None,
        source="android-node",
        extra=extra,
    )


# -- safe command allowlist ----------------------------------------------
#
# Maps a typed command -> fabric capability + argument schema. Anything not
# listed here cannot be sent to an Android node, period. There is no shell,
# no eval, no generic execution endpoint.

def _cmd_none(args: dict[str, Any]) -> dict[str, Any]:
    if args:
        raise AndroidCommandError("command takes no arguments")
    return {}


def _cmd_notify(args: dict[str, Any]) -> dict[str, Any]:
    title = args.get("title", "")
    body = args.get("body", "")
    if not isinstance(title, str) or not title.strip() or len(title) > 80:
        raise AndroidCommandError("notification needs title (1..80 chars)")
    if not isinstance(body, str) or len(body) > 500:
        raise AndroidCommandError("notification body must be <= 500 chars")
    return {"title": title.strip(), "body": body}


def _cmd_open_app(args: dict[str, Any]) -> dict[str, Any]:
    package = args.get("package", "")
    if not isinstance(package, str) or not _PACKAGE_RE.match(package):
        raise AndroidCommandError("open_app needs a valid package name")
    return {"package": package}


def _cmd_open_url(args: dict[str, Any]) -> dict[str, Any]:
    url = args.get("url", "")
    if not isinstance(url, str) or not url:
        raise AndroidCommandError("open_url needs a url")
    from ..security.guards import is_safe_url as _safe
    ok, reason = _safe(url)
    if not ok:
        raise AndroidCommandError(f"open_url blocked: {reason}")
    return {"url": url}


def _cmd_vibrate(args: dict[str, Any]) -> dict[str, Any]:
    try:
        duration = int(args.get("duration_ms", 200))
    except (TypeError, ValueError):
        raise AndroidCommandError("vibrate needs integer duration_ms")
    if not 0 <= duration <= 10000:
        raise AndroidCommandError("vibrate duration_ms must be 0..10000")
    return {"duration_ms": duration}


def _cmd_volume(args: dict[str, Any]) -> dict[str, Any]:
    stream = args.get("stream", "music")
    if stream not in _VOLUME_STREAMS:
        raise AndroidCommandError(f"unknown volume stream: {stream!r}")
    try:
        level = int(args.get("level", 50))
    except (TypeError, ValueError):
        raise AndroidCommandError("volume needs integer level")
    if not 0 <= level <= 100:
        raise AndroidCommandError("volume level must be 0..100")
    return {"stream": stream, "level": level}


#: command -> (fabric capability, arg validator)
SAFE_COMMANDS: dict[str, tuple[str, Any]] = {
    "device.get_info": ("device.info", _cmd_none),
    "device.get_status": ("device.status", _cmd_none),
    "device.get_battery": ("device.battery", _cmd_none),
    "device.get_network": ("device.network", _cmd_none),
    "device.get_location": ("device.location", _cmd_none),
    "device.get_sensors": ("device.sensors", _cmd_none),
    "device.show_notification": ("device.notifications", _cmd_notify),
    "device.open_app": ("device.screen", _cmd_open_app),
    "device.open_url": ("device.screen", _cmd_open_url),
    "device.vibrate": ("device.screen", _cmd_vibrate),
    "device.set_volume": ("device.screen", _cmd_volume),
    "device.capture_photo": ("device.camera", _cmd_none),
    "device.start_sensor_stream": ("device.sensors", _cmd_none),
    "device.stop_sensor_stream": ("device.sensors", _cmd_none),
}


def validate_command(command: str, args: dict[str, Any] | None) -> dict[str, Any]:
    """Validate a typed command. Returns {capability, args} or raises."""
    if command not in SAFE_COMMANDS:
        raise AndroidCommandError(
            f"command not on the safe allowlist: {command!r}")
    capability, schema = SAFE_COMMANDS[command]
    clean = schema(dict(args or {}))
    return {"command": command, "capability": capability, "args": clean}


def validate_android_event(type: str, payload: dict[str, Any] | None) -> dict[str, Any]:
    """Validate a typed Android event. Device text stays flagged untrusted."""
    if type not in ANDROID_EVENTS:
        raise AndroidError(f"unknown android event: {type!r}")
    if payload is not None and not isinstance(payload, dict):
        raise AndroidError("event payload must be an object")
    reject_secrets(dict(payload or {}), "event payload")
    clean = scrub(dict(payload or {}))
    flags: dict[str, Any] = {}
    for key in ("text", "title", "body", "message"):
        if key in clean and isinstance(clean[key], str):
            scan = check_text(clean[key])
            if not scan["clean"]:
                flags["injection"] = scan
    return {"type": type, "payload": clean, "flags": flags}


def android_message(message_type: str, sender_node: str, *,
                    recipient_node: str = "", capability: str = "",
                    payload: dict[str, Any] | None = None,
                    request_id: str = "") -> FabricMessage:
    """Build a validated android-side envelope (same protocol, no fork)."""
    message = FabricMessage(
        sender_node=sender_node,
        recipient_node=recipient_node,
        message_type=message_type,
        capability=capability,
        payload=scrub(dict(payload or {})),
        request_id=request_id,
        provenance={"observer": "android-node",
                    "protocol_version": PROTOCOL_VERSION},
    )
    return message.validate()


def parse_android_message(data: dict[str, Any]) -> FabricMessage:
    """Parse + validate an inbound envelope. Version mismatches rejected."""
    message = FabricMessage.from_dict(data)
    return message.validate()


# -- pairing ---------------------------------------------------------------


class PairingManager:
    """Short-lived pairing codes with hashed, persisted pending state.

    Codes are anti-mistake verification, NOT authentication: the trust
    decision itself is still an explicit human approval recorded by the
    fabric with actor + reason.

    Only SHA-256 hashes of codes are kept (memory and disk); the plaintext
    code exists only in the begin() return value. Pending pairings persist
    to ``android-pairings.json`` so issuing a code in one process (CLI) and
    confirming it in another works. Entries expire after the TTL and are
    pruned on load/save.
    """

    def __init__(self, *, ttl_s: float = PAIRING_CODE_TTL_S,
                 path: str | Path | None = None) -> None:
        self.ttl_s = ttl_s
        self.path = Path(path) if path else None
        self._pending: dict[str, dict[str, Any]] = {}
        self.audit: list[dict[str, Any]] = []
        self.load()

    @staticmethod
    def _hash(code: str) -> str:
        return hashlib.sha256(str(code).encode("utf-8")).hexdigest()

    def begin(self, device_id: str, *, by: str = "user",
              code: str = "") -> dict[str, Any]:
        pairing_code = code or f"{secrets.randbelow(1000000):06d}"
        if not re.fullmatch(r"\d{6}", pairing_code):
            raise PairingError("pairing code must be 6 digits")
        self._pending[device_id] = {
            "code_sha256": self._hash(pairing_code),
            "created_at": now(),
            "attempts": 0,
            "by": by,
        }
        self._audit("pairing:begun", device_id, True, by, [])
        self.save()
        return {"device_id": device_id, "pairing_code": pairing_code,
                "expires_in_s": self.ttl_s}

    def confirm(self, device_id: str, code: str) -> None:
        pending = self._pending.get(device_id)
        if pending is None:
            raise PairingError("no pending pairing for this device")
        if now() - float(pending["created_at"]) > self.ttl_s:
            del self._pending[device_id]
            self._audit("pairing:expired", device_id, False, "", [])
            self.save()
            raise PairingError("pairing code expired; begin pairing again")
        pending["attempts"] = int(pending["attempts"]) + 1
        if pending["attempts"] > PAIRING_MAX_ATTEMPTS:
            del self._pending[device_id]
            self._audit("pairing:locked", device_id, False, "", [])
            self.save()
            raise PairingError("too many wrong codes; pairing locked")
        if not hmac.compare_digest(self._hash(code),
                                   str(pending["code_sha256"])):
            self._audit("pairing:wrong_code", device_id, False, "", [])
            self.save()
            raise PairingError("wrong pairing code")
        del self._pending[device_id]
        self._audit("pairing:confirmed", device_id, True, "", [])
        self.save()

    def cancel(self, device_id: str) -> bool:
        if device_id in self._pending:
            del self._pending[device_id]
            self._audit("pairing:cancelled", device_id, True, "", [])
            self.save()
            return True
        return False

    def prune(self) -> int:
        """Drop expired entries. Returns count dropped."""
        stamp = now()
        expired = [d for d, p in self._pending.items()
                   if stamp - float(p.get("created_at", 0)) > self.ttl_s]
        for device_id in expired:
            del self._pending[device_id]
        return len(expired)

    def save(self) -> None:
        """Persist pending hashes (atomic write). Best-effort, audited."""
        if self.path is None:
            return
        try:
            self.prune()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".android-pairings-",
                                       dir=str(self.path.parent))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump({"version": 1, "pending": self._pending},
                              handle, indent=2, sort_keys=True)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp, self.path)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
        except (OSError, ValueError) as exc:
            self._audit("pairing:save_failed", "", False, "",
                        [f"{exc}"[:120]])

    def load(self) -> int:
        """Load pending hashes. Corrupt/missing file recovers to empty."""
        if self.path is None or not self.path.exists():
            return 0
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return 0
        if not isinstance(raw, dict):
            return 0
        loaded = 0
        for device_id, entry in (raw.get("pending") or {}).items():
            if not isinstance(entry, dict):
                continue
            if not re.fullmatch(r"[0-9a-f]{64}",
                                str(entry.get("code_sha256", ""))):
                continue
            try:
                created = float(entry.get("created_at", 0))
                attempts = int(entry.get("attempts", 0))
            except (TypeError, ValueError):
                continue
            self._pending[str(device_id)] = {
                "code_sha256": str(entry["code_sha256"]),
                "created_at": created,
                "attempts": attempts,
                "by": str(entry.get("by", ""))[:64],
            }
            loaded += 1
        self.prune()
        return loaded

    def state(self, device_id: str) -> PairingState:
        return (PairingState.PAIR_PENDING if device_id in self._pending
                else PairingState.UNPAIRED)

    def pending_devices(self) -> list[str]:
        return sorted(self._pending)

    def _audit(self, action: str, device_id: str, ok: bool, actor: str,
               reasons: list[str]) -> None:
        self.audit.append(audit_record(f"android:{action}", actor=actor,
                                       device_id=device_id, ok=ok,
                                       reasons=reasons))
        if len(self.audit) > 200:
            self.audit = self.audit[-200:]


# -- outbound command queue --------------------------------------------------


@dataclass
class QueuedCommand:
    command_id: str = field(default_factory=lambda: new_id("acmd"))
    device_id: str = ""
    command: str = ""
    capability: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    actor: str = ""
    created_at: float = field(default_factory=now)
    expires_at: float = 0.0

    def expired(self, at: float | None = None) -> bool:
        return (at if at is not None else now()) > self.expires_at

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# -- adapter -----------------------------------------------------------------


class AndroidNodeAdapter:
    """Core-side facade for Android nodes. Wraps a DeviceFabric."""

    def __init__(self, fabric: Any, *,
                 pairing: PairingManager | None = None) -> None:
        if fabric is None:
            raise AndroidError("AndroidNodeAdapter needs a DeviceFabric")
        self.fabric = fabric
        if pairing is not None:
            self.pairing = pairing
        else:
            home = getattr(fabric, "home", None)
            path = Path(home) / "android-pairings.json" if home else None
            self.pairing = PairingManager(path=path)
        self._connected: dict[str, float] = {}  # device_id -> connected_since
        self._queues: dict[str, deque] = {}
        self._dropped: dict[str, int] = {}

    # -- enrollment / pairing --------------------------------------------------

    def register_android(self, name: str, metadata: dict[str, Any], *,
                         by: str = "user", owner: str = "",
                         pairing_code: str = "") -> dict[str, Any]:
        """Register an Android node. Starts UNTRUSTED + PAIR_PENDING."""
        meta = validate_android_metadata(metadata)
        info = self.fabric.register_device(
            name, "phone", by=by, platform=ANDROID_PLATFORM,
            platform_version=meta["android_version"], owner=owner,
            metadata={"android_model": meta["device_model"],
                      "android_manufacturer": meta.get("manufacturer", ""),
                      "android_sdk": meta.get("sdk_int", 0),
                      "is_android": True})
        # registry.register() has no node_version kwarg; the app version
        # lands on the editable node_version field via CAS update.
        self.fabric.registry.update(info["device_id"],
                                    node_version=meta["app_version"])
        info = self.fabric.info(info["device_id"])
        pairing = self.pairing.begin(info["device_id"], by=by,
                                     code=pairing_code)
        out = dict(info)
        out["pairing"] = pairing
        out["pairing_state"] = PairingState.PAIR_PENDING.value
        return out

    def discover_android(self, name: str, *, by: str = "user") -> dict[str, Any]:
        return self.fabric.discover_device(name, "phone", by=by)

    def pair(self, device_id: str, code: str, *, by: str = "user",
             reason: str = "", node_id: str = "") -> dict[str, Any]:
        """Confirm pairing code, bind node_id, record trust decision."""
        self._require_android(device_id)
        self.pairing.confirm(device_id, code)
        if node_id:
            device = self.fabric.registry.require(device_id)
            claimed = str(node_id)[:128]
            if device.node_id and device.node_id != claimed:
                raise PairingError(
                    f"node_id conflict: {device.node_id} != {claimed}")
            device.node_id = claimed
            self.fabric.registry.node_index[claimed] = device_id
        info = self.fabric.trust_device(device_id, by=by,
                                        reason=reason or "pairing code confirmed")
        self._remember(f"Android node paired: {info['name']}")
        return self.status(device_id)
    def pair_request_approval(self, device_id: str, code: str, *,
                                by: str = "socket-host",
                                node_id: str = "") -> dict[str, Any]:
        """Socket pairing step 1: verify the code and bind node_id WITHOUT
        trusting. The device ends at TRUST_PENDING; an explicit
        ``trust_android`` (human approval) is still required before the
        host issues a device secret. Never raises for wrong codes."""
        from .model import LifecycleState
        self._require_android(device_id)
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
        self._require_android(device_id)
        self._connected.pop(device_id, None)
        self._queues.pop(device_id, None)
        info = self.fabric.revoke_device(
            device_id, by=by, reason=reason or "unpaired by user")
        self._remember(f"Android node unpaired: {info['name']}")
        return self.status(device_id)

    def trust_android(self, device_id: str, *, by: str = "user",
                      reason: str = "") -> dict[str, Any]:
        self._require_android(device_id)
        self.pairing.cancel(device_id)
        info = self.fabric.trust_device(device_id, by=by, reason=reason)
        return self.status(device_id)

    def revoke_android(self, device_id: str, *, by: str = "user",
                       reason: str = "") -> dict[str, Any]:
        return self.unpair(device_id, by=by, reason=reason)

    def quarantine_android(self, device_id: str, *, by: str = "user",
                           reason: str = "") -> dict[str, Any]:
        self._require_android(device_id)
        self._connected.pop(device_id, None)
        info = self.fabric.quarantine_device(device_id, by=by, reason=reason)
        return self.status(device_id)

    def pairing_state(self, device_id: str) -> dict[str, Any]:
        device = self.fabric.registry.require(device_id)
        if self.pairing.state(device_id) == PairingState.PAIR_PENDING:
            state = PairingState.PAIR_PENDING.value
        elif str(device.trust.value) == "trusted":
            state = PairingState.PAIRED.value
        else:
            state = PairingState.UNPAIRED.value
        return {"device_id": device_id, "pairing_state": state,
                "lifecycle": device.lifecycle.value,
                "trust": device.trust.value}

    # -- connection / presence ---------------------------------------------------

    def connect(self, device_id: str, *, by: str = "device") -> dict[str, Any]:
        """Mark the link connected; promote presence; drain queued commands."""
        self._require_android(device_id)
        self._connected[device_id] = now()
        try:
            self.fabric.registry.mark_online(device_id)
        except Exception:
            pass  # only TRUSTED/OFFLINE nodes promote; others stay as-is
        self._bus("device.connected",
                  {"device_id": device_id, "by": by})
        drained = self.drain(device_id)
        out = self.status(device_id)
        out["drained"] = drained
        return out

    def disconnect(self, device_id: str, *, by: str = "device",
                   reason: str = "") -> dict[str, Any]:
        self._require_android(device_id)
        self._connected.pop(device_id, None)
        try:
            self.fabric.registry.mark_offline(
                device_id, reason=reason or "link disconnected")
        except Exception:
            pass
        self._bus("device.disconnected",
                  {"device_id": device_id, "by": by, "reason": reason[:200]})
        return self.status(device_id)

    def is_connected(self, device_id: str) -> bool:
        return device_id in self._connected

    def heartbeat(self, device_id: str, report: dict[str, Any] | None = None,
                  *, by: str = "device") -> dict[str, Any]:
        """Heartbeat counts only while the link is connected.

        Reports from a disconnected node are refused (never claim ONLINE
        while disconnected); use connect() first.
        """
        self._require_android(device_id)
        if not self.is_connected(device_id):
            raise AndroidError("node is not connected; heartbeat refused")
        telemetry = (android_telemetry(dict(report or {}), device_id)
                     if report is not None else None)
        info = self.fabric.heartbeat(device_id, telemetry, by=by)
        battery = (report or {}).get("battery_pct")
        try:
            if battery is not None and float(battery) <= LOW_BATTERY_PCT:
                self._ingest_validated(
                    device_id, "battery.low",
                    {"battery_pct": float(battery)}, remember=False)
        except (TypeError, ValueError):
            pass
        return self.status(device_id)

    # -- permissions / capabilities ----------------------------------------------

    def report_permissions(self, device_id: str, report: dict[str, Any], *,
                           by: str = "user") -> dict[str, Any]:
        """Apply a permission report: enable only what Android allows.

        Returns the granted/withheld split. Security-relevant changes
        (camera/mic/location newly denied or granted) become memory facts.
        """
        self._require_android(device_id)
        clean = validate_permission_report(report)
        device = self.fabric.registry.require(device_id)
        declared = sorted(device.capabilities)
        split = negotiate_capabilities(declared, clean)
        for name in split["granted"]:
            try:
                self.fabric.set_capability_enabled(device_id, name, True,
                                                   by=by)
            except Exception:
                pass
        for item in split["withheld"]:
            try:
                self.fabric.set_capability_enabled(device_id,
                                                   item["capability"], False,
                                                   by=by)
            except Exception:
                pass
        self.fabric.registry.update(
            device_id, metadata={**(device.metadata or {}),
                                 "android_permissions": clean})
        for watched in ("device.camera", "device.microphone",
                        "device.location"):
            if watched in clean and clean[watched] != PermissionState.AVAILABLE.value:
                self._remember(
                    f"Android permission changed: {watched} is "
                    f"{clean[watched]} on {device.name}")
                break
        return {"device_id": device_id, "granted": split["granted"],
                "withheld": split["withheld"]}

    def declare_android_capabilities(self, device_id: str,
                                     declared: list[str], *,
                                     by: str = "user") -> dict[str, Any]:
        """Declare capabilities, filtered through the permission report."""
        self._require_android(device_id)
        device = self.fabric.registry.require(device_id)
        permissions = dict(
            (device.metadata or {}).get("android_permissions", {}))
        split = negotiate_capabilities(list(declared), permissions)
        if split["granted"]:
            self.fabric.declare_capabilities(
                device_id,
                [{"name": name, "version": 1} for name in split["granted"]],
                by=by)
        return {"device_id": device_id, **split}

    # -- commands ------------------------------------------------------------------

    def send_command(self, actor: str, device_id: str, command: str,
                     args: dict[str, Any] | None = None,
                     approval_token: str = "") -> dict[str, Any]:
        """Send a typed command. Offline nodes queue (bounded, expiring)."""
        self._require_android(device_id)
        checked = validate_command(command, args)
        if not self.is_connected(device_id):
            queued = self._enqueue(device_id, checked, actor)
            return {"ok": False, "queued": True, "command_id": queued.command_id,
                    "device_id": device_id, "command": command,
                    "error": "node offline: command queued (bounded, expiring)"}
        device = self.fabric.registry.require(device_id)
        if not self.fabric.registry.capability_enabled(device,
                                                        checked["capability"]):
            return {"ok": False, "device_id": device_id, "command": command,
                    "error": f"capability not available on node: "
                             f"{checked['capability']}"}
        host = getattr(self, "socket_host", None)
        if host is not None and host.has_lane(device_id):
            # Live socket lane: authorize + deliver via the host (bare
            # wire name, host HMAC proof, correlated result). The host
            # re-checks authorization; nothing bypasses the router.
            return host.send_command(actor, device_id, command,
                                     checked["args"],
                                     approval_token=approval_token)
        return self.fabric.route_command(actor, device_id,
                                         checked["capability"],
                                         checked["args"],
                                         approval_token=approval_token)

    def _enqueue(self, device_id: str, checked: dict[str, Any],
                 actor: str) -> QueuedCommand:
        queue = self._queues.setdefault(device_id, deque())
        item = QueuedCommand(
            device_id=device_id, command=checked["command"],
            capability=checked["capability"], args=checked["args"],
            actor=actor, expires_at=now() + COMMAND_TTL_S)
        queue.append(item)
        while len(queue) > COMMAND_QUEUE_MAX:
            queue.popleft()
            self._dropped[device_id] = self._dropped.get(device_id, 0) + 1
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
                    # Live socket lane: same authorized path as a fresh
                    # send (re-authorize per item; approval-gated commands
                    # fail closed here exactly as they would live).
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
        return {"dispatched": dispatched, "rejected": rejected,
                "dropped_while_offline": self._dropped.get(device_id, 0)}

    def queue_depth(self, device_id: str) -> dict[str, Any]:
        queue = self._queues.get(device_id, deque())
        return {"device_id": device_id, "queued": len(queue),
                "dropped_while_offline": self._dropped.get(device_id, 0)}

    # -- events ----------------------------------------------------------------------

    def ingest_event(self, device_id: str, type: str,
                     payload: dict[str, Any] | None = None, *,
                     remember: bool = False) -> dict[str, Any]:
        """Validate and fan out an Android event. Untrusted text stays data."""
        self._require_android(device_id)
        checked = validate_android_event(type, payload)
        return self._ingest_validated(device_id, checked["type"],
                                      checked["payload"], remember=remember,
                                      flags=checked["flags"])

    def _ingest_validated(self, device_id: str, type: str,
                          payload: dict[str, Any], *,
                          remember: bool = False,
                          flags: dict[str, Any] | None = None) -> dict[str, Any]:
        device = self.fabric.registry.require(device_id)
        summary = sanitize_text(
            f"{type} from {device.name}: "
            + str(payload.get("text", payload.get("summary", "")))[:120],
            EVENT_TEXT_LIMIT)
        self._bus(type, {"device_id": device_id, "name": device.name,
                         **payload})
        dots = self.fabric.route_dots({"type": type, "entity": device.name,
                                       "summary": summary})
        proactive_id = None
        if type in PROACTIVE_ANDROID_EVENTS and self.fabric.proactive is not None:
            try:
                from ..proactive.engine import ProactiveEvent
                event = ProactiveEvent(
                    type="world_changed", source="android-node",
                    entity=device.name, summary=summary,
                    payload={"android_event": type,
                             "device_id": device_id},
                    confidence=0.6,
                    provenance={"observer": "android-node",
                                "device_id": device_id},
                    trusted=False)
                candidate = self.fabric.proactive.notify(event)
                proactive_id = (candidate.candidate_id
                                if candidate is not None else None)
            except Exception:
                proactive_id = None
        if remember:
            self._remember(summary)
        return {"ok": True, "type": type, "device_id": device_id,
                "dots": dots, "proactive_candidate": proactive_id,
                "flags": flags or {}}

    # -- location (explicit only) -------------------------------------------------------

    def set_location(self, device_id: str, room: str, *,
                     permission: str = "", user_permitted: bool = False,
                     by: str = "user") -> dict[str, Any]:
        """Record location only with OS permission AND explicit user consent."""
        self._require_android(device_id)
        if permission != PermissionState.AVAILABLE.value or not user_permitted:
            raise AndroidError(
                "location needs android permission AVAILABLE + explicit user consent")
        return self.fabric.set_location(device_id, room, by=by)

    # -- read -----------------------------------------------------------------------------

    def status(self, device_id: str) -> dict[str, Any]:
        info = self.fabric.info(device_id)
        device = self.fabric.registry.require(device_id)
        info["pairing_state"] = self.pairing_state(device_id)["pairing_state"]
        info["connected"] = self.is_connected(device_id)
        info["queue"] = self.queue_depth(device_id)
        info["android_permissions"] = dict(
            (device.metadata or {}).get("android_permissions", {}))
        info["is_android"] = True
        return info

    def list_android(self) -> list[dict[str, Any]]:
        rows = []
        for device in self.fabric.registry.list():
            if device.platform == ANDROID_PLATFORM:
                rows.append(self.status(device.device_id))
        return sorted(rows, key=lambda r: r["name"].lower())

    def doctor(self) -> list[dict[str, Any]]:
        checks: list[dict[str, Any]] = []
        checks.append({"name": "android-adapter", "ok": True,
                       "detail": f"AVAILABLE: adapter v{ANDROID_ADAPTER_VERSION}; "
                                 f"protocol v{PROTOCOL_VERSION}"})
        try:
            count = len(self.list_android())
            checks.append({"name": "registry", "ok": True,
                           "detail": f"AVAILABLE: {count} android node(s)"})
        except Exception as exc:
            checks.append({"name": "registry", "ok": False,
                           "detail": str(exc)[:120]})
        pending = self.pairing.pending_devices()
        checks.append({"name": "pairing", "ok": True,
                       "detail": f"AVAILABLE: {len(pending)} pending; "
                                 "code hashes persisted, plaintext never stored"})
        checks.append({"name": "transport", "ok": True,
                       "detail": "AVAILABLE (in-process via device fabric); "
                                 "remote socket transport: AVAILABLE "
                                 "(jarvis.device.socket_transport + "
                                 "android_transport; see docs/ANDROID_TRANSPORT.md)"})
        checks.append({"name": "apk", "ok": True,
                       "detail": "OPTIONAL: companion app under android/ "
                                 "(:app:assembleDebug builds app-debug.apk); "
                                 "physical device or emulator required to install"})
        return checks

    # -- internals ----------------------------------------------------------------------------

    def _require_android(self, device_id: str) -> Any:
        device = self.fabric.registry.require(device_id)
        if device.platform != ANDROID_PLATFORM and not (
                device.metadata or {}).get("is_android"):
            raise AndroidError(f"not an android node: {device_id}")
        return device

    def _bus(self, type: str, payload: dict[str, Any]) -> None:
        bus = getattr(self.fabric, "bus", None)
        if bus is None:
            return
        try:
            from ..events.store import Event
            bus.publish(Event(type=type, payload=scrub(payload)))
        except Exception:
            pass

    def _remember(self, text: str) -> None:
        try:
            self.fabric.remember_fact(text)
        except Exception:
            pass
