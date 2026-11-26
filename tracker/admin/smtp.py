"""The email (SMTP) settings screen. Only non-secret settings are stored.

Administrators change every setting. Other ``manage_email_settings`` holders change only the sender address: the
server, port, authentication method, user, tenant and client stay administrator-only and are shown to them read-only,
because pointing the app at another server would send it the SMTP password or token.
"""

from __future__ import annotations

from flask import abort, flash, redirect, render_template, request, url_for
from sqlalchemy import select

from ..audit import record
from ..auth import current_user, permission_required
from ..db import get_session
from ..feedback import mail as feedback_mail
from ..feedback import settings as feedback_settings
from ..mail import access, domains
from ..mail.compose import (
    BLOCK_PLACEHOLDERS,
    PLACEHOLDERS,
    REPORT_SUBJECT_KEY,
    SAMPLE_CONTEXT,
    render_subject,
    report_subject,
    unknown_placeholders,
)
from ..models import AppSetting
from . import bp

# Non-secret keys only. SMTP_PASSWORD and SMTP_CLIENT_SECRET are environment variables and never stored here.
SMTP_KEYS = ("smtp_host", "smtp_port", "smtp_auth", "smtp_user", "smtp_from", "smtp_tenant_id", "smtp_client_id")
SENDER_KEYS = ("smtp_from",)  # the keys a holder who is not an administrator may change
SMTP_AUTH_MODES = ("none", "plain", "xoauth2")
SERVER_LOCKED_MESSAGE = "Only an administrator can change the mail server and how the app signs in to it."
DOMAINS_LOCKED_MESSAGE = "Only an administrator can change which domains report emails may go to."
MAX_REPORT_SUBJECT = 300
REPORT_SUBJECT_ERROR = f"The report email subject is required and must be at most {MAX_REPORT_SUBJECT} characters."


def _smtp_values(db) -> dict[str, str]:
    stored = {row.key: row.value for row in db.scalars(select(AppSetting).where(AppSetting.key.in_(SMTP_KEYS)))}
    values = {key: stored.get(key, "") for key in SMTP_KEYS}
    values["smtp_auth"] = values["smtp_auth"] or "none"
    return values


def _submitted(before: dict[str, str], is_admin: bool) -> dict[str, str]:
    """The settings to store. A holder who is not an administrator keeps every server setting as it is, and posting a
    different value for one is refused with 400 (the form offers no such field to them)."""
    if is_admin:
        return {key: request.form.get(key, "").strip() for key in SMTP_KEYS}
    for key in SMTP_KEYS:
        if key not in SENDER_KEYS and key in request.form and request.form[key].strip() != before[key]:
            abort(400, description=SERVER_LOCKED_MESSAGE)
    return before | {key: request.form.get(key, "").strip() for key in SENDER_KEYS}


