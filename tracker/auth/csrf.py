"""CSRF protection, login throttling and redirect safety (ported from the EVERTON dashboard)."""

from __future__ import annotations

import secrets
import threading
import time
from collections import defaultdict, deque
from urllib.parse import urlsplit

from flask import Flask, abort, request, session

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class LoginThrottle:
    """Process-local rate limiter for the login form."""

    def __init__(self, attempts: int = 5, window_seconds: int = 300) -> None:
        self.attempts = attempts
        self.window_seconds = window_seconds
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _trim(self, key: str, now: float) -> deque[float]:
        failures = self._failures[key]
        while failures and failures[0] <= now - self.window_seconds:
            failures.popleft()
        return failures

    def blocked(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            blocked = len(self._trim(key, now)) >= self.attempts
            if not self._failures[key]:
                self._failures.pop(key, None)
            return blocked

    def fail(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            self._trim(key, now).append(now)

    def clear(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)


def csrf_token() -> str:
    return session.setdefault("csrf_token", secrets.token_urlsafe(32))


def valid_csrf(candidate: str | None) -> bool:
    expected = session.get("csrf_token", "")
    return bool(candidate and expected and secrets.compare_digest(candidate, expected))


def safe_next_url(value: str | None) -> str | None:
    """Accept only same-site absolute paths."""
    if not value or "\\" in value or any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        return None
    # Exactly one leading slash: "//host" and "///host" are read by browsers as protocol-relative URLs.
    if not value.startswith("/") or value.startswith("//"):
        return None
    parts = urlsplit(value)
    if parts.scheme or parts.netloc:
        return None
    return value


def install_csrf(app: Flask) -> None:
    """Reject any state-changing request that lacks a valid token with 400."""

    @app.before_request
    def check_csrf():
        if request.method in UNSAFE_METHODS:
            candidate = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
            if not valid_csrf(candidate):
                abort(400, description="The form has expired or is invalid. Please reload the page and try again.")

    app.jinja_env.globals["csrf_token"] = csrf_token
