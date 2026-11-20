"""Accounts for the public JARVIS platform.

People sign up, sign in and get their own JARVIS. This module owns
the two things that make that safe:

- **Passwords**: scrypt with a per-user salt (stdlib, no third-party
  crypto). The hash is never written to a log or returned by an API.
- **Sessions**: server-side session ids in an `HttpOnly` cookie, so a
  session can be revoked the moment it looks wrong.

The store is a plain JSON file. It is small, it is inspectable, and it
can be reverted — the same rule the rest of JARVIS follows.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any

#: A password hash costs this much memory; slow enough to hurt a
#: brute-force, cheap enough for a sign-up form.
SCRYPT_N = 2 ** 14
SCRYPT_R = 8
SCRYPT_P = 1

#: How long a session stays valid.
SESSION_TTL_S = 7 * 24 * 3600

#: Emails are used as a login name and for nothing else.
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]{2,}$")

#: A password has to be long enough to matter.
MIN_PASSWORD_LEN = 10


def normalize_email(email: str) -> str:
    """Lower-cased, trimmed email. The login name."""
    return str(email or "").strip().lower()


def valid_email(email: str) -> bool:
    return bool(EMAIL_PATTERN.match(normalize_email(email)))


def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    """(salt_hex, hash_hex) for a password."""
    salt = salt or os.urandom(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt,
                            n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P,
                            maxmem=SCRYPT_N * SCRYPT_R * 256)
    return salt.hex(), digest.hex()


def verify_password(password: str, salt_hex: str, hash_hex: str) -> bool:
    """Is this the right password? Constant-time comparison."""
    try:
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False
    try:
        _, candidate = hash_password(password, salt)
    except (ValueError, MemoryError):
        return False
    return hmac.compare_digest(candidate, str(hash_hex or ""))


def new_user_id() -> str:
    """An opaque user id (never the email, never sequential)."""
    return "u-" + secrets.token_hex(8)


class UserStore:
    """The people who have an account."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.path = self.root / "users.json"
        # RLock: resolve() drops an expired session while it holds
        # the lock, so the lock has to be re-entrant.
        self._lock = threading.RLock()

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self, data: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(data, indent=2, sort_keys=True),
                        encoding="utf-8")
        temp.replace(self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def create(self, email: str, password: str) -> dict[str, Any]:
        """Create an account. Raises ValueError with a readable reason."""
        email = normalize_email(email)
        if not valid_email(email):
            raise ValueError("that does not look like an email address")
        if len(str(password or "")) < MIN_PASSWORD_LEN:
            raise ValueError(
                f"the password needs at least {MIN_PASSWORD_LEN} characters")
        with self._lock:
            users = self._load()
            if email in users:
                raise ValueError("there is already an account with that email")
            salt, digest = hash_password(password)
            user = {
                "id": new_user_id(),
                "email": email,
                "salt": salt,
                "hash": digest,
                "created_at": time.time(),
                "last_seen": time.time(),
            }
            users[email] = user
            self._save(users)
        return {"id": user["id"], "email": user["email"]}

    def authenticate(self, email: str, password: str) -> dict[str, Any] | None:
        """The account for these credentials, or None."""
        email = normalize_email(email)
        with self._lock:
            users = self._load()
            user = users.get(email)
            if not isinstance(user, dict):
                # Spend the time anyway: an unknown email must not be
                # faster than a wrong password.
                hash_password(str(password or ""))
                return None
            if not verify_password(str(password or ""), user.get("salt", ""),
                                   user.get("hash", "")):
                return None
            user["last_seen"] = time.time()
            self._save(users)
            return {"id": user["id"], "email": user["email"]}

    def get(self, user_id: str) -> dict[str, Any] | None:
        """The account with this id (no password material)."""
        with self._lock:
            for user in self._load().values():
                if isinstance(user, dict) and user.get("id") == user_id:
                    return {"id": user["id"], "email": user["email"],
                            "created_at": user.get("created_at", 0)}
        return None

    def get_by_email(self, email: str) -> dict[str, Any] | None:
        """The account with this email (no password material)."""
        email = normalize_email(email)
        with self._lock:
            user = self._load().get(email)
            if not isinstance(user, dict):
                return None
            return {"id": user["id"], "email": user["email"],
                    "created_at": user.get("created_at", 0)}

    def change_password(self, email: str, old_password: str,
                        new_password: str) -> bool:
        """Replace a password. The old one must be right."""
        email = normalize_email(email)
        if len(str(new_password or "")) < MIN_PASSWORD_LEN:
            raise ValueError(
                f"the password needs at least {MIN_PASSWORD_LEN} characters")
        with self._lock:
            users = self._load()
            user = users.get(email)
            if not isinstance(user, dict):
                return False
            if not verify_password(str(old_password or ""),
                                   user.get("salt", ""), user.get("hash", "")):
                return False
            salt, digest = hash_password(str(new_password))
            user["salt"] = salt
            user["hash"] = digest
            users[email] = user
            self._save(users)
            return True

    def delete(self, user_id: str) -> bool:
        """Remove the account. Returns False when there was none."""
        with self._lock:
            users = self._load()
            gone = [email for email, user in users.items()
                    if isinstance(user, dict) and user.get("id") == user_id]
            if not gone:
                return False
            for email in gone:
                users.pop(email, None)
            self._save(users)
            return True

    def count(self) -> int:
        with self._lock:
            return len(self._load())


class SessionStore:
    """Server-side sessions. The cookie carries only the id."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.path = self.root / "sessions.json"
        # RLock: resolve() drops an expired session while it holds
        # the lock, so the lock has to be re-entrant.
        self._lock = threading.RLock()

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self, data: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(data, indent=2, sort_keys=True),
                        encoding="utf-8")
        temp.replace(self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def create(self, user_id: str,
               ttl_s: float = SESSION_TTL_S) -> tuple[str, float]:
        """(session_id, expires_at) for a new session."""
        token = secrets.token_urlsafe(32)
        expires = time.time() + ttl_s
        with self._lock:
            sessions = self._load()
            now = time.time()
            for key, value in list(sessions.items()):
                if not isinstance(value, dict) or \
                        float(value.get("expires_at", 0)) < now:
                    sessions.pop(key, None)
            sessions[token] = {"user_id": user_id, "created_at": now,
                               "expires_at": expires}
            self._save(sessions)
        return token, expires

    def resolve(self, token: str) -> str | None:
        """The user id behind a session id, or None."""
        if not token:
            return None
        with self._lock:
            session = self._load().get(token)
            if not isinstance(session, dict):
                return None
            if float(session.get("expires_at", 0)) < time.time():
                self.drop(token)
                return None
            user_id = str(session.get("user_id") or "")
            return user_id or None

    def drop(self, token: str) -> bool:
        """Revoke a session."""
        if not token:
            return False
        with self._lock:
            sessions = self._load()
            if token not in sessions:
                return False
            sessions.pop(token, None)
            self._save(sessions)
            return True

    def drop_user(self, user_id: str) -> int:
        """Revoke every session of a user. Returns how many."""
        with self._lock:
            sessions = self._load()
            gone = [key for key, value in sessions.items()
                    if isinstance(value, dict)
                    and value.get("user_id") == user_id]
            for key in gone:
                sessions.pop(key, None)
            if gone:
                self._save(sessions)
            return len(gone)


def new_cookie(name: str, value: str, *, max_age: int = SESSION_TTL_S,
               secure: bool = False) -> str:
    """A session cookie. HttpOnly so scripts cannot read it."""
    parts = [f"{name}={value}", "Path=/", "HttpOnly",
             f"Max-Age={int(max_age)}", "SameSite=Lax"]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def parse_cookies(header: str) -> dict[str, str]:
    """The cookies in a request header."""
    out: dict[str, str] = {}
    for part in str(header or "").split(";"):
        if "=" not in part:
            continue
        name, _, value = part.partition("=")
        out[name.strip()] = value.strip()
    return out


def sign_token(payload: str, secret: str) -> str:
    """A signed value (used for anything that must not be editable)."""
    mac = hmac.new(secret.encode(), payload.encode(),
                   hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode().rstrip("=")


__all__ = ["UserStore", "SessionStore", "hash_password", "verify_password",
           "normalize_email", "valid_email", "new_user_id", "new_cookie",
           "parse_cookies", "sign_token", "SESSION_TTL_S", "MIN_PASSWORD_LEN"]
