"""Authentication blueprint: local sign-in, sign-out and the approval holding page."""

from __future__ import annotations

from flask import Blueprint, current_app, redirect, render_template, request, session, url_for
from sqlalchemy import select

from ..audit import record
from ..db import get_session
from ..models import User
from .csrf import LoginThrottle, csrf_token, safe_next_url, valid_csrf
from .passwords import verify_against_dummy, verify_password
from .roles import ROLE_ORDER, require_tracker_role, user_role, visible_trackers
from .session import admin_required, current_user, login_required, login_user, logout_user

__all__ = [
    "ROLE_ORDER",
    "LoginThrottle",
    "admin_required",
    "bp",
    "csrf_token",
    "current_user",
    "login_required",
    "login_user",
    "logout_user",
    "require_tracker_role",
    "user_role",
    "valid_csrf",
    "visible_trackers",
]

bp = Blueprint("auth", __name__)

MAX_EMAIL_LENGTH = 254
MAX_PASSWORD_LENGTH = 512
_THROTTLE_KEY = "login_throttles"


def _throttles() -> tuple[LoginThrottle, LoginThrottle]:
    """Per-account (5 failures) and per-address (20 failures) limiters, kept on the application."""
    return current_app.extensions.setdefault(
        _THROTTLE_KEY, (LoginThrottle(attempts=5, window_seconds=300), LoginThrottle(attempts=20, window_seconds=300))
    )


def _login_page(error: str | None = None, status: int = 200):
    return (
        render_template(
            "login.html",
            error=error,
            sso_enabled=current_app.config["SSO_ENABLED"],
            next_url=safe_next_url(request.values.get("next")),
            page_title="Sign in",
        ),
        status,
    )


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user() is not None:
        return redirect(url_for("index"))
    if request.method == "GET":
        return _login_page()

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    account_throttle, address_throttle = _throttles()
    account_key = f"account:{email}"
    address_key = f"address:{request.remote_addr}"
    if account_throttle.blocked(account_key) or address_throttle.blocked(address_key):
        return _login_page("Too many failed attempts. Please wait a few minutes and try again.", 429)

    if len(email) > MAX_EMAIL_LENGTH or len(password) > MAX_PASSWORD_LENGTH:
        email, password = "", ""
    db = get_session()
    user = db.scalar(select(User).where(User.email == email)) if email else None
    if user is None or not user.password_hash:
        verify_against_dummy(password)
        password_ok = False
    else:
        password_ok = verify_password(password, user.password_hash)

    if not password_ok:
        account_throttle.fail(account_key)
        address_throttle.fail(address_key)
        return _login_page("Invalid email or password.", 200)

    if user.status == "pending":
        return _login_page("Your account is awaiting approval by an administrator.", 200)
    if user.status != "active":
        account_throttle.fail(account_key)
        return _login_page("Invalid email or password.", 200)

    account_throttle.clear(account_key)
    login_user(user)
    record(db, user_id=user.id, tracker_id=None, action="login", entity="user", entity_id=user.id)
    db.commit()
    return redirect(safe_next_url(request.args.get("next") or request.form.get("next")) or url_for("index"))


@bp.post("/logout")
def logout():
    logout_user()
    return redirect(url_for("auth.login"))


@bp.get("/auth/pending")
def pending():
    name = session.pop("pending_name", None)
    return render_template("sso_pending.html", name=name, page_title="Awaiting approval")
