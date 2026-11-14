"""Files that must never be read by an agent or a perception tool.

One list, used by both the perception providers and the tool layer, so
"never readable" means the same thing everywhere. The credential stores
hold the vault key, the approval tokens and the standing grants: reading
one turns a file read into a credential leak.

The rule is fail closed — a refusal, not a redaction.
"""

from __future__ import annotations

from pathlib import Path

#: Absolute paths that are never readable.
PROTECTED_PATHS: tuple[str, ...] = (
    "/etc/shadow", "/etc/sudoers", "/etc/gshadow", "/etc/master.passwd",
)

#: File names that are never readable, wherever they live.
PROTECTED_NAMES: tuple[str, ...] = (
    "id_rsa", "id_ed25519", "id_ecdsa", ".pem", ".key", ".p12", ".pfx",
    "secrets.json", ".vault.key", "policy-approvals.json",
    "device-approvals.json", "credentials.json", ".env", ".netrc",
    "_history", "cookies.sqlite", "Login Data", "keystore", "wallet.dat",
)


def is_protected(resolved: Path | str) -> str:
    """Return the reason this path is protected, or "" when it is fine."""
    try:
        text = str(resolved)
    except Exception:
        return ""
    for blocked in PROTECTED_PATHS:
        if text == blocked or text.startswith(blocked + "/"):
            return f"credential store: {blocked}"
    name = Path(text).name
    for blocked in PROTECTED_NAMES:
        if blocked in name:
            return f"credential store: {blocked}"
    return ""


__all__ = ["PROTECTED_PATHS", "PROTECTED_NAMES", "is_protected"]
