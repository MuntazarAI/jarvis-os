"""The public platform: accounts, sessions, per-user JARVIS, chat.

Deterministic: no network, no models, no mic. The JARVIS instance is
faked at the loop boundary, so these tests assert the platform's own
rules — who may talk, what they may see, and what is stored — and not
the quality of an answer.

The rules that matter most:
- one person's data never reaches another person's answers;
- a password is never stored, returned or logged in plain text;
- a session is an HttpOnly cookie, and it is revocable;
- a visitor's text is bounded and rate limited.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from http.cookiejar import CookieJar

import pytest

from jarvis.platform.accounts import (SessionStore, UserStore, hash_password,
                                       new_cookie, parse_cookies,
                                       verify_password)
from jarvis.platform.chat import CHAT_HTML
from jarvis.platform.routes import Platform
from jarvis.platform.server import PlatformServer


class _FakeJarvis:
    """A JARVIS that answers without a model."""

    def __init__(self, reply: str = "I am JARVIS.") -> None:
        self.reply = reply
        self.seen: list[str] = []
        self.cycle = 0

    def cycle_once(self, text: str, source: str = "user", session_id: str = ""):
        self.seen.append(text)
        self.cycle += 1
        from jarvis.core.loop import CycleResult
        return CycleResult(cycle=self.cycle, input_text=text,
                           response=self.reply, intent="chat")

    def close(self) -> None:
        pass


@pytest.fixture()
def platform(tmp_path):
    plat = Platform(tmp_path / "platform", speak=False)
    yield plat
    plat.close()


def _client(base: str):
    jar = CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def _post(base: str, opener, path: str, data: dict):
    request = urllib.request.Request(
        base + path, data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with opener.open(request, timeout=30) as response:
            body = response.read()
            try:
                return response.status, json.loads(body.decode() or "{}")
            except ValueError:
                return response.status, body
    except urllib.error.HTTPError as exc:
        body = exc.read()
        try:
            return exc.code, json.loads(body.decode() or "{}")
        except ValueError:
            return exc.code, body


def _get(base: str, opener, path: str):
    try:
        with opener.open(base + path, timeout=30) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


# accounts ---------------------------------------------------------------------

def test_password_is_never_stored_in_plain_text(tmp_path):
    store = UserStore(tmp_path)
    store.create("muntazar@example.com", "a very long password")
    raw = (tmp_path / "users.json").read_text(encoding="utf-8")
    assert "a very long password" not in raw
    assert "hash" in raw and "salt" in raw


def test_password_hash_round_trip():
    salt, digest = hash_password("correct horse battery")
    assert verify_password("correct horse battery", salt, digest) is True
    assert verify_password("wrong horse battery", salt, digest) is False


def test_duplicate_email_is_refused(tmp_path):
    store = UserStore(tmp_path)
    store.create("muntazar@example.com", "a very long password")
    with pytest.raises(ValueError):
        store.create("muntazar@example.com", "another long password")


def test_short_password_is_refused(tmp_path):
    store = UserStore(tmp_path)
    with pytest.raises(ValueError):
        store.create("muntazar@example.com", "short")


def test_wrong_email_shape_is_refused(tmp_path):
    store = UserStore(tmp_path)
    with pytest.raises(ValueError):
        store.create("not-an-email", "a very long password")


def test_authenticate_rejects_a_wrong_password(tmp_path):
    store = UserStore(tmp_path)
    store.create("muntazar@example.com", "a very long password")
    assert store.authenticate("muntazar@example.com", "wrong password") is None
    assert store.authenticate("muntazar@example.com",
                              "a very long password") is not None


def test_session_can_be_revoked(tmp_path):
    sessions = SessionStore(tmp_path)
    token, _ = sessions.create("u-1")
    assert sessions.resolve(token) == "u-1"
    sessions.drop(token)
    assert sessions.resolve(token) is None


def test_expired_session_does_not_resolve(tmp_path):
    sessions = SessionStore(tmp_path)
    token, _ = sessions.create("u-1", ttl_s=-1)
    assert sessions.resolve(token) is None


def test_session_cookie_is_httponly():
    cookie = new_cookie("jarvis_session", "abc")
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie


def test_cookie_parsing():
    assert parse_cookies("a=1; b=2").get("b") == "2"
    assert parse_cookies("").get("a") is None


# routes -----------------------------------------------------------------------

def test_signup_creates_an_account_and_a_session(platform):
    code, payload = platform.handle(
        "POST", "/api/signup", json.dumps(
            {"email": "muntazar@example.com",
             "password": "a very long password"}).encode(), {})
    assert code == 200
    assert payload["email"] == "muntazar@example.com"
    assert "set_cookie" in payload
    assert "HttpOnly" in payload["set_cookie"]


def test_signup_refuses_a_duplicate(platform):
    body = json.dumps({"email": "muntazar@example.com",
                       "password": "a very long password"}).encode()
    platform.handle("POST", "/api/signup", body, {})
    code, payload = platform.handle("POST", "/api/signup", body, {})
    assert code == 400
    assert "already" in payload["error"]


def test_login_and_logout(platform):
    body = json.dumps({"email": "muntazar@example.com",
                       "password": "a very long password"}).encode()
    platform.handle("POST", "/api/signup", body, {})
    code, payload = platform.handle(
        "POST", "/api/login", json.dumps(
            {"email": "muntazar@example.com",
             "password": "a very long password"}).encode(), {})
    assert code == 200
    token = parse_cookies(payload["set_cookie"]).get("jarvis_session")
    assert token
    headers = {"cookie": f"jarvis_session={token}"}
    assert platform.handle("GET", "/api/me", b"", headers)[0] == 200
    assert platform.handle("POST", "/api/logout", b"", headers)[0] == 200
    assert platform.handle("GET", "/api/me", b"", headers)[0] == 401


def test_login_with_a_wrong_password_says_nothing_useful(platform):
    platform.handle("POST", "/api/signup", json.dumps(
        {"email": "muntazar@example.com",
         "password": "a very long password"}).encode(), {})
    code, payload = platform.handle(
        "POST", "/api/login", json.dumps(
            {"email": "muntazar@example.com",
             "password": "wrong password"}).encode(), {})
    assert code == 401
    assert "wrong" in payload["error"]
    # The same message for an address that does not exist.
    other = platform.handle(
        "POST", "/api/login", json.dumps(
            {"email": "nobody@example.com",
             "password": "wrong password"}).encode(), {})
    assert other[0] == 401
    assert other[1]["error"] == payload["error"]


def test_chat_needs_a_session(platform):
    code, payload = platform.handle(
        "POST", "/api/chat", json.dumps({"message": "hi"}).encode(), {})
    assert code == 401


def test_chat_answers_and_records_the_turn(platform, monkeypatch):
    platform.handle("POST", "/api/signup", json.dumps(
        {"email": "muntazar@example.com",
         "password": "a very long password"}).encode(), {})
    token = _session_token(platform, "muntazar@example.com")
    headers = {"cookie": f"jarvis_session={token}"}
    space = platform.spaces.space(platform.users.get_by_email("muntazar@example.com")
                                   ["id"])
    fake = _FakeJarvis("Hello, I am JARVIS.")
    monkeypatch.setattr(type(space), "jarvis", lambda self: fake)
    code, payload = platform.handle(
        "POST", "/api/chat", json.dumps({"message": "hello"}).encode(),
        headers)
    assert code == 200
    assert payload["reply"] == "Hello, I am JARVIS."
    assert fake.seen == ["hello"]
    turns = space.history(payload["conversation_id"])
    assert [t["role"] for t in turns] == ["user", "jarvis"]


def test_conversations_can_be_made_listed_and_deleted(platform):
    platform.handle("POST", "/api/signup", json.dumps(
        {"email": "muntazar@example.com",
         "password": "a very long password"}).encode(), {})
    token = _session_token(platform, "muntazar@example.com")
    headers = {"cookie": f"jarvis_session={token}"}
    code, payload = platform.handle("POST", "/api/conversations",
                                     b"{}", headers)
    assert code == 200
    conversation_id = payload["conversation"]["id"]
    listed = platform.handle("GET", "/api/conversations", b"", headers)[1]
    assert conversation_id in [c["id"] for c in listed["conversations"]]
    assert platform.handle("DELETE", f"/api/conversations/{conversation_id}",
                           b"", headers)[0] == 200
    listed = platform.handle("GET", "/api/conversations", b"", headers)[1]
    assert conversation_id not in [c["id"] for c in listed["conversations"]]


def test_a_conversation_is_titled_by_its_first_message(platform, monkeypatch):
    platform.handle("POST", "/api/signup", json.dumps(
        {"email": "muntazar@example.com",
         "password": "a very long password"}).encode(), {})
    token = _session_token(platform, "muntazar@example.com")
    headers = {"cookie": f"jarvis_session={token}"}
    space = platform.spaces.space(platform.users.get_by_email("muntazar@example.com")
                                   ["id"])
    monkeypatch.setattr(type(space), "jarvis",
                        lambda self: _FakeJarvis("Hello."))
    platform.handle("POST", "/api/chat",
                    json.dumps({"message": "Plan my day"}).encode(), headers)
    listed = platform.handle("GET", "/api/conversations", b"", headers)[1]
    titles = [c["title"] for c in listed["conversations"]]
    assert "Plan my day" in titles


def test_the_password_can_be_changed_and_the_account_deleted(platform):
    platform.handle("POST", "/api/signup", json.dumps(
        {"email": "muntazar@example.com",
         "password": "a very long password"}).encode(), {})
    token = _session_token(platform, "muntazar@example.com")
    headers = {"cookie": f"jarvis_session={token}"}
    # The wrong current password changes nothing.
    code, payload = platform.handle("POST", "/api/account/password", json.dumps(
        {"current": "wrong password", "new": "an even longer password"}
    ).encode(), headers)
    assert code == 400
    # The right one works. Changing the password revokes every other
    # session and hands back a fresh one, so the person stays signed in.
    code, payload = platform.handle("POST", "/api/account/password", json.dumps(
        {"current": "a very long password",
         "new": "an even longer password"}).encode(), headers)
    assert code == 200
    fresh = parse_cookies(payload["set_cookie"]).get("jarvis_session")
    assert fresh
    headers = {"cookie": f"jarvis_session={fresh}"}
    assert platform.handle("GET", "/api/me", b"", headers)[0] == 200
    # The old session is gone.
    old_headers = {"cookie": f"jarvis_session={token}"}
    assert platform.handle("GET", "/api/me", b"", old_headers)[0] == 401
    # Deleting the account ends every session.
    assert platform.handle("POST", "/api/account/delete", b"", headers)[0] == 200
    assert platform.handle("GET", "/api/me", b"", headers)[0] == 401


def test_each_person_gets_their_own_jarvis(platform, monkeypatch):
    platform.handle("POST", "/api/signup", json.dumps(
        {"email": "alice@example.com",
         "password": "a very long password"}).encode(), {})
    platform.handle("POST", "/api/signup", json.dumps(
        {"email": "bob@example.com",
         "password": "another long password"}).encode(), {})
    alice_id = platform.users.get_by_email("alice@example.com")["id"]
    bob_id = platform.users.get_by_email("bob@example.com")["id"]
    alice_space = platform.spaces.space(alice_id)
    bob_space = platform.spaces.space(bob_id)
    assert alice_space.home != bob_space.home
    alice_space.record(alice_space.new_conversation()["id"], "user",
                       "my secret is 4242")
    assert bob_space.history(bob_space.new_conversation()["id"]) == []


def test_rate_limit_holds(platform, monkeypatch):
    platform.handle("POST", "/api/signup", json.dumps(
        {"email": "muntazar@example.com",
         "password": "a very long password"}).encode(), {})
    token = _session_token(platform, "muntazar@example.com")
    headers = {"cookie": f"jarvis_session={token}"}
    space = platform.spaces.space(
        platform.users.get_by_email("muntazar@example.com")["id"])
    monkeypatch.setattr(type(space), "jarvis", lambda self: _FakeJarvis())
    codes = []
    for _ in range(25):
        codes.append(platform.handle(
            "POST", "/api/chat", json.dumps({"message": "hi"}).encode(),
            headers)[0])
    assert 429 in codes
    assert codes.count(200) >= 10


def test_an_over_long_message_is_refused(platform):
    platform.handle("POST", "/api/signup", json.dumps(
        {"email": "muntazar@example.com",
         "password": "a very long password"}).encode(), {})
    token = _session_token(platform, "muntazar@example.com")
    headers = {"cookie": f"jarvis_session={token}"}
    code, payload = platform.handle(
        "POST", "/api/chat", json.dumps({"message": "x" * 9000}).encode(),
        headers)
    assert code == 400


def test_the_page_never_reaches_out_to_the_internet():
    lowered = CHAT_HTML.lower()
    assert "src=\"http" not in lowered
    assert "href=\"http" not in lowered
    assert "@import" not in lowered


def _session_token(platform: Platform, email: str) -> str:
    """Sign in and return the session id."""
    user = platform.users.authenticate(email, "a very long password") or \
        platform.users.authenticate(email, "another long password")
    token, _ = platform.sessions.create(user["id"])
    return token


# the server -------------------------------------------------------------------

def test_the_server_signs_a_person_in_and_answers(tmp_path):
    server = PlatformServer(tmp_path / "platform", port=0, speak=False)
    server.serve_forever()
    base = f"http://127.0.0.1:{server.port}"
    opener = _client(base)
    try:
        status, _ = _get(base, opener, "/")
        assert status == 200
        code, payload = _post(base, opener, "/api/signup",
                               {"email": "muntazar@example.com",
                                "password": "a very long password"})
        assert code == 200
        status, body = _get(base, opener, "/api/me")
        assert status == 200
        assert json.loads(body.decode())["email"] == "muntazar@example.com"
    finally:
        server.shutdown()


def test_the_server_refuses_a_chat_without_a_session(tmp_path):
    server = PlatformServer(tmp_path / "platform", port=0, speak=False)
    server.serve_forever()
    base = f"http://127.0.0.1:{server.port}"
    opener = _client(base)
    try:
        code, _ = _post(base, opener, "/api/chat", {"message": "hi"})
        assert code == 401
    finally:
        server.shutdown()
