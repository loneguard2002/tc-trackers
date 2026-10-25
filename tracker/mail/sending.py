"""Sending the report: stored sends, the retry backoff and the audit trail.

Delivery is the initial send plus 4 retries (5 attempts in total). Failed sends are queued and retried after 5, 15,
60 and 240 minutes. ``attempts`` counts failed attempts; the send becomes ``failed`` when the fifth has failed.
Passwords, tokens and message bodies are never audited.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from flask import current_app
from sqlalchemy import select

from ..audit import record
from ..models import EmailTemplate, Recipient, ReportSend, Tracker, User
from ..report import views as report_views
from ..report.build import Report, build_report
from ..report.render import html_to_pdf, render_print_html
from . import smtp
from .compose import build_report_email, report_link

logger = logging.getLogger(__name__)

BACKOFF_MINUTES = [5, 15, 60, 240]
MAX_ATTEMPTS = len(BACKOFF_MINUTES) + 1  # the initial send plus 4 retries
NO_RECIPIENTS_MESSAGE = "Add at least one recipient before sending."
ERROR_LENGTH = 300


def next_attempt_delay(attempts: int) -> timedelta | None:
    """The wait after ``attempts`` failed attempts, or ``None`` when the send should now be marked failed."""
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    if attempts >= MAX_ATTEMPTS:
        return None
    return timedelta(minutes=BACKOFF_MINUTES[attempts - 1])


def error_text(exc: Exception) -> str:
    """The class of the underlying error and a short message; MailError messages never hold credentials."""
    return f"{type(exc.__cause__ or exc).__name__}: {str(exc)[:ERROR_LENGTH]}"


def recipient_emails(session, tracker: Tracker) -> list[str]:
    return list(
        session.scalars(select(Recipient.email).where(Recipient.tracker_id == tracker.id).order_by(Recipient.id))
    )


def _link(tracker: Tracker, week_ending: date) -> str:
    return report_link(current_app.config["APP_URL"], tracker.id, week_ending)


def _audit(session, send: ReportSend, tracker: Tracker, user_id: int | None) -> None:
    action = {"sent": "report_sent", "queued": "report_send_queued", "failed": "report_send_failed"}[send.status]
    detail = {
        "recipient_count": len(send.recipients),
        "recipients": list(send.recipients),
        "trigger": send.trigger,
        "status": send.status,
        "week_ending": send.week_ending.isoformat(),
        "attempts": send.attempts,
    }
    if send.error:
        detail["error"] = send.error
    record(
        session, user_id=user_id, tracker_id=tracker.id, action=action, entity="report_send", entity_id=send.id,
        detail=detail,
    )  # fmt: skip


def _record_failure(send: ReportSend, exc: Exception, now: datetime) -> None:
    """Count one failed attempt: store the error and either schedule the next retry or give up."""
    send.attempts += 1
    send.error = error_text(exc)
    delay = next_attempt_delay(send.attempts)
    send.status = "failed" if delay is None else "queued"
    send.next_attempt_at = None if delay is None else now + delay


def _attempt(session, send: ReportSend, tracker: Tracker, report: Report, now: datetime, user_id: int | None) -> None:
    """One delivery attempt for ``send``; updates its status and audits the outcome. The caller commits."""
    template = session.get(EmailTemplate, tracker.id)
    msg = build_report_email(report, template, list(send.recipients), _link(tracker, send.week_ending), send.pdf or b"")
    try:
        smtp.send_message(msg)
    except smtp.MailError as exc:
        _record_failure(send, exc, now)
    else:
        send.status = "sent"
        send.sent_at = now
        send.error = None
        send.next_attempt_at = None
    _audit(session, send, tracker, user_id)


def report_today(trigger: str, send_timezone: str, now: datetime) -> date:
    """The report's "today". A scheduled send uses the date in the tracker's send timezone at ``now`` (the worker runs
    in UTC); other sends keep the application's usual ``today()``."""
    if trigger == "scheduled":
        return now.astimezone(ZoneInfo(send_timezone)).date()
    return report_views.today()


def _report_and_pdf(session, tracker: Tracker, week_ending: date, today: date | None = None) -> tuple[Report, bytes]:
    report = build_report(session, tracker, week_ending, today or report_views.today())
    return report, html_to_pdf(render_print_html(report))


