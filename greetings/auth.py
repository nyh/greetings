"""Who may do what.

Guests need no account. A guest's cookie holds a random token that identifies
their one greeting; the database keeps only its hash.

The family signs in with Google, and the email address Google confirms must be
in ``admins`` in the config. With ``require_login=False`` (the local
development server on loopback) everyone is the family.
"""

# Copyright (C) 2026 Nadav Har'El
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import hashlib
import os
import secrets
import threading
import time
from collections import deque
from pathlib import Path

from flask import request, session

GUEST_COOKIE = "greeting"
SESSION_ADMIN = "admin"
CSRF_KEY = "csrf"


# ------------------------------------------------------------------ secret key

def secret_key(path: Path) -> bytes:
    """Read the key that signs session cookies, creating it on first use."""
    try:
        return path.read_bytes()
    except FileNotFoundError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(32)
    # O_EXCL: if two workers start together, one creates and both read it.
    try:
        with open(path, "xb", opener=lambda p, f: os.open(p, f, 0o600)) as f:
            f.write(key)
    except FileExistsError:
        pass
    return path.read_bytes()


# ------------------------------------------------------------------ guests

def new_guest_token() -> str:
    return secrets.token_urlsafe(32)


def owner_of(token: str | None) -> str | None:
    """The hash stored in the database for a guest's cookie token."""
    if not token:
        return None
    return hashlib.sha256(token.encode()).hexdigest()


def guest_owner() -> str | None:
    return owner_of(request.cookies.get(GUEST_COOKIE))


# ------------------------------------------------------------------ CSRF

def csrf_token() -> str:
    tok = session.get(CSRF_KEY)
    if not tok:
        tok = session[CSRF_KEY] = secrets.token_urlsafe(32)
    return tok


def check_csrf() -> bool:
    sent = request.form.get("csrf", "")
    expected = session.get(CSRF_KEY, "")
    return bool(expected) and secrets.compare_digest(sent, expected)


# ------------------------------------------------------------------ the family

def admin_email() -> str | None:
    return session.get(SESSION_ADMIN)


def is_admin(admins: tuple[str, ...]) -> bool:
    email = admin_email()
    return bool(email) and email.lower() in admins


def log_in(email: str) -> None:
    session.clear()
    session.permanent = True
    session[SESSION_ADMIN] = email.lower()


def log_out() -> None:
    session.clear()


def safe_next(raw: str | None) -> str:
    """Only a path on this site: never let ?next= send someone elsewhere."""
    if raw and raw.startswith("/") and not raw.startswith("//") and "\\" not in raw:
        return raw
    return "/admin"


# ------------------------------------------------------------------ flooding

class RateLimit:
    """At most ``limit`` events per key per ``window`` seconds, in memory.

    Per process, so with several gunicorn workers the real limit is a multiple
    of this. That is fine: it is a guard against a script, not a quota.
    """

    def __init__(self, limit: int, window: float = 60.0) -> None:
        self.limit = limit
        self.window = window
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        if self.limit <= 0:
            return True
        t = time.monotonic()
        with self._lock:
            q = self._events.setdefault(key, deque())
            while q and q[0] <= t - self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(t)
            if len(self._events) > 10000:       # forget idle addresses
                for k in [k for k, v in self._events.items() if not v]:
                    del self._events[k]
            return True
