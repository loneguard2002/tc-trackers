"""Authentication blueprint: local sign-in, sign-out and the approval holding page."""

from __future__ import annotations

from flask import Blueprint, current_app, redirect, render_template, request, session, url_for
from sqlalchemy import select

from ..audit import record
from ..db import get_session
from ..models import User
from .csrf import LoginThrottle, csrf_token, safe_next_url, valid_csrf
from .passwords import verify_against_dummy, verify_password
from .permissions import PERMISSIONS, has_permission, permission_required, user_permissions
from .roles import ROLE_ORDER, ROLES, require_tracker_role, tracker_roles, user_role, visible_trackers
from .session import admin_required, current_user, login_required, login_user, logout_user

__all__ = [
    "PERMISSIONS",
    "ROLE_ORDER",
    "ROLES",
    "LoginThrottle",
    "admin_required",
    "bp",
    "csrf_token",
    "has_permission",
    "current_user",
    "login_required",
    "login_user",
    "logout_user",
    "permission_required",
    "require_tracker_role",
    "tracker_roles",
    "user_permissions",
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


def _record_failure(db, user: User | None, entered_email: str, reason: str) -> None:
    """Log a refused sign-in: the email as entered and the reason, never the password."""
    record(
        db,
        user_id=None,
        tracker_id=None,
        action="login_failed",
        entity="user",
        entity_id=None if user is None else user.id,
        detail={"email": entered_email, "reason": reason},
        target_user_id=None if user is None else user.id,
    )
    db.commit()


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user() is not None:
        return redirect(url_for("index"))
    if request.method == "GET":
        return _login_page()

    email = request.form.get("email", "").strip().lower()
    entered_email = email[:MAX_EMAIL_LENGTH]
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
        reason = "unknown_account" if user is None else "wrong_password"
        _record_failure(db, user, entered_email, reason)
        return _login_page("Invalid email or password.", 200)

    if user.status == "pending":
        _record_failure(db, user, entered_email, "not_active")
        return _login_page("Your account is awaiting approval by an administrator.", 200)
    if user.status != "active":
        account_throttle.fail(account_key)
        _record_failure(db, user, entered_email, "not_active")
        return _login_page("Invalid email or password.", 200)

    account_throttle.clear(account_key)
    login_user(user)
    record(
        db, user_id=user.id, tracker_id=None, action="login", entity="user", entity_id=user.id, target_user_id=user.id
    )
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
