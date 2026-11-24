"""Keeps each person's calendar reminder in step with the tracker.

A ``CalendarReminder`` row records that a person switched the reminder on and what their calendar was last sent. The
action follows from comparing what is wanted now with what was sent: a request when the person should have it and the
calendar does not hold it, an update when the series changed (or on ``force``), a cancellation when they should not
have it and the calendar does. ``SEQUENCE`` rises only after a successful delivery; a failed delivery changes nothing
remembered except ``last_error``, so the next cycle tries again.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import date, datetime
from typing import Literal

from sqlalchemy import or_, select

from ..auth.roles import user_role
from ..mail import smtp
from ..mail.sending import error_text
from ..models import CalendarReminder, CalendarReminderEvent, Tracker, User
from .ics import Series, build_invite_email, describe_series, fingerprint, inputs_url, series_for

logger = logging.getLogger(__name__)

Action = Literal["request", "update", "cancel"]

EVENT_LABELS = {
    "switched_on": "Switched on",
    "switched_off": "Switched off",
    "sent": "Invite sent",
    "updated": "Update sent",
    "cancelled": "Cancellation sent",
    "failed": "Sending failed",
    "downloaded": "Downloaded",
}
EVENT_GROUPS = {
    "sent": "sent",
    "updated": "sent",
    "cancelled": "sent",
    "failed": "failed",
    "downloaded": "download",
    "switched_on": "change",
    "switched_off": "change",
}
ERROR_DETAIL_LIMIT = 200

_not_set_up_logged = False


def record_event(session, user_id: int, tracker_id: int, kind: str, detail: str = "") -> None:
    """Add an event to the person's history for the tracker. The caller commits it with the change it records."""
    session.add(CalendarReminderEvent(user_id=user_id, tracker_id=tracker_id, kind=kind, detail=detail))


def events_for(session, user_id: int, tracker_id: int) -> list[CalendarReminderEvent]:
    """One person's events for one tracker, newest first."""
    query = (
        select(CalendarReminderEvent)
        .where(CalendarReminderEvent.user_id == user_id, CalendarReminderEvent.tracker_id == tracker_id)
        .order_by(CalendarReminderEvent.at.desc(), CalendarReminderEvent.id.desc())
    )
    return list(session.scalars(query))


def _update_detail(sent: dict | None, current: dict) -> str:
    """What changed since the delivered series, in words; ``Sent again`` when nothing did."""
    sent = sent or {}
    found = []
    if sent.get("name") != current["name"]:
        found.append("Tracker renamed")
    if sent.get("first") != current["first"] or sent.get("last") != current["last"]:
        found.append("Dates changed")
    if sent.get("weekday") != current["weekday"]:
        found.append("Week-ending day changed")
    if sent.get("tz") != current["tz"]:
        found.append("Time zone changed")
    return "; ".join(found) or "Sent again"


def _cancel_reason(session, row: CalendarReminder) -> str:
    """Why the reminder is no longer wanted, in the order ``wanted`` checks."""
    if not row.enabled:
        return "Switched off"
    if session.get(Tracker, row.tracker_id).status != "active":
        return "Tracker archived"
    if session.get(User, row.user_id).status != "active":
        return "Account not active"
    return "Edit rights removed"


def email_set_up(session) -> bool:
    """Whether the application has a sending address and a mail host to send from."""
    config = smtp.get_smtp_config(session)
    return bool(config.get("from_") and config.get("host"))


def _lock(session, row: CalendarReminder, skip_locked: bool = False) -> CalendarReminder | None:
    """Re-read the row under ``FOR UPDATE`` so the request handler and the scheduler never send for it at once.

    The caller's pending changes are flushed first (the query autoflushes), so they are kept. With ``skip_locked`` a
    row someone else holds gives ``None``. The lock lasts until the caller commits or rolls back.
    """
    query = (
        select(CalendarReminder)
        .where(CalendarReminder.user_id == row.user_id, CalendarReminder.tracker_id == row.tracker_id)
        .with_for_update(skip_locked=skip_locked)
        .execution_options(populate_existing=True)
    )
    return session.scalars(query).first()


