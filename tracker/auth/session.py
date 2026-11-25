"""Session handling: the session stores the user id, a fingerprint of the password (and the CSRF token)."""

from __future__ import annotations

import hashlib
import hmac
from functools import wraps

from flask import abort, current_app, g, has_request_context, redirect, request, session, url_for

from ..db import get_session
from ..models import User

SESSION_KEY = "auth"


def session_key(user: User, secret: str | bytes) -> str:
    """A keyed fingerprint of the user's password hash. A new password changes it, which ends every session started
    with the old password; a Microsoft account has no password, so its fingerprint does not change."""
    key = secret.encode() if isinstance(secret, str) else secret
    return hmac.new(key, (user.password_hash or "").encode(), hashlib.sha256).hexdigest()


def login_user(user: User) -> None:
    """Start a fresh session for the user (the old one is discarded to prevent fixation)."""
    session.clear()
    session["user_id"] = user.id
    session[SESSION_KEY] = session_key(user, current_app.secret_key)
    session.permanent = True
    g.pop("current_user", None)


def logout_user() -> None:
    session.clear()
    g.pop("current_user", None)


def current_user() -> User | None:
    """Load the signed-in user; users that are not active, and sessions started with an earlier password, count as
    logged out.

    Outside a request (the scheduler worker renders templates in an app context only) nobody is signed in.
    """
    if not has_request_context():
        return None
    if "current_user" in g:
        return g.current_user
    user = None
    user_id = session.get("user_id")
    if user_id is not None:
        candidate = get_session().get(User, user_id)
        if (
            candidate is not None
            and candidate.status == "active"
            and hmac.compare_digest(session.get(SESSION_KEY, ""), session_key(candidate, current_app.secret_key))
        ):
            user = candidate
    g.current_user = user
    return user


def _to_login():
    return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            return _to_login()
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if user is None:
            return _to_login()
        if not user.is_admin:
            abort(403, description="Administrator access is required.")
        return view(*args, **kwargs)

    return wrapped
