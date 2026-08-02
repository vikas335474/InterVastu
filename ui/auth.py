"""Password hashing + session-token helpers for the Vastu audit UI.

Design: server-side sessions (an opaque random token, stored in
``storage.sessions`` and set as an httponly cookie), not a stateless/signed
token like a JWT. At this project's scale (a handful of known users, one
SQLite file) a session lookup per request is cheap, and it buys a real
property a stateless token doesn't give for free: logging out immediately
revokes access, rather than a token staying valid until it expires.

Password hashing uses bcrypt directly (not a home-grown scheme, not a
faster-but-weaker general-purpose hash) -- bcrypt is a well-vetted,
purpose-built password hash with a built-in work factor, which is the
standard, boring, correct choice here.

This module never logs, prints, or stores a plaintext password anywhere;
``storage.create_user`` only ever receives the bcrypt hash produced here.
"""

from __future__ import annotations

import re
import secrets

import bcrypt

#: Minimum password length. A simple length floor, not a full password-
#: strength policy (no forced mix of character classes) -- length is the
#: single strongest, least user-hostile lever for this scale of product.
MIN_PASSWORD_LENGTH = 8

#: Usernames are restricted to a small, predictable character set so they
#: are safe to render directly in the UI and never collide with anything
#: URL/HTML-special.
USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9_.-]{3,32}$")

#: Session cookie name, shared between server.py's set/read/clear calls.
SESSION_COOKIE_NAME = "vastu_session"


def validate_username(username: str) -> str | None:
    """Return an error message if ``username`` is invalid, else None."""
    if not USERNAME_PATTERN.match(username or ""):
        return (
            "Username must be 3-32 characters: letters, numbers, underscore, "
            "dot, or hyphen only."
        )
    return None


def validate_password(password: str) -> str | None:
    """Return an error message if ``password`` is too weak, else None."""
    if not password or len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    return None


def hash_password(password: str) -> str:
    """Bcrypt-hash a plaintext password for storage."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Check a plaintext password against a stored bcrypt hash.

    Returns False (never raises) for a malformed/corrupt stored hash --
    that is a "wrong password" outcome from the caller's point of view, not
    a server error.
    """
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def generate_session_token() -> str:
    """A cryptographically random, URL-safe session token."""
    return secrets.token_urlsafe(32)
