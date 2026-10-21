"""Administration: user approval, administrator flag and the non-secret email settings."""

from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..audit import record
from ..auth import admin_required, current_user
from ..auth.passwords import hash_password, validate_new_password
from ..db import get_session
from ..models import AppSetting, User

bp = Blueprint("admin", __name__, url_prefix="/admin")

# Non-secret keys only. SMTP_PASSWORD and SMTP_CLIENT_SECRET are environment variables and never stored here.
SMTP_KEYS = ("smtp_host", "smtp_port", "smtp_auth", "smtp_user", "smtp_from", "smtp_tenant_id", "smtp_client_id")
SMTP_AUTH_MODES = ("none", "plain", "xoauth2")


def _get_user_or_404(user_id: int) -> User:
    user = get_session().get(User, user_id)
    if user is None:
        abort(404)
    return user


@bp.get("/users")
@admin_required
def users():
    db = get_session()
    rows = db.scalars(select(User).order_by(User.status != "pending", User.full_name, User.id)).all()
    return render_template("admin/users.html", users=rows, page_title="Users", current_page="admin")


@bp.post("/users")
@admin_required
def create_user():
    email = request.form.get("email", "").strip().lower()
    full_name = request.form.get("full_name", "").strip()
    password = request.form.get("password", "")
    error = None
    if not email or "@" not in email or not full_name:
        error = "An email address and a full name are required."
    else:
        error = validate_new_password(password)
    if error:
        flash(error, "danger")
        return redirect(url_for("admin.users"))
    db = get_session()
    user = User(
        email=email, full_name=full_name, password_hash=hash_password(password), auth_source="local", status="active"
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        flash("A user with that email address already exists.", "danger")
        return redirect(url_for("admin.users"))
    record(
        db,
        user_id=current_user().id,
        tracker_id=None,
        action="user_created",
        entity="user",
        entity_id=user.id,
        detail={"email": email, "source": "local"},
    )
    db.commit()
    flash(f"Created {email}.", "success")
    return redirect(url_for("admin.users"))


@bp.post("/users/<int:user_id>/approve")
@admin_required
def approve(user_id: int):
    user = _get_user_or_404(user_id)
    db = get_session()
    previous = user.status
    user.status = "active"
    record(
        db,
        user_id=current_user().id,
        tracker_id=None,
        action="user_approved",
        entity="user",
        entity_id=user.id,
        detail={"from": previous},
    )
    db.commit()
    flash(f"{user.full_name} is now active.", "success")
    return redirect(url_for("admin.users"))


@bp.post("/users/<int:user_id>/disable")
@admin_required
def disable(user_id: int):
    user = _get_user_or_404(user_id)
    if user.id == current_user().id:
        flash("You cannot disable your own account.", "danger")
        return redirect(url_for("admin.users"))
    db = get_session()
    user.status = "disabled"
    record(db, user_id=current_user().id, tracker_id=None, action="user_disabled", entity="user", entity_id=user.id)
    db.commit()
    flash(f"{user.full_name} has been disabled.", "success")
    return redirect(url_for("admin.users"))


@bp.post("/users/<int:user_id>/admin")
@admin_required
def set_admin(user_id: int):
    user = _get_user_or_404(user_id)
    make_admin = request.form.get("is_admin") == "1"
    if user.id == current_user().id and not make_admin:
        flash("You cannot remove your own administrator access.", "danger")
        return redirect(url_for("admin.users"))
    db = get_session()
    user.is_admin = make_admin
    record(
        db,
        user_id=current_user().id,
        tracker_id=None,
        action="user_admin_changed",
        entity="user",
        entity_id=user.id,
        detail={"is_admin": make_admin},
    )
    db.commit()
    flash(f"Administrator access {'granted to' if make_admin else 'removed from'} {user.full_name}.", "success")
    return redirect(url_for("admin.users"))


def _smtp_values(db) -> dict[str, str]:
    stored = {row.key: row.value for row in db.scalars(select(AppSetting).where(AppSetting.key.in_(SMTP_KEYS)))}
    values = {key: stored.get(key, "") for key in SMTP_KEYS}
    values["smtp_auth"] = values["smtp_auth"] or "none"
    return values


@bp.route("/smtp", methods=["GET", "POST"])
@admin_required
def smtp():
    db = get_session()
    if request.method == "POST":
        submitted = {key: request.form.get(key, "").strip() for key in SMTP_KEYS}
        port = submitted["smtp_port"]
        if port and not (port.isdigit() and 1 <= int(port) <= 65535):
            abort(400, description="The SMTP port must be a number between 1 and 65535.")
        if submitted["smtp_auth"] not in SMTP_AUTH_MODES:
            abort(400, description="The authentication mode must be none, plain or xoauth2.")
        before = _smtp_values(db)
        for key, value in submitted.items():
            db.merge(AppSetting(key=key, value=value))
        record(
            db,
            user_id=current_user().id,
            tracker_id=None,
            action="smtp_settings_updated",
            entity="app_settings",
            entity_id="smtp",
            detail={"changed": sorted(k for k in SMTP_KEYS if before[k] != submitted[k])},
        )
        db.commit()
        flash("Email settings saved.", "success")
        return redirect(url_for("admin.smtp"))
    return render_template(
        "admin/smtp.html",
        values=_smtp_values(db),
        modes=SMTP_AUTH_MODES,
        page_title="Email settings",
        current_page="admin",
    )
