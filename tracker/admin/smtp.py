"""The email (SMTP) settings screen. Only non-secret settings are stored."""

from __future__ import annotations

from flask import abort, flash, redirect, render_template, request, url_for
from sqlalchemy import select

from ..audit import record
from ..auth import current_user, permission_required
from ..db import get_session
from ..models import AppSetting
from . import bp

# Non-secret keys only. SMTP_PASSWORD and SMTP_CLIENT_SECRET are environment variables and never stored here.
SMTP_KEYS = ("smtp_host", "smtp_port", "smtp_auth", "smtp_user", "smtp_from", "smtp_tenant_id", "smtp_client_id")
SMTP_AUTH_MODES = ("none", "plain", "xoauth2")


def _smtp_values(db) -> dict[str, str]:
    stored = {row.key: row.value for row in db.scalars(select(AppSetting).where(AppSetting.key.in_(SMTP_KEYS)))}
    values = {key: stored.get(key, "") for key in SMTP_KEYS}
    values["smtp_auth"] = values["smtp_auth"] or "none"
    return values


@bp.route("/smtp", methods=["GET", "POST"])
@permission_required("manage_email_settings")
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
        current_page="smtp",
    )