def wanted(session, row: CalendarReminder) -> bool:
    """Whether the person should hold the reminder now: switched on, tracker active, and able to edit it."""
    if not row.enabled:
        return False
    tracker = session.get(Tracker, row.tracker_id)
    user = session.get(User, row.user_id)
    if tracker is None or user is None or tracker.status != "active":
        return False
    return user_role(session, user, tracker.id) in ("editor", "owner")


def _sent_series(current: Series, sent: dict) -> Series:
    """The series as last delivered, from its stored fingerprint; the link is the current one."""
    return replace(
        current,
        name=sent["name"],
        weekday=sent["weekday"],
        first=date.fromisoformat(sent["first"]),
        last=date.fromisoformat(sent["last"]),
        tz=sent["tz"],
    )


def _record_failure(session, row: CalendarReminder, message: str) -> None:
    """Remember the error and commit, keeping the caller's other pending changes. Never raises."""
    try:
        row.last_error = message
        record_event(session, row.user_id, row.tracker_id, "failed", message[:ERROR_DETAIL_LIMIT])
        session.commit()
    except Exception:
        logger.exception(
            "Calendar reminder error for tracker %s, user %s could not be recorded", row.tracker_id, row.user_id
        )
        session.rollback()


def sync_reminder(session, row: CalendarReminder, now_utc: datetime, force: bool = False) -> Action | None:
    """Send what the person's calendar needs, if anything. Returns the action delivered, or ``None``."""
    locked = _lock(session, row)
    if locked is None:
        return None
    row = locked
    tracker = session.get(Tracker, row.tracker_id)
    user = session.get(User, row.user_id)
    series = series_for(tracker, user, inputs_url(tracker.id))
    current = fingerprint(series)
    if wanted(session, row):
        if row.sent_state != "sent":
            action: Action | None = "request"
        elif force or row.sent_fingerprint != current:
            action = "update"
        else:
            action = None
    else:
        action = "cancel" if row.sent_state == "sent" else None
    if action is None or not email_set_up(session):
        return None

    if action == "request":
        kind, detail = "sent", describe_series(series)
    elif action == "update":
        kind, detail = "updated", _update_detail(row.sent_fingerprint, current)
    else:
        kind, detail = "cancelled", _cancel_reason(session, row)
    if action == "cancel" and row.sent_fingerprint:
        series = _sent_series(series, row.sent_fingerprint)  # cancel exactly what the calendar holds
    sequence = 0 if row.sent_at is None else row.sequence + 1
    method = "CANCEL" if action == "cancel" else "REQUEST"
    try:
        organizer = smtp.get_smtp_config(session)["from_"]
        smtp.send_message(build_invite_email(series, organizer, user.email, method, sequence, now_utc))
    except Exception as exc:
        logger.exception("Calendar reminder %s for tracker %s, user %s failed", action, row.tracker_id, row.user_id)
        _record_failure(session, row, error_text(exc))
        return None
    row.sequence = sequence
    row.sent_state = "cancelled" if action == "cancel" else "sent"
    row.sent_fingerprint = None if action == "cancel" else current
    row.sent_at = now_utc
    row.last_error = None
    record_event(session, row.user_id, row.tracker_id, kind, detail)
    session.commit()
    return action


def sync_all(session, now_utc: datetime) -> int:
    """Bring every switched-on or delivered reminder up to date. Returns the number delivered.

    Does nothing while email is not set up (one info line per process). A row a request is holding is skipped.
    """
    global _not_set_up_logged
    if not email_set_up(session):
        if not _not_set_up_logged:
            _not_set_up_logged = True
            logger.info("Calendar reminders are not sent: email is not set up in this application yet")
        return 0
    keys = session.execute(
        select(CalendarReminder.user_id, CalendarReminder.tracker_id)
        .where(or_(CalendarReminder.enabled.is_(True), CalendarReminder.sent_state == "sent"))
        .order_by(CalendarReminder.tracker_id, CalendarReminder.user_id)
    ).all()
    delivered = 0
    for user_id, tracker_id in keys:
        try:
            row = session.get(CalendarReminder, (user_id, tracker_id))
            if row is not None:
                row = _lock(session, row, skip_locked=True)
            if row is not None and sync_reminder(session, row, now_utc) is not None:
                delivered += 1
            session.commit()  # releases the lock
        except Exception:
            session.rollback()
            logger.exception("Calendar reminder for tracker %s, user %s could not be processed", tracker_id, user_id)
    return delivered
