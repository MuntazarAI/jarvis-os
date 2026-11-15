"""The public platform: sign up, sign in, chat.

This is the part a visitor touches. Everything it does is local to the
server: no third-party service sees a user's message, and one person's
data never reaches another person's answers.

Rules:
- a session is an `HttpOnly` cookie; the password never leaves the
  server in any form;
- every message goes through the normal JARVIS path
  (perception → cognition → policy), so a visitor's text is untrusted
  input, never an instruction;
- one conversation at a time per person, and a rate limit, so one
  account cannot spend the whole model budget;
- when JARVIS wants to do something that needs a human, the human is
  asked in the chat, in that person's own session.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

from .accounts import (SessionStore, UserStore, new_cookie, parse_cookies,
                       valid_email)
from .users import UserRegistry

#: The cookie that carries the session id.
SESSION_COOKIE = "jarvis_session"

#: How many messages one person may send per minute.
MESSAGES_PER_MINUTE = 20

#: How long a message may be.
MAX_MESSAGE_CHARS = 8000

#: How many conversations are listed at once.
MAX_LISTED_CONVERSATIONS = 50


class Platform:
    """The public side of JARVIS."""

    def __init__(self, root: str | Path, template_config: Path | None = None,
                 speak: bool = True) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.users = UserStore(self.root)
        self.sessions = SessionStore(self.root)
        self.spaces = UserRegistry(self.root, template_config)
        self.speak = speak
        self._rate: dict[str, list[float]] = {}

    # -- helpers ------------------------------------------------------------
    def _session_user(self, headers: dict[str, str]) -> str | None:
        cookies = parse_cookies(headers.get("cookie", ""))
        token = cookies.get(SESSION_COOKIE, "")
        return self.sessions.resolve(token)

    def _rate_ok(self, user_id: str) -> bool:
        """One person, one conversation at a time, within a budget."""
        now = time.time()
        recent = [t for t in self._rate.get(user_id, []) if now - t < 60]
        if len(recent) >= MESSAGES_PER_MINUTE:
            self._rate[user_id] = recent
            return False
        recent.append(now)
        self._rate[user_id] = recent
        return True

    @staticmethod
    def _json_body(body: bytes) -> dict[str, Any]:
        try:
            data = json.loads(body.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _space(self, user_id: str):
        return self.spaces.space(user_id)

    # -- routes -------------------------------------------------------------
    def handle(self, method: str, path: str, body: bytes,
               headers: dict[str, str]) -> tuple[int, dict[str, Any]]:
        """Answer a platform request. None means "not mine"."""
        route = path.split("?", 1)[0].rstrip("/") or "/"
        if method == "GET" and route in ("/", "/chat"):
            return self._page()
        if method == "POST" and route == "/api/signup":
            return self._signup(body)
        if method == "POST" and route == "/api/login":
            return self._login(body)
        if method == "POST" and route == "/api/logout":
            return self._logout(headers)
        if method == "GET" and route == "/api/me":
            return self._me(headers)
        if method == "POST" and route == "/api/chat":
            return self._chat(body, headers)
        if method == "GET" and route == "/api/history":
            return self._history(headers)
        if method == "POST" and route == "/api/speak":
            return self._speak(body, headers)
        if method == "GET" and route == "/api/conversations":
            return self._conversations(headers)
        if method == "POST" and route == "/api/conversations":
            return self._new_conversation(body, headers)
        if method == "DELETE" and route.startswith("/api/conversations/"):
            return self._delete_conversation(
                route.rsplit("/", 1)[-1], headers)
        if route.startswith("/api/conversations/") and \
                route.count("/") == 3 and method == "GET":
            return self._conversation_messages(route.split("/")[3], headers)
        if method == "POST" and route == "/api/approvals":
            return self._approval_decision(body, headers)
        if method == "GET" and route == "/api/approvals":
            return self._approvals_pending(headers)
        if method == "POST" and route == "/api/account/password":
            return self._change_password(body, headers)
        if method == "POST" and route == "/api/account/delete":
            return self._delete_account(headers)
        return 404, {"error": "not found"}

    def _page(self) -> tuple[int, dict]:
        # The page is rebuilt on every request, so a refresh always
        # shows the current design while it is being worked on.
        import importlib
        from . import chat as chat_module
        importlib.reload(chat_module)
        return 200, {"__html__": chat_module.CHAT_HTML}

    # -- accounts -----------------------------------------------------------
    def _signup(self, body: bytes) -> tuple[int, dict[str, Any]]:
        data = self._json_body(body)
        email = str(data.get("email") or "")
        password = str(data.get("password") or "")
        if not valid_email(email):
            return 400, {"error": "that does not look like an email address"}
        try:
            user = self.users.create(email, password)
        except ValueError as exc:
            return 400, {"error": str(exc)}
        space = self._space(user["id"])
        space.ensure_home()
        space.new_conversation()
        token, expires = self.sessions.create(user["id"])
        return 200, {"ok": True, "email": user["email"],
                     "set_cookie": new_cookie(SESSION_COOKIE, token,
                                              max_age=int(expires -
                                                         time.time()))}

    def _login(self, body: bytes) -> tuple[int, dict[str, Any]]:
        data = self._json_body(body)
        user = self.users.authenticate(str(data.get("email") or ""),
                                       str(data.get("password") or ""))
        if not user:
            # One message for both "no such account" and "wrong
            # password": the caller learns nothing about who exists.
            return 401, {"error": "email or password is wrong"}
        token, expires = self.sessions.create(user["id"])
        return 200, {"ok": True, "email": user["email"],
                     "set_cookie": new_cookie(SESSION_COOKIE, token,
                                              max_age=int(expires -
                                                         time.time()))}

    def _logout(self, headers: dict[str, str]) -> tuple[int, dict[str, Any]]:
        cookies = parse_cookies(headers.get("cookie", ""))
        self.sessions.drop(cookies.get(SESSION_COOKIE, ""))
        return 200, {"ok": True,
                     "set_cookie": new_cookie(SESSION_COOKIE, "",
                                              max_age=0)}

    def _me(self, headers: dict[str, str]) -> tuple[int, dict[str, Any]]:
        user_id = self._session_user(headers)
        if not user_id:
            return 401, {"error": "not signed in"}
        user = self.users.get(user_id)
        if not user:
            return 401, {"error": "not signed in"}
        return 200, {"id": user["id"], "email": user["email"]}

    def _change_password(self, body: bytes,
                         headers: dict[str, str]) -> tuple[int, dict[str, Any]]:
        user_id = self._session_user(headers)
        if not user_id:
            return 401, {"error": "not signed in"}
        user = self.users.get(user_id)
        if not user:
            return 401, {"error": "not signed in"}
        data = self._json_body(body)
        try:
            changed = self.users.change_password(
                user["email"], str(data.get("current") or ""),
                str(data.get("new") or ""))
        except ValueError as exc:
            return 400, {"error": str(exc)}
        if not changed:
            return 400, {"error": "the current password is wrong"}
        # Every other session of this person is now suspect.
        self.sessions.drop_user(user_id)
        token, expires = self.sessions.create(user_id)
        return 200, {"ok": True,
                     "set_cookie": new_cookie(SESSION_COOKIE, token,
                                              max_age=int(expires -
                                                         time.time()))}

    def _delete_account(self, headers: dict[str, str]) -> tuple[int, dict]:
        user_id = self._session_user(headers)
        if not user_id:
            return 401, {"error": "not signed in"}
        self.sessions.drop_user(user_id)
        self.users.delete(user_id)
        space = self._space(user_id)
        space.close()
        try:
            shutil.rmtree(space.home, ignore_errors=True)
        except OSError:
            pass
        return 200, {"ok": True,
                     "set_cookie": new_cookie(SESSION_COOKIE, "", max_age=0)}

    # -- conversations ------------------------------------------------------
    def _conversations(self, headers: dict[str, str]) -> tuple[int, dict]:
        user_id = self._session_user(headers)
        if not user_id:
            return 401, {"error": "not signed in"}
        items = self._space(user_id).conversations()
        return 200, {"conversations": items[:MAX_LISTED_CONVERSATIONS]}

    def _new_conversation(self, body: bytes,
                          headers: dict[str, str]) -> tuple[int, dict]:
        user_id = self._session_user(headers)
        if not user_id:
            return 401, {"error": "not signed in"}
        data = self._json_body(body)
        item = self._space(user_id).new_conversation(
            str(data.get("title") or ""))
        return 200, {"conversation": item}

    def _delete_conversation(self, conversation_id: str,
                             headers: dict[str, str]) -> tuple[int, dict]:
        user_id = self._session_user(headers)
        if not user_id:
            return 401, {"error": "not signed in"}
        ok = self._space(user_id).delete_conversation(conversation_id)
        return (200 if ok else 404), {"ok": ok}

    def _conversation_messages(self, conversation_id: str,
                               headers: dict[str, str]) -> tuple[int, dict]:
        user_id = self._session_user(headers)
        if not user_id:
            return 401, {"error": "not signed in"}
        space = self._space(user_id)
        item = space.conversation(conversation_id)
        if not item:
            return 404, {"error": "unknown conversation"}
        return 200, {"conversation": item,
                     "turns": space.history(conversation_id)}

    # -- chat ---------------------------------------------------------------
    def _current_conversation(self, space, title: str = "") -> dict:
        """The conversation to write into (the newest one, or a new)."""
        items = space.conversations()
        if items:
            return items[0]
        return space.new_conversation(title)

    def _chat(self, body: bytes, headers: dict[str, str]) -> tuple[int, dict]:
        user_id = self._session_user(headers)
        if not user_id:
            return 401, {"error": "not signed in"}
        data = self._json_body(body)
        message = str(data.get("message") or "").strip()
        if not message:
            return 400, {"error": "say something"}
        if len(message) > MAX_MESSAGE_CHARS:
            return 400, {"error": "that message is too long"}
        if not self._rate_ok(user_id):
            return 429, {"error": "too many messages, slow down a moment"}
        space = self._space(user_id)
        conversation = self._current_conversation(space)
        conversation_id = str(conversation.get("id"))
        space.record(conversation_id, "user", message)
        title = str(conversation.get("title") or "") or message[:48]
        try:
            jarvis = space.jarvis()
            result = jarvis.cycle_once(message, source="user")
            reply = str(result.response or "").strip() or \
                "I did not have an answer for that."
            tools = [str(t)[:80] for t in (result.tools_used or [])][:5]
        except Exception as exc:
            # A failure must not take the page down.
            reply = ("Something went wrong on my side "
                     f"({type(exc).__name__}).")
            tools = []
        space.record(conversation_id, "jarvis", reply, title=title)
        return 200, {"reply": reply, "speak": self.speak,
                     "conversation_id": conversation_id,
                     "tools": tools,
                     "approvals": self._pending_approvals(space)}

    # -- approvals ---------------------------------------------------------
    def _pending_approvals(self, space) -> list[dict[str, Any]]:
        """What JARVIS wants a human to say yes to."""
        try:
            policy = getattr(space.jarvis(), "policy", None)
            records = getattr(policy, "approvals", None)
        except Exception:
            return []
        out: list[dict[str, Any]] = []
        if not isinstance(records, dict):
            return out
        for token, record in records.items():
            if not isinstance(record, dict):
                continue
            if record.get("status") != "pending":
                continue
            out.append({"token": str(token)[:128],
                        "action": str(record.get("action", ""))[:200],
                        "risk": str(record.get("risk", "?"))[:20]})
            if len(out) >= 5:
                break
        return out

    def _approvals_pending(self, headers: dict[str, str]) -> tuple[int, dict]:
        user_id = self._session_user(headers)
        if not user_id:
            return 401, {"error": "not signed in"}
        return 200, {"approvals": self._pending_approvals(
            self._space(user_id))}

    def _approval_decision(self, body: bytes,
                           headers: dict[str, str]) -> tuple[int, dict]:
        user_id = self._session_user(headers)
        if not user_id:
            return 401, {"error": "not signed in"}
        data = self._json_body(body)
        token = str(data.get("token") or "")[:128]
        decision = str(data.get("decision") or "").lower()
        if decision not in ("approve", "deny"):
            return 400, {"error": "decision must be approve or deny"}
        space = self._space(user_id)
        try:
            policy = getattr(space.jarvis(), "policy", None)
            if decision == "approve":
                ok = bool(policy.approve(token, by=f"platform:{user_id}"))
            else:
                ok = bool(policy.deny(token, by=f"platform:{user_id}",
                                      reason="the person said no"))
        except Exception:
            return 500, {"error": "the decision could not be recorded"}
        if not ok:
            return 404, {"error": "that approval is no longer waiting"}
        return 200, {"ok": True, "decision": decision}

    # -- voice -------------------------------------------------------------
    def _speak(self, body: bytes, headers: dict[str, str]) -> tuple[int, Any]:
        """The spoken answer, in the British voice."""
        user_id = self._session_user(headers)
        if not user_id:
            return 401, {"error": "not signed in"}
        data = self._json_body(body)
        text = str(data.get("text") or "").strip()[:MAX_MESSAGE_CHARS]
        if not text:
            return 400, {"error": "nothing to say"}
        from ..voice.tts import provider_for, TTSRequest
        provider = provider_for("auto", {})
        if not provider.available():
            return 503, {"error": "no voice engine installed"}
        result = provider.synthesize(TTSRequest(text=text), None)
        if not result.ok or not result.audio_path:
            return 503, {"error": "the voice engine failed"}
        try:
            audio = Path(result.audio_path).read_bytes()
        except OSError:
            return 503, {"error": "the voice engine failed"}
        return 200, {"__audio__": audio, "ctype": "audio/wav"}

    def close(self) -> None:
        self.spaces.close_all()


__all__ = ["Platform", "SESSION_COOKIE", "MESSAGES_PER_MINUTE",
           "MAX_MESSAGE_CHARS"]