def send_report(
    session,
    tracker: Tracker,
    week_ending: date,
    trigger: str,
    user_id: int | None,
    now: datetime,
    *,
    claimed: ReportSend | None = None,
) -> ReportSend:
    """Build and send the report for ``week_ending``; stores a ``ReportSend`` with the PDF and commits.

    With ``claimed`` (a scheduled send already inserted as ``sending``) that row is filled in rather than a new one.
    """
    recipients = recipient_emails(session, tracker)
    if not recipients:
        raise ValueError(NO_RECIPIENTS_MESSAGE)
    report, pdf = _report_and_pdf(session, tracker, week_ending, report_today(trigger, tracker.send_timezone, now))
    if claimed is None:
        send = ReportSend(
            tracker_id=tracker.id,
            week_ending=report.week_ending,
            trigger=trigger,
            status="sending",
            recipients=recipients,
            pdf=pdf,
            attempts=0,
            created_by=user_id,
        )
        session.add(send)
    else:
        send = claimed
        send.recipients = recipients
        send.pdf = pdf
    session.flush()
    _attempt(session, send, tracker, report, now, user_id)
    session.commit()
    return send


def _claim_due(session, now: datetime, skip: set[int]) -> ReportSend | None:
    """Lock and return the next due queued send (``FOR UPDATE SKIP LOCKED``), re-checked against the database."""
    query = (
        select(ReportSend)
        .where(ReportSend.status == "queued", ReportSend.next_attempt_at <= now)
        .order_by(ReportSend.next_attempt_at, ReportSend.id)
        .limit(1)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )
    if skip:
        query = query.where(ReportSend.id.not_in(skip))
    return session.scalars(query).first()


def _retry_one(session, send: ReportSend, now: datetime) -> None:
    """Attempt ``send`` and commit. Any failure counts as a failed attempt, so one bad row cannot block the queue."""
    send_id = send.id
    try:
        tracker = session.get(Tracker, send.tracker_id)
        today = report_today(send.trigger, tracker.send_timezone, now)
        report = build_report(session, tracker, send.week_ending, today)
        _attempt(session, send, tracker, report, now, send.created_by)
    except Exception as exc:
        logger.exception("Report send %s could not be retried", send_id)
        session.rollback()  # discards any half-made changes and releases the lock; take it again before recording
        send = session.scalars(
            select(ReportSend)
            .where(ReportSend.id == send_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one()
        if send.status != "queued":
            session.rollback()
            return
        _record_failure(send, exc, now)
        _audit(session, send, session.get(Tracker, send.tracker_id), send.created_by)
    session.commit()


def retry_queued(session, now: datetime) -> int:
    """Resend queued sends that are due, re-using the stored PDF. Returns the number of sends attempted.

    One row at a time: claim it (``FOR UPDATE SKIP LOCKED``), send, commit, repeat, so a second worker never sends a
    row this one holds and the lock is held for exactly the send it protects. Each row is tried at most once per call.
    """
    done: set[int] = set()
    while (send := _claim_due(session, now, done)) is not None:
        done.add(send.id)
        _retry_one(session, send, now)
    return len(done)


def send_test(session, tracker: Tracker, week_ending: date, user: User, now: datetime) -> None:
    """Send the report to ``user`` only. Not stored as a report send; raises ``MailError`` on failure."""
    report, pdf = _report_and_pdf(session, tracker, week_ending)
    template = session.get(EmailTemplate, tracker.id)
    msg = build_report_email(report, template, [user.email], _link(tracker, report.week_ending), pdf)
    try:
        smtp.send_message(msg)
    except smtp.MailError as exc:
        status, error = "failed", error_text(exc)
    else:
        status, error = "sent", None
    detail = {
        "recipient_count": 1,
        "recipients": [user.email],
        "trigger": "manual",
        "status": status,
        "week_ending": report.week_ending.isoformat(),
        "test": True,
    }
    if error:
        detail["error"] = error
    record(
        session, user_id=user.id, tracker_id=tracker.id, action="report_test_sent", entity="report_send",
        entity_id=None, detail=detail,
    )  # fmt: skip
    session.commit()
    if error:
        raise smtp.MailError(error)
