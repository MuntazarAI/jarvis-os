"""Durable audit log for device authorization and control (4.2).

Append-only JSONL at ``<home>/device-audit.jsonl``: every record is one
line, so a crash can never corrupt earlier records and readers never
need to parse a half-written file. Records reuse the
:func:`jarvis.device.security.audit_record` shape (event, actor,
device_id, ok, reasons, at) plus free-form ``extra`` — always scrubbed,
never carrying secrets.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .security import audit_record

AUDIT_FILENAME = "device-audit.jsonl"
MAX_LINE_BYTES = 64 * 1024


class DeviceAudit:
    """Append-only audit sink. Best-effort, never raises."""

    def __init__(self, home: str | Path | None) -> None:
        self.home = Path(home) if home else None

    @property
    def path(self) -> Path | None:
        if self.home is None:
            return None
        return self.home / AUDIT_FILENAME

    def record(self, event: str, *, actor: str = "", device_id: str = "",
               ok: bool = True, reasons: list[str] | None = None,
               extra: dict[str, Any] | None = None) -> dict[str, Any]:
        """Append one audit record. Returns the record (also on I/O failure)."""
        entry = audit_record(event, actor=actor, device_id=device_id,
                             ok=ok, reasons=reasons,
                             extra=dict(extra or {}))
        line = json.dumps(entry, sort_keys=True, default=str)
        if len(line.encode("utf-8")) > MAX_LINE_BYTES:
            line = json.dumps(dict(entry, extra={"truncated": True}),
                              sort_keys=True, default=str)
        path = self.path
        if path is not None:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(path, "a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
                    handle.flush()
                    try:
                        os.fsync(handle.fileno())
                    except OSError:
                        pass
            except OSError:
                pass
        return entry

    def tail(self, limit: int = 100) -> list[dict[str, Any]]:
        """Newest-first slice. Corrupt lines are skipped, never fatal."""
        path = self.path
        if path is None or not path.exists():
            return []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out: list[dict[str, Any]] = []
        for raw in reversed(lines[-max(limit, 1):]):
            try:
                item = json.loads(raw)
            except ValueError:
                continue
            if isinstance(item, dict):
                out.append(item)
        return out

    def count(self) -> int:
        path = self.path
        if path is None or not path.exists():
            return 0
        try:
            with open(path, "rb") as handle:
                return sum(1 for _ in handle)
        except OSError:
            return 0


__all__ = ["DeviceAudit", "AUDIT_FILENAME"]
