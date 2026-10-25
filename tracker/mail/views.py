"""Owner routes for the recipient list, the email template, the preview, the test send and the manual send."""

from __future__ import annotations

from datetime import datetime, timezone

from flask import current_app, flash, g, redirect, render_template, request, url_for
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from ..audit import record
from ..auth import current_user, require_tracker_role
from ..db import get_session
from ..engine.weeks import week_endings
from ..models import EmailTemplate, Recipient, ReportSend
from ..report import views as report_views
from ..report.build import build_report, default_report_week
from ..trackers.views import _refuse_if_archived
from . import bp, sending, smtp
from .compose import (
    DEFAULT_BODY,
    DEFAULT_SUBJECT,
    PLACEHOLDERS,
    normalise_recipient,
    preview_chart_src,
    render_email_html,
    unknown_placeholders,
)
from .compose import report_link as make_link

MAX_SUBJECT = 300
MAX_BODY = 50_000


def _week(tracker):
    return report_views._requested_week(tracker) or default_report_week(tracker, report_views.today())


def _audit(tracker, action: str, entity_id, detail: dict) -> None:
    record(
        get_session(), user_id=current_user().id, tracker_id=tracker.id, action=action, entity="email_settings",
        entity_id=entity_id, detail=detail,
    )  # fmt: skip


def _page(tracker, week, preview=None, form=None, status: int = 200):
    db = get_session()
    template = db.get(EmailTemplate, tracker.id)
    values = form or {
        "subject": template.subject if template else DEFAULT_SUBJECT,
        "body_html": template.body_html if template else DEFAULT_BODY,
    }
    recent = db.scalars(
        select(ReportSend).where(ReportSend.tracker_id == tracker.id).order_by(ReportSend.id.desc()).limit(10)
    ).all()
    return (
        render_template(
            "mail/settings.html",
            tracker=tracker,
            recipients=db.scalars(select(Recipient).where(Recipient.tracker_id == tracker.id).order_by(Recipient.id)),
            values=values,
            placeholders=PLACEHOLDERS,
            unknown=unknown_placeholders(values["subject"], values["body_html"]),
            custom=template is not None,
            weeks=week_endings(tracker.first_week_ending, tracker.last_week_ending),
            week=week,
            preview=preview,
            recent=recent,
            page_title=f"{tracker.name} email",
            current_page="trackers",
        ),
        status,
    )


@bp.route("/trackers/<int:tracker_id>/mail", methods=["GET", "POST"])
@require_tracker_role("owner")
def settings(tracker_id: int):
    tracker, db = g.tracker, get_session()
    if request.method == "GET":
        return _page(tracker, _week(tracker))
    refused = _refuse_if_archived(tracker, "mail.settings")
    if refused:
        return refused
    action = request.form.get("action", "")
    back = redirect(url_for("mail.settings", tracker_id=tracker.id))
    if action == "add_recipient":
        email, error = normalise_recipient(request.form.get("email", ""))
        if error:
            flash(error, "danger")
            return back
        if db.scalar(select(Recipient.id).where(Recipient.tracker_id == tracker.id, Recipient.email == email)):
            flash(f"{email} is already a recipient.", "danger")
            return back
        db.add(Recipient(tracker_id=tracker.id, email=email, name=request.form.get("name", "").strip()[:200]))
        _audit(tracker, "recipient_added", email, {"email": email})
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            flash(f"{email} is already a recipient.", "danger")
            return back
        flash(f"Added {email}.", "success")
    elif action == "remove_recipient":
        recipient = db.get(Recipient, request.form.get("recipient_id", type=int) or 0)
        if recipient is None or recipient.tracker_id != tracker.id:
            flash("That recipient was not found.", "danger")
            return back
        db.delete(recipient)
        _audit(tracker, "recipient_removed", recipient.email, {"email": recipient.email})
        db.commit()
        flash(f"Removed {recipient.email}.", "success")
    elif action == "reset_template":
        db.execute(delete(EmailTemplate).where(EmailTemplate.tracker_id == tracker.id))
        _audit(tracker, "email_template_reset", tracker.id, {})
        db.commit()
        flash("The email template has been reset to the default.", "success")
    elif action == "save_template":
        subject = " ".join(request.form.get("subject", "").split())
        body = request.form.get("body_html", "").strip()
        errors = []
        if not subject or len(subject) > MAX_SUBJECT:
            errors.append(f"The subject is required and must be at most {MAX_SUBJECT} characters.")
        if not body or len(body) > MAX_BODY:
            errors.append(f"The body is required and must be at most {MAX_BODY} characters.")
        if errors:
            for message in errors:
                flash(message, "danger")
            return _page(tracker, _week(tracker), form={"subject": subject, "body_html": body}, status=400)
        db.merge(EmailTemplate(tracker_id=tracker.id, subject=subject, body_html=body))
        _audit(
            tracker, "email_template_saved", tracker.id, {"unknown_placeholders": unknown_placeholders(subject, body)}
        )
        db.commit()
        flash("Email template saved.", "success")
    else:
        flash("Unknown action.", "danger")
    return back


@bp.get("/trackers/<int:tracker_id>/mail/preview")
@require_tracker_role("owner")
def preview(tracker_id: int):
    tracker, db = g.tracker, get_session()
    week = _week(tracker)
    report = build_report(db, tracker, week, report_views.today())
    link = make_link(current_app.config["APP_URL"], tracker.id, week)
    subject, page = render_email_html(report, db.get(EmailTemplate, tracker.id), link, preview_chart_src(report))
    return _page(tracker, week, preview={"subject": subject, "html": page})


@bp.post("/trackers/<int:tracker_id>/mail/test")
@require_tracker_role("owner")
def test_send(tracker_id: int):
    tracker = g.tracker
    refused = _refuse_if_archived(tracker, "mail.settings")
    if refused:
        return refused
    week = _week(tracker)
    user = current_user()
    try:
        sending.send_test(get_session(), tracker, week, user, datetime.now(timezone.utc))
    except smtp.MailError as exc:
        flash(f"The test email could not be sent: {exc}", "danger")
    else:
        flash(f"A test email was sent to {user.email}.", "success")
    return redirect(url_for("mail.settings", tracker_id=tracker.id, week=week.isoformat()))


@bp.post("/trackers/<int:tracker_id>/mail/send")
@require_tracker_role("owner")
def send_now(tracker_id: int):
    tracker = g.tracker
    refused = _refuse_if_archived(tracker, "mail.settings")
    if refused:
        return refused
    week = _week(tracker)
    try:
        send = sending.send_report(
            get_session(), tracker, week, "manual", current_user().id, datetime.now(timezone.utc)
        )
    except ValueError as exc:
        flash(str(exc), "danger")
    else:
        if send.status == "sent":
            flash(f"The report for the week ending {week.isoformat()} was sent.", "success")
        elif send.status == "queued":
            flash("The report could not be sent now. It is queued and will be retried.", "danger")
        else:
            flash("The report could not be sent.", "danger")
    return redirect(url_for("mail.settings", tracker_id=tracker.id, week=week.isoformat()))
