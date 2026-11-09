"""The reminder to write the weekly update, sent 24 hours before a tracker's automatic send.

A reminder is due for an active tracker with automatic sending on when its next send falls within the next 24 hours
and the update (the report input's headline) for that week has not been written. It goes to the person in charge, or
to the people given Owner directly on the tracker while nobody qualified is in charge. A reminder is claimed by
inserting its ``ReportReminder`` row, so each tracker and week gets one at most; a failed delivery gives the claim back
and the next scheduler run tries again.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage

from flask import current_app, render_template
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from ..audit import record
from ..auth.roles import lead_in_charge
from ..mail import smtp
from ..mail.compose import html_to_text
from ..models import ReportInput, ReportReminder, ReportSend, Tracker, TrackerRole, User
from .runner import next_send

logger = logging.getLogger(__name__)

WINDOW = timedelta(hours=24)


def due_reminders(session, now_utc: datetime) -> list[tuple[int, date]]:
    """``(tracker_id, week_ending)`` for each reminder due now and not yet sent."""
    due = []
    trackers = session.scalars(
        select(Tracker).where(Tracker.status == "active", Tracker.schedule_enabled.is_(True)).order_by(Tracker.id)
    )
    for tracker in trackers:
        fire = next_send(tracker, now_utc)
        if fire is None or fire.astimezone(timezone.utc) - now_utc > WINDOW:
            continue
        week = fire.date()
        written = session.get(ReportInput, (tracker.id, week))
        if written is not None and (written.headline or "").strip():
            continue
        done = select(ReportReminder.tracker_id).where(
            ReportReminder.tracker_id == tracker.id, ReportReminder.week_ending == week
        )
        sent = select(ReportSend.id).where(
            ReportSend.tracker_id == tracker.id, ReportSend.week_ending == week, ReportSend.trigger == "scheduled"
        )
        if session.scalar(done) is None and session.scalar(sent) is None:
            due.append((tracker.id, week))
    return due


def reminder_recipients(session, tracker: Tracker) -> list[str]:
    """The person in charge, or else the active people given Owner directly on the tracker."""
    lead = lead_in_charge(session, tracker)
    if lead is not None:
        return [lead.email]
    owners = session.scalars(
        select(User.email)
        .join(TrackerRole, TrackerRole.user_id == User.id)
        .where(TrackerRole.tracker_id == tracker.id, TrackerRole.role == "owner", User.status == "active")
        .order_by(User.email)
    )
    return list(owners)


def build_reminder(tracker: Tracker, week: date, fire: datetime, recipients: list[str]) -> EmailMessage:
    link = f"{current_app.config['APP_URL'].rstrip('/')}/trackers/{tracker.id}/inputs?week={week.isoformat()}"
    page = render_template("mail/reminder.html", tracker=tracker, week=week, fire=fire, link=link)
    msg = EmailMessage()
    msg["Subject"] = f"Weekly update needed: {tracker.name} report goes out {fire:%a %d %b at %H:%M}"
    msg["To"] = ", ".join(recipients)
    msg.set_content(html_to_text(page) + "\n")
    msg.add_alternative(page, subtype="html")
    return msg


def send_reminder(session, tracker_id: int, week: date, now_utc: datetime) -> bool:
    """Claim, send and record one reminder; ``False`` when it was not sent (claimed elsewhere, nobody to send it
    to, or the delivery failed, in which case the claim is given back)."""
    tracker = session.get(Tracker, tracker_id)
    recipients = reminder_recipients(session, tracker)
    if not recipients:
        logger.warning("No one to remind about tracker %s, week %s", tracker_id, week)
        return False
    claimed = session.execute(
        insert(ReportReminder)
        .values(tracker_id=tracker_id, week_ending=week, recipients=recipients)
        .on_conflict_do_nothing()
        .returning(ReportReminder.tracker_id)
    ).scalar_one_or_none()
    session.commit()
    if claimed is None:
        return False
    fire = next_send(tracker, now_utc)
    try:
        smtp.send_message(build_reminder(tracker, week, fire, recipients))
    except Exception:
        logger.exception("The reminder for tracker %s, week %s could not be sent", tracker_id, week)
        session.execute(
            delete(ReportReminder).where(ReportReminder.tracker_id == tracker_id, ReportReminder.week_ending == week)
        )
        session.commit()
        return False
    record(
        session, user_id=None, tracker_id=tracker_id, action="report_reminder_sent", entity="tracker",
        entity_id=tracker_id, detail={"week_ending": week.isoformat(), "recipients": recipients},
    )  # fmt: skip
    session.commit()
    return True


def send_due_reminders(session, now_utc: datetime) -> int:
    """Send every due reminder; returns how many were sent. One failure never stops the others."""
    sent = 0
    for tracker_id, week in due_reminders(session, now_utc):
        try:
            sent += send_reminder(session, tracker_id, week, now_utc)
        except Exception:
            session.rollback()
            logger.exception("The reminder for tracker %s, week %s could not be processed", tracker_id, week)
    return sent
