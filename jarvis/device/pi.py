"""Raspberry Pi edge node adapter for the device fabric (5.0).

Mirrors the proven Android node pattern: typed SAFE_COMMANDS (no
shell, no eval, no subprocess, no arbitrary execution), closed event
set, single-use pairing codes, trust-gated heartbeat, bounded offline
queues. All execution flows through DeviceRouter + PolicyEngine; this
module adds no authorization of its own.

Pi differences from Android (deliberate, minimal):
- platform ``raspberry-pi`` / ``is_pi`` metadata marker;
- own pairing file (``pi-pairings.json``) and queue file;
- GPIO allowlist configuration (deny by default);
- hardware-backed telemetry validators (ranges, not values).
"""

from __future__ import annotations

import json
import os
import tempfile
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core.types import new_id, now
from .android import PairingError, PairingManager, PairingState
from .model import TrustState

PI_PLATFORM = "raspberry-pi"
PI_DEVICE_TYPE = "raspberry_pi"
PI_ADAPTER_VERSION = 1

PI_CAPABILITIES = (
    "pi.system",
    "pi.telemetry",
    "pi.network",
    "pi.camera",
    "pi.sensors",
    "pi.gpio",
    "pi.led",
    "pi.audio",
)

PI_EVENTS = (
    "pi.connected",
    "pi.disconnected",
    "pi.telemetry",
    "pi.temperature.high",
    "pi.network.changed",
    "pi.sensor.updated",
    "pi.camera.captured",
    "pi.gpio.changed",
    "pi.storage.low",
)

PROACTIVE_PI_EVENTS = (
    "pi.connected",
    "pi.disconnected",
    "pi.temperature.high",
    "pi.storage.low",
)

PAIRING_CODE_TTL_S = 600.0
PAIRING_MAX_ATTEMPTS = 5
COMMAND_QUEUE_MAX = 50
COMMAND_TTL_S = 300.0
EVENT_TEXT_LIMIT = 500
QUEUE_FILENAME = "pi-queue.json"

#: GPIO allowlist defaults: nothing usable until explicitly configured.
DEFAULT_GPIO_PINS: dict[str, dict[str, Any]] = {}


class PiError(RuntimeError):
    """Pi adapter misuse (not a policy denial)."""


class PiCommandError(ValueError):
    """Unknown command or invalid arguments."""


