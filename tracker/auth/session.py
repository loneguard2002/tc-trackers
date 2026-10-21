"""Session handling: the session stores only the user id (and the CSRF token)."""

from __future__ import annotations

from functools import wraps

from flask import abort, g, redirect, request, session, url_for

from ..db import get_session
from ..models import User


def login_user(user: User) -> None:
    """Start a fresh session for the user (the old one is discarded to prevent fixation)."""
    session.clear()
    session["user_id"] = user.id
    session.permanent = True
    g.pop("current_user", None)


def logout_user() -> None:
    session.clear()
    g.pop("current_user", None)


def current_user() -> User | None:
    """Load the signed-in user; users that are not active count as logged out."""
    if "current_user" in g:
        return g.current_user
    user = None
    user_id = session.get("user_id")
    if user_id is not None:
        candidate = get_session().get(User, user_id)
        if candidate is not None and candidate.status == "active":
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
