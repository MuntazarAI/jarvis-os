"""Experience Layer foundation: UI as a consumer of existing JARVIS state.

No new agent runtime, task engine, policy engine, memory, world model,
event bus, or scheduler is created here. This module only assembles
read-only snapshots from authoritative subsystems and exposes them for
external UI shells. Actions still flow through the existing policy gates.
"""

from __future__ import annotations

from typing import Any

def status_snapshot(jarvis: Any) -> dict[str, Any]:
    """Return a read-only, bounded snapshot of the current JARVIS state.

    The snapshot is assembled from existing subsystems only. It is
    untrusted input for any UI that renders it.
    """
    try:
        devices = jarvis.devices_status() if hasattr(jarvis, "devices_status") else {}
    except Exception:
        devices = {"ok": False, "error": "devices unavailable"}

    try:
        snapshot = {
            "ok": True,
            "source": "experience-foundation",
            "note": "UI layer consumes existing state only. No new runtime.",
            "devices": devices,
            "timestamp": jarvis._now() if hasattr(jarvis, "_now") else None,
        }
        return snapshot
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