def validate_pi_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Validate registration metadata. Never raises for missing optionals."""
    if not isinstance(metadata, dict):
        raise PiError("pi metadata must be an object")
    return {
        "pi_model": str(metadata.get("pi_model", ""))[:80],
        "os": str(metadata.get("os", ""))[:80],
        "arch": str(metadata.get("arch", ""))[:32],
        "software_version": str(metadata.get("software_version", ""))[:32],
    }


# -- command validators (shape only; policy decides authorization) ---------


def _cmd_none(args: dict[str, Any]) -> dict[str, Any]:
    if args:
        raise PiCommandError("command takes no arguments")
    return {}


def _cmd_sensor(args: dict[str, Any]) -> dict[str, Any]:
    sensor_id = str(args.get("sensor_id", ""))[:64]
    if not sensor_id:
        raise PiCommandError("sensor_id is required")
    if any(not ch.isalnum() and ch not in "_-." for ch in sensor_id):
        raise PiCommandError("invalid sensor_id")
    return {"sensor_id": sensor_id}


def _cmd_gpio_read(args: dict[str, Any], pins: dict[str, Any]) -> dict[str, Any]:
    try:
        pin = int(args.get("pin"))
    except (TypeError, ValueError):
        raise PiCommandError("pin must be an integer")
    spec = pins.get(str(pin))
    if spec is None:
        raise PiCommandError(f"pin {pin} is not allowlisted")
    return {"pin": pin}


def _cmd_gpio_write(args: dict[str, Any],
                    pins: dict[str, Any]) -> dict[str, Any]:
    try:
        pin = int(args.get("pin"))
    except (TypeError, ValueError):
        raise PiCommandError("pin must be an integer")
    spec = pins.get(str(pin))
    if spec is None:
        raise PiCommandError(f"pin {pin} is not allowlisted")
    if str(spec.get("mode", "read")).lower() != "write":
        raise PiCommandError(f"pin {pin} is read-only")
    value = args.get("value")
    if value not in (0, 1, True, False):
        raise PiCommandError("GPIO value must be 0 or 1")
    return {"pin": pin, "value": 1 if value else 0}


def _cmd_led(args: dict[str, Any]) -> dict[str, Any]:
    state = str(args.get("state", "")).lower()
    if state not in ("on", "off", "blink"):
        raise PiCommandError("led state must be on|off|blink")
    return {"state": state}


def _cmd_camera(args: dict[str, Any]) -> dict[str, Any]:
    if args:
        raise PiCommandError("command takes no arguments")
    return {}


SAFE_COMMANDS: dict[str, tuple[str, Any]] = {
    # typed command -> (fabric capability, validator)
    "pi.system.info": ("pi.system", _cmd_none),
    "pi.system.status": ("pi.system", _cmd_none),
    "pi.system.cpu": ("pi.system", _cmd_none),
    "pi.system.memory": ("pi.system", _cmd_none),
    "pi.system.storage": ("pi.system", _cmd_none),
    "pi.system.temperature": ("pi.system", _cmd_none),
    "pi.network.status": ("pi.network", _cmd_none),
    "pi.camera.status": ("pi.camera", _cmd_none),
    "pi.camera.capture": ("pi.camera", _cmd_camera),
    "pi.sensor.read": ("pi.sensors", _cmd_sensor),
    "pi.gpio.read": ("pi.gpio", _cmd_gpio_read),
    "pi.gpio.write": ("pi.gpio", _cmd_gpio_write),
    "pi.led.set": ("pi.led", _cmd_led),
    "pi.audio.status": ("pi.audio", _cmd_none),
}


def validate_command(command: str, args: dict[str, Any] | None,
                     gpio_pins: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate a typed Pi command. Returns {command, capability, args}."""
    if command not in SAFE_COMMANDS:
        raise PiCommandError(
            f"command not on the safe allowlist: {command!r}")
    capability, schema = SAFE_COMMANDS[command]
    clean = dict(args or {})
    if schema in (_cmd_gpio_read, _cmd_gpio_write):
        clean = schema(clean, gpio_pins or {})
    else:
        clean = schema(clean)
    return {"command": command, "capability": capability, "args": clean}


def validate_pi_event(event_type: str,
                      payload: dict[str, Any] | None) -> dict[str, Any]:
    """Validate a typed Pi event. Unknown names are rejected."""
    if event_type not in PI_EVENTS:
        raise PiError(f"unknown pi event: {event_type!r}")
    data = dict(payload or {})
    if len(str(data)) > 4096:
        raise PiError("pi event payload exceeds 4 KiB")
    return {"type": event_type, "payload": data}


@dataclass
class QueuedPiCommand:
    command_id: str = field(default_factory=lambda: new_id("pcmd"))
    device_id: str = ""
    command: str = ""
    capability: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    actor: str = ""
    created_at: float = field(default_factory=now)
    expires_at: float = 0.0

    def expired(self, at: float | None = None) -> bool:
        stamp = at if at is not None else now()
        return bool(self.expires_at and stamp >= self.expires_at)

    def to_dict(self) -> dict[str, Any]:
        return {"command_id": self.command_id, "device_id": self.device_id,
                "command": self.command, "capability": self.capability,
                "args": self.args, "actor": self.actor,
                "created_at": self.created_at,
                "expires_at": self.expires_at}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "QueuedPiCommand":
        return cls(command_id=str(data.get("command_id", new_id("pcmd"))),
                   device_id=str(data.get("device_id", "")),
                   command=str(data.get("command", "")),
                   capability=str(data.get("capability", "")),
                   args=dict(data.get("args", {}) or {}),
                   actor=str(data.get("actor", "")),
                   created_at=float(data.get("created_at", 0.0) or 0.0),
                   expires_at=float(data.get("expires_at", 0.0) or 0.0))


__all__ = [
    "PI_PLATFORM",
    "PI_DEVICE_TYPE",
    "PI_ADAPTER_VERSION",
    "PI_CAPABILITIES",
    "PI_EVENTS",
    "PROACTIVE_PI_EVENTS",
    "SAFE_COMMANDS",
    "COMMAND_QUEUE_MAX",
    "COMMAND_TTL_S",
    "PiError",
    "PiCommandError",
    "QueuedPiCommand",
    "validate_command",
    "validate_pi_metadata",
    "validate_pi_event",
]
