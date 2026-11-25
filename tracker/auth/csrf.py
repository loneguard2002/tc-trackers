"""CSRF protection, redirect safety and a NUL byte guard (ported from the EVERTON dashboard); the sign-in limiter is in
``throttle.py``."""

from __future__ import annotations

import secrets
from urllib.parse import urlsplit

from flask import Flask, abort, request, session

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
# Endpoints that take a POST without the app's token. Microsoft posts the sign-in result to the SSO callback
# (response_mode=form_post); there MSAL checks the posted state against the signed flow cookie instead (auth/sso.py).
CSRF_EXEMPT_ENDPOINTS = frozenset({"sso.sso_callback"})


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


NUL_MESSAGE = "The request contained a character that is not allowed (a NUL byte). Remove it and try again."


def _has_nul(values) -> bool:
    return any("\x00" in key or any("\x00" in value for value in values.getlist(key)) for key in values)


def install_csrf(app: Flask) -> None:
    """Reject any state-changing request that lacks a valid token with 400, and any request whose address or form
    fields hold a NUL byte (PostgreSQL text cannot store one, so it would otherwise fail as a 500). Uploaded files are
    not checked: their bytes are read by the importer, not stored as text."""

    @app.before_request
    def reject_nul_bytes():
        if "\x00" in request.path or _has_nul(request.args) or _has_nul(request.form):
            abort(400, description=NUL_MESSAGE)

    @app.before_request
    def check_csrf():
        if request.method in UNSAFE_METHODS and request.endpoint not in CSRF_EXEMPT_ENDPOINTS:
            candidate = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
            if not valid_csrf(candidate):
                abort(400, description="The form has expired or is invalid. Please reload the page and try again.")

    app.jinja_env.globals["csrf_token"] = csrf_token
