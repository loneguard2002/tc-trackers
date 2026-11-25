"""Authentication blueprint: local sign-in, sign-out and the approval holding page."""

from __future__ import annotations

from datetime import timezone

from flask import Blueprint, current_app, redirect, render_template, request, url_for
from flask import session as browser_session  # ``session`` here is this package's own module, imported below

from ..audit import record
from ..db import get_session
from ..models import User
from . import throttle
from .accounts import find_by_email
from .csrf import csrf_token, safe_next_url, valid_csrf
from .passwords import verify_against_dummy, verify_password
from .permissions import PERMISSIONS, has_permission, permission_required, user_permissions
from .roles import ROLE_ORDER, ROLES, require_tracker_role, tracker_roles, user_role, visible_trackers
from .session import admin_required, current_user, login_required, login_user, logout_user

__all__ = [
    "PERMISSIONS",
    "ROLE_ORDER",
    "ROLES",
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


def _login_page(error: str | None = None, status: int = 200):
    return (
        render_template(
            "login.html",
            error=error,
            sso_enabled=current_app.config["SSO_ENABLED"],
            next_url=safe_next_url(request.values.get("next")),
            page_title="Sign in",
            bare_page=True,
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
    address = request.remote_addr or "unknown"
    db = get_session()
    limits = throttle.load_limits(db)  # changed by administrators on Admin › Sign-in protection
    if (entered_email and throttle.blocked(db, limits, "account", entered_email)) or throttle.blocked(
        db, limits, "address", address
    ):
        return _login_page("Too many failed attempts. Please wait a few minutes and try again.", 429)

    if len(email) > MAX_EMAIL_LENGTH or len(password) > MAX_PASSWORD_LENGTH:
        email, password = "", ""
    user = find_by_email(db, email) if email else None
    if user is None or not user.password_hash:
        verify_against_dummy(password)
        password_ok = False
    else:
        password_ok = verify_password(password, user.password_hash)

    if not password_ok:
        if entered_email:
            throttle.fail(db, "account", entered_email)
        throttle.fail(db, "address", address)
        reason = "unknown_account" if user is None else "wrong_password"
        _record_failure(db, user, entered_email, reason)
        return _login_page("Invalid email or password.", 200)

    if user.status == "pending":
        _record_failure(db, user, entered_email, "not_active")
        return _login_page("Your account is awaiting approval by an administrator.", 200)
    if user.status != "active":
        throttle.fail(db, "account", entered_email)
        _record_failure(db, user, entered_email, "not_active")
        return _login_page("Invalid email or password.", 200)

    throttle.clear(db, "account", entered_email)
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


def _access_page(session_key: str, status: str, template: str, title: str):
    """The page after a Microsoft sign-in that cannot go on: the request waits, or it was turned down. The callback
    names the person in the session once; anything else goes back to the sign-in page."""
    from ..mail import access  # here: the mail package imports views that need this blueprint's helpers

    db = get_session()
    user_id = browser_session.pop(session_key, None)
    person = db.get(User, user_id) if isinstance(user_id, int) else None
    if person is None or person.status != status:
        return redirect(url_for("auth.login"))
    return render_template(
        template,
        person=person,
        first_name=access.first_name(person),
        asked=person.created_at.astimezone(timezone.utc),
        emailed=access.mail_configured(db),
        infosec=access.infosec_email(db),
        page_title=title,
        bare_page=True,
    )


@bp.get("/auth/pending")
def pending():
    return _access_page("pending_user_id", "pending", "sso_pending.html", "Access requested")


@bp.get("/auth/declined")
def declined():
    return _access_page("declined_user_id", "declined", "sso_declined.html", "Access not approved")
