"""Secrets vault, sessions, consent and privacy."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    _HAS_CRYPTOGRAPHY = True
except Exception:
    _HAS_CRYPTOGRAPHY = False

from ..core.types import new_id, now


def _xor(data: bytes, key: bytes) -> bytes:
    """Legacy XOR cipher for backward compatibility only."""
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


class SecretVault:
    """Local encrypted-at-rest store with AES-GCM (preferred) or legacy XOR+HMAC.

    - Key sourced from env `JARVIS_VAULT_KEY` or generated file (0600).
    - AES-GCM used when `cryptography` is available; otherwise falls back to
      XOR+HMAC for compatibility with existing blobs.
    - All blobs are authenticated; tampered blobs raise ValueError.
    - Access is logged with actor, timestamp, and operation type.
    """

    VAULT_VERSION = 2  # v1 = XOR+HMAC, v2 = AES-GCM

    def __init__(self, home: Path | str) -> None:
        self.home = Path(home)
        self.home.mkdir(parents=True, exist_ok=True)
        self.key_file = self.home / ".vault.key"
        self.store_file = self.home / "secrets.json"
        self._lock = threading.RLock()
        self._key = self._load_or_create_key()
        self._secrets: dict[str, dict[str, Any]] = self._load()
        self.access_log: list[dict[str, Any]] = []

    def _load_or_create_key(self) -> bytes:
        env = os.environ.get("JARVIS_VAULT_KEY")
        if env:
            return hashlib.sha256(env.encode()).digest()
        if self.key_file.exists():
            return bytes.fromhex(self.key_file.read_text().strip())
        key = secrets.token_bytes(32)
        self.key_file.write_text(key.hex())
        try:
            os.chmod(self.key_file, 0o600)
        except OSError:
            pass
        return key

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self.store_file.exists():
            return {}
        try:
            return json.loads(self.store_file.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

    def _save(self) -> None:
        with self._lock:
            self.store_file.write_text(json.dumps(self._secrets, indent=2))
            try:
                os.chmod(self.store_file, 0o600)
            except OSError:
                pass

    def _seal_aesgcm(self, plaintext: str) -> str:
        """Encrypt with AES-GCM (256-bit key, 96-bit nonce)."""
        nonce = secrets.token_bytes(12)
        aead = AESGCM(self._key)
        sealed = aead.encrypt(nonce, plaintext.encode(), None)
        # Store: version(1) | nonce(12) | ciphertext+tag
        blob = bytes([self.VAULT_VERSION]) + nonce + sealed
        return base64.b64encode(blob).decode()

    def _open_aesgcm(self, blob: str) -> str:
        """Decrypt AES-GCM blob, verifying authentication tag."""
        raw = base64.b64decode(blob)
        if not raw:
            raise ValueError("empty blob")
        version = raw[0]
        if version != self.VAULT_VERSION:
            raise ValueError(f"unsupported vault version: {version}")
        if len(raw) < 1 + 12 + 16:  # version + nonce + min tag
            raise ValueError("blob too short")
        nonce = raw[1:13]
        sealed = raw[13:]
        aead = AESGCM(self._key)
        return aead.decrypt(nonce, sealed, None).decode()

    def _seal_legacy(self, plaintext: str) -> str:
        """Legacy XOR + HMAC-SHA256 for backward compatibility."""
        raw = plaintext.encode()
        sealed = _xor(raw, self._key)
        mac = hmac.new(self._key, sealed, hashlib.sha256).hexdigest()
        return base64.b64encode(sealed).decode() + "." + mac

    def _open_legacy(self, blob: str) -> str:
        """Legacy XOR + HMAC open."""
        try:
            encoded, mac = blob.rsplit(".", 1)
        except ValueError:
            raise ValueError("corrupt legacy blob")
        sealed = base64.b64decode(encoded)
        if not hmac.compare_digest(mac, hmac.new(self._key, sealed, hashlib.sha256).hexdigest()):
            raise ValueError("secret integrity check failed")
        return _xor(sealed, self._key).decode()

    def _seal(self, plaintext: str) -> str:
        if _HAS_CRYPTOGRAPHY:
            return self._seal_aesgcm(plaintext)
        return self._seal_legacy(plaintext)

    def _open(self, blob: str) -> str:
        # Detect format: AES-GCM blobs are base64 without '.' and start with version byte
        if _HAS_CRYPTOGRAPHY and "." not in blob:
            try:
                return self._open_aesgcm(blob)
            except Exception:
                # Fall through to legacy if somehow corrupted
                pass
        return self._open_legacy(blob)

    def _log(self, op: str, name: str, actor: str, ok: bool, detail: str = "") -> None:
        self.access_log.append({
            "op": op,
            "name": name,
            "actor": actor,
            "at": now(),
            "ok": ok,
            "detail": detail[:200],
        })
        # Bound the log
        if len(self.access_log) > 1000:
            self.access_log = self.access_log[-1000:]

    def put(self, name: str, value: str, expires_in: float | None = None) -> None:
        with self._lock:
            if not name or len(name) > 256:
                raise ValueError("invalid secret name")
            if len(value) > 65536:
                raise ValueError("secret value too large")
            self._secrets[name] = {
                "blob": self._seal(value),
                "created": now(),
                "expires_at": now() + expires_in if expires_in else None,
                "version": self.VAULT_VERSION,
            }
            self._save()
            self._log("put", name, "jarvis", True)

    def get(self, name: str, actor: str = "jarvis") -> str | None:
        with self._lock:
            entry = self._secrets.get(name)
            if not entry:
                self._log("get", name, actor, False, "not found")
                return None
            if entry.get("expires_at") and entry["expires_at"] <= now():
                del self._secrets[name]
                self._save()
                self._log("get", name, actor, False, "expired")
                return None
            try:
                value = self._open(entry["blob"])
                self._log("get", name, actor, True)
                return value
            except Exception as exc:
                self._log("get", name, actor, False, f"decrypt failed: {type(exc).__name__}")
                raise

    def delete(self, name: str) -> bool:
        with self._lock:
            if name not in self._secrets:
                self._log("delete", name, "jarvis", False, "not found")
                return False
            del self._secrets[name]
            self._save()
            self._log("delete", name, "jarvis", True)
            return True

    def rotate(self, name: str, value: str) -> bool:
        with self._lock:
            if name not in self._secrets:
                self._log("rotate", name, "jarvis", False, "not found")
                return False
            self.put(name, value)
            self._log("rotate", name, "jarvis", True)
            return True

    def rotate_key(self, new_key: bytes | None = None) -> int:
        """Re-encrypt all secrets with a new master key.

        Returns the number of secrets rotated. Caller must ensure the
        new key is stored in `JARVIS_VAULT_KEY` or `.vault.key` before
        next vault instantiation.
        """
        if new_key is None:
            new_key = secrets.token_bytes(32)
        old_key = self._key
        self._key = new_key
        count = 0
        with self._lock:
            for name, entry in list(self._secrets.items()):
                try:
                    # Decrypt with old key
                    blob = entry["blob"]
                    if _HAS_CRYPTOGRAPHY and "." not in blob:
                        # AES-GCM
                        raw = base64.b64decode(blob)
                        nonce = raw[1:13]
                        sealed = raw[13:]
                        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
                        aead = AESGCM(old_key)
                        plaintext = aead.decrypt(nonce, sealed, None).decode()
                    else:
                        # Legacy
                        encoded, mac = blob.rsplit(".", 1)
                        sealed = base64.b64decode(encoded)
                        if not hmac.compare_digest(mac, hmac.new(old_key, sealed, hashlib.sha256).hexdigest()):
                            raise ValueError("integrity check failed")
                        plaintext = _xor(sealed, old_key).decode()
                    # Re-encrypt with new key
                    entry["blob"] = self._seal(plaintext)
                    entry["version"] = self.VAULT_VERSION
                    count += 1
                except Exception:
                    # Leave corrupted entry alone
                    continue
            self._save()
        return count

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._secrets)

    def audit_log(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            return list(self.access_log[-limit:])


@dataclass
class Session:
    session_id: str = field(default_factory=lambda: new_id("sess"))
    user: str = "user"
    created: float = field(default_factory=now)
    last_active: float = field(default_factory=now)
    expires_at: float = field(default_factory=lambda: now() + 86400)
    permissions: list[str] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    branched_from: str = ""

    def touch(self) -> None:
        self.last_active = now()

    @property
    def expired(self) -> bool:
        return now() >= self.expires_at


class SessionEngine:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = threading.RLock()

    def create(self, user: str = "user", permissions: list[str] | None = None,
               ttl: float = 86400.0) -> Session:
        sess = Session(user=user, permissions=permissions or [],
                       expires_at=now() + ttl)
        with self._lock:
            self._sessions[sess.session_id] = sess
        return sess

    def get(self, session_id: str) -> Session | None:
        with self._lock:
            sess = self._sessions.get(session_id)
            if not sess:
                return None
            if sess.expired:
                del self._sessions[session_id]
                return None
            sess.touch()
            return sess

    def branch(self, session_id: str) -> Session | None:
        with self._lock:
            parent = self._sessions.get(session_id)
            if not parent:
                return None
            child = Session(user=parent.user, permissions=list(parent.permissions),
                            context=dict(parent.context), branched_from=session_id)
            self._sessions[child.session_id] = child
            return child

    def end(self, session_id: str) -> bool:
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

    def active(self) -> list[Session]:
        with self._lock:
            live = []
            for sid in list(self._sessions):
                sess = self._sessions[sid]
                if sess.expired:
                    del self._sessions[sid]
                else:
                    live.append(sess)
            return live


class ConsentEngine:
    """Per-data, per-device, per-sensor consent with retention policies."""

    SCOPES = ("camera", "microphone", "memory", "sharing", "sensors", "location")

    def __init__(self) -> None:
        self.grants: dict[str, dict[str, Any]] = {}
        self.history: list[dict[str, Any]] = []

    def grant(self, scope: str, actor: str = "user",
              expires_in: float | None = None) -> None:
        if scope not in self.SCOPES:
            raise ValueError(f"unknown consent scope: {scope}")
        self.grants[scope] = {"by": actor, "at": now(),
                              "expires_at": now() + expires_in if expires_in else None}
        self.history.append({"scope": scope, "decision": "granted",
                             "by": actor, "at": now()})

    def revoke(self, scope: str, actor: str = "user") -> None:
        self.grants.pop(scope, None)
        self.history.append({"scope": scope, "decision": "revoked",
                             "by": actor, "at": now()})

    def allowed(self, scope: str) -> bool:
        grant = self.grants.get(scope)
        if not grant:
            return False
        if grant.get("expires_at") and grant["expires_at"] <= now():
            self.grants.pop(scope, None)
            return False
        return True

    def require(self, scope: str) -> None:
        if not self.allowed(scope):
            raise PermissionError(f"consent required for: {scope}")

    def export(self) -> dict[str, Any]:
        return {"grants": {k: {**v} for k, v in self.grants.items()},
                "history": list(self.history)}