@bp.route("/smtp", methods=["GET", "POST"])
@permission_required("manage_email_settings")
def smtp():
    db = get_session()
    is_admin = current_user().is_admin
    if request.method == "POST":
        before = _smtp_values(db)
        submitted = _submitted(before, is_admin)
        port = submitted["smtp_port"]
        if port and not (port.isascii() and port.isdigit() and len(port) <= 5 and 1 <= int(port) <= 65535):
            abort(400, description="The SMTP port must be a number between 1 and 65535.")
        if submitted["smtp_auth"] not in SMTP_AUTH_MODES:
            abort(400, description="The authentication mode must be none, plain or xoauth2.")
        subject_before = report_subject(db)
        subject = subject_before
        if REPORT_SUBJECT_KEY in request.form:  # left out of the form: kept as it is
            subject = " ".join(request.form[REPORT_SUBJECT_KEY].split())
            if not subject or len(subject) > MAX_REPORT_SUBJECT:
                abort(400, description=REPORT_SUBJECT_ERROR)
        # Access requests (design 2026-11-18): kept as they are when left out of the form.
        infosec_before, days_before = access.infosec_email(db), access.reminder_days(db)
        infosec, days = infosec_before, days_before
        if access.INFOSEC_KEY in request.form:
            infosec, error = access.parse_infosec_email(request.form[access.INFOSEC_KEY])
            if error:
                abort(400, description=error)
        if access.REMINDER_DAYS_KEY in request.form:
            days, error = access.parse_reminder_days(request.form[access.REMINDER_DAYS_KEY])
            if error:
                abort(400, description=error)
        # Feedback (design 2026-11-25): kept as it is unless the form carries the section (an unticked box sends none).
        feedback_before, link_before = feedback_settings.addresses(db), feedback_settings.link_on(db)
        feedback_to, link = feedback_before, link_before
        if "feedback_section" in request.form:
            feedback_to, error = feedback_settings.parse_addresses(request.form.get(feedback_settings.ADDRESS_KEY, ""))
            if error:
                abort(400, description=error)
            link = request.form.get(feedback_settings.LINK_KEY) == "1"
        for key, value in submitted.items():
            db.merge(AppSetting(key=key, value=value))
        if subject != subject_before:
            db.merge(AppSetting(key=REPORT_SUBJECT_KEY, value=subject))
        if infosec != infosec_before:
            db.merge(AppSetting(key=access.INFOSEC_KEY, value=infosec))
        if days != days_before:
            db.merge(AppSetting(key=access.REMINDER_DAYS_KEY, value=str(days)))
        # Allowed recipient domains (audit 2026-11-25, Medium 1): administrators only; kept as they are when left out.
        domains_before = domains.allowed_domains(db)
        allowed = domains_before
        if domains.KEY in request.form:
            allowed, error = domains.parse_domains(request.form[domains.KEY])
            if error:
                abort(400, description=error)
            if allowed != domains_before and not is_admin:
                abort(400, description=DOMAINS_LOCKED_MESSAGE)
        if allowed != domains_before:
            db.merge(AppSetting(key=domains.KEY, value="\n".join(allowed)))
            record(
                db,
                user_id=current_user().id,
                tracker_id=None,
                action="recipient_domains_changed",
                entity="app_settings",
                entity_id=domains.KEY,
                detail={
                    "added": [d for d in allowed if d not in domains_before],
                    "removed": [d for d in domains_before if d not in allowed],
                },
            )
        if feedback_to != feedback_before:
            db.merge(AppSetting(key=feedback_settings.ADDRESS_KEY, value=", ".join(feedback_to)))
        if link != link_before:
            db.merge(AppSetting(key=feedback_settings.LINK_KEY, value="1" if link else "0"))
        if (feedback_to, link) != (feedback_before, link_before):
            record(
                db,
                user_id=current_user().id,
                tracker_id=None,
                action="feedback_settings_changed",
                entity="app_settings",
                entity_id="feedback",
                detail={
                    "changed": [
                        key
                        for key, differs in (
                            (feedback_settings.ADDRESS_KEY, feedback_to != feedback_before),
                            (feedback_settings.LINK_KEY, link != link_before),
                        )
                        if differs
                    ]
                },
            )
        record(
            db,
            user_id=current_user().id,
            tracker_id=None,
            action="smtp_settings_updated",
            entity="app_settings",
            entity_id="smtp",
            detail={
                "changed": sorted(
                    [k for k in SMTP_KEYS if before[k] != submitted[k]]
                    + ([REPORT_SUBJECT_KEY] if subject != subject_before else [])
                    + ([access.INFOSEC_KEY] if infosec != infosec_before else [])
                    + ([access.REMINDER_DAYS_KEY] if days != days_before else [])
                )
            },
        )
        db.commit()
        flash("Email settings saved.", "success")
        return redirect(url_for("admin.smtp"))
    return render_template(
        "admin/smtp.html",
        values=_smtp_values(db),
        report_subject=report_subject(db),
        infosec=access.infosec_email(db),
        reminder_days=access.reminder_days(db),
        feedback_to=", ".join(feedback_settings.addresses(db)),
        feedback_link=feedback_settings.link_on(db),
        recipient_domains=domains.allowed_domains(db),
        domains_key=domains.KEY,
        max_reminder_days=access.MAX_REMINDER_DAYS,
        unknown=unknown_placeholders(report_subject(db)),
        placeholders={name: text for name, text in PLACEHOLDERS.items() if name not in BLOCK_PLACEHOLDERS},
        known=list(PLACEHOLDERS),
        blocks=BLOCK_PLACEHOLDERS,
        sample=SAMPLE_CONTEXT,
        sample_subject=render_subject(report_subject(db), SAMPLE_CONTEXT),
        max_subject=MAX_REPORT_SUBJECT,
        modes=SMTP_AUTH_MODES,
        server_locked=not is_admin,
        locked_message=SERVER_LOCKED_MESSAGE,
        page_title="Email settings",
        current_page="smtp",
    )


@bp.post("/smtp/feedback-test")
@permission_required("manage_email_settings")
def smtp_feedback_test():
    db = get_session()
    problem = feedback_mail.send_test(db, current_user())
    if problem:
        flash(problem, "danger")
    else:
        flash("A test feedback email was sent to the saved address.", "success")
    return redirect(url_for("admin.smtp") + "#section-feedback")
