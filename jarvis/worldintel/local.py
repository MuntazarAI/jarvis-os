"""Local-world providers (World Intelligence 1.0).

Boundaries for authorized LOCAL state entering the same evidence
architecture as external sources. Classification is LOCAL or PRIVATE
by default — local observations never leave the machine through this
layer, and are labeled so downstream code cannot mistake them for
public web evidence.

Providers are read-only status snapshots (never actions):
- computer: ComputerController.status() + window/clipboard presence.
- devices: device-fabric snapshot (counts only, no secrets).
- services: serve/doctor-derived service state.

Home Assistant and OpenClaw are explicit future boundaries: adapter
stubs document the contract (observations in, actions via PolicyEngine
only) without implementing them.
"""

from __future__ import annotations

import time
from typing import Any

from .sources import EvidenceItem


def computer_snapshot() -> list[EvidenceItem]:
    """Read-only local computer state as evidence (LOCAL class)."""
    stamp = time.time()
    try:
        from ..computer.computer import ComputerController
        status = ComputerController().status()
    except Exception as exc:
        return [EvidenceItem(
            source_id="local-computer", title="computer unavailable",
            text=f"computer status failed: {type(exc).__name__}")]
    lines = [f"{key}={value}" for key, value in sorted(
        status.items()) if not isinstance(value, dict)]
    return [EvidenceItem(
        source_id="local-computer", title="local computer state",
        retrieved_at=stamp, text="; ".join(lines)[:2000])]


def device_snapshot(fabric: Any = None) -> list[EvidenceItem]:
    """Device counts only — no keys, tokens, or pairing material."""
    stamp = time.time()
    try:
        from ..device.fabric import DeviceFabric
        from ..policy.policy import PolicyEngine
        from ..core.config import JarvisConfig
        fabric = fabric or DeviceFabric(
            home=".", policy=PolicyEngine(JarvisConfig()))
        counts = fabric.status() if hasattr(fabric, "status") else {}
    except Exception as exc:
        return [EvidenceItem(
            source_id="local-devices", title="devices unavailable",
            text=f"device snapshot failed: {type(exc).__name__}")]
    safe = {k: v for k, v in (counts or {}).items()
            if isinstance(v, (int, float, bool, str))}
    return [EvidenceItem(
        source_id="local-devices", title="local device snapshot",
        retrieved_at=stamp,
        text="; ".join(f"{k}={v}" for k, v in sorted(
            safe.items()))[:2000])]


# -- future adapter boundaries (stubs, not implementations) ---------------

def home_assistant_spec() -> dict[str, Any]:
    """Contract a future Home Assistant adapter must satisfy."""
    return {
        "direction": "observations in only",
        "classification": "local",
        "actions": "via PolicyEngine + DeviceCommandService only, "
                   "never from World Intelligence directly",
        "required": ["entity_id", "state", "observed_at", "source"],
        "forbidden": ["credentials", "tokens", "raw network details"],
    }


def openclaw_spec() -> dict[str, Any]:
    """Contract a future OpenClaw adapter must satisfy."""
    return {
        "direction": "observations in only",
        "classification": "local",
        "actions": "via PolicyEngine only",
        "required": ["node_id", "capability", "observed_at", "source"],
        "forbidden": ["credentials", "tokens", "raw network details"],
    }


__all__ = ["computer_snapshot", "device_snapshot",
           "home_assistant_spec", "openclaw_spec"]
