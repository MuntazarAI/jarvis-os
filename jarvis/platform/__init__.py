"""The public JARVIS platform.

People sign up, sign in and talk to their own JARVIS: the same brain
and the same voice, with their own memory, their own files and their
own tasks.

    Platform   the routes: sign up, log in, chat, speak
    accounts   passwords (scrypt) and sessions (HttpOnly cookie)
    users      one home directory — one JARVIS — per person
    chat       the page people actually see

Everything is local to the server. No third-party service sees a
message, and one person's data never reaches another person's answers.
"""

from .accounts import (SessionStore, UserStore, hash_password,
                       new_cookie, parse_cookies, valid_email,
                       verify_password)
from .routes import Platform
from .users import UserRegistry, UserSpace

__all__ = ["Platform", "UserStore", "SessionStore", "UserRegistry",
           "UserSpace", "hash_password", "verify_password",
           "valid_email", "new_cookie", "parse_cookies"]
