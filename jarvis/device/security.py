"""Security helpers for the device fabric.

The fabric reuses the existing JARVIS security architecture and adds only
fabric-specific enforcement:

- secret-looking keys are REJECTED (not stored) in device metadata and
  telemetry extras — secrets must never land in device state;
- persisted/logged structures go through ``scrub`` (drop secret keys,
  truncate long strings), mirroring dots/missions persistence;
- device-supplied text is injection-scanned and sanitized before it can
  reach prompts, dots, or memory;
- every trust decision and routed command produces an audit record.
"""

from __future__ import annotations

from typing import Any

from ..core.types import now
from ..security.guards import sanitize_for_context, scan_injection

#: Substrings that mark a mapping key as secret-bearing. Mirrors the
#: dots/missions ``_scrub`` convention plus key-material hints.
SECRET_KEY_HINTS = (
    "password",
    "secret",
    "token",
    "credential",
    "api_key",
    "apikey",
    "private_key",
    "privatekey",
    "auth",
    "passphrase",
    "seed_phrase",
)


class FabricSecurityError(ValueError):
    """Raised when device-supplied data violates a security rule."""


def _is_secret_key(key: str) -> bool:
    lowered = key.lower()
    return any(hint in lowered for hint in SECRET_KEY_HINTS)


def scrub(value: Any) -> Any:
    """Drop secret-bearing keys, truncate long strings. For logs/traces."""
    if isinstance(value, dict):
        return {
            k: scrub(v) for k, v in value.items()
            if not _is_secret_key(str(k))
        }
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, str) and len(value) > 200:
        return value[:200] + "\u2026[truncated]"
    return value


def reject_secrets(mapping: dict[str, Any], where: str) -> dict[str, Any]:
    """Refuse to accept secret-bearing keys into persisted device state."""
    if not isinstance(mapping, dict):
        raise FabricSecurityError(f"{where} must be an object")
    for key in mapping:
        if _is_secret_key(str(key)):
            raise FabricSecurityError(
                f"{where} must not contain secret material (key {key!r} refused)"
            )
    return mapping


def check_text(text: str) -> dict[str, Any]:
    """Injection scan for device-supplied text. Returns the scan report."""
    return scan_injection(text or "")


def sanitize_text(text: str, limit: int = 500) -> str:
    """Quote device-supplied text as untrusted content for prompts/memory."""
    return sanitize_for_context(text or "", limit)


def audit_record(action: str, *, actor: str = "", device_id: str = "",
                 ok: bool = True, reasons: list[str] | None = None,
                 extra: dict[str, Any] | None = None) -> dict[str, Any]:
    record: dict[str, Any] = {
        "event": action,
        "actor": actor,
        "device_id": device_id,
        "ok": ok,
        "reasons": list(reasons or []),
        "at": now(),
    }
    if extra:
        record["extra"] = scrub(extra)
    return record
