"""Keeps each person's calendar reminder in step with the tracker.

A ``CalendarReminder`` row records that a person switched the reminder on and what their calendar was last sent. The
action follows from comparing what is wanted now with what was sent: a request when the person should have it and the
calendar does not hold it, an update when the series changed (or on ``force``), a cancellation when they should not
have it and the calendar does. ``SEQUENCE`` rises only after a successful delivery; a failed delivery changes nothing
remembered except ``last_error``, so the next cycle tries again.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Literal

from sqlalchemy import or_, select

from ..auth.roles import user_role
from ..mail import smtp
from ..mail.sending import error_text
from ..models import CalendarReminder, Tracker, User
from .ics import build_invite_email, fingerprint, inputs_url, series_for

logger = logging.getLogger(__name__)

Action = Literal["request", "update", "cancel"]


def wanted(session, row: CalendarReminder) -> bool:
    """Whether the person should hold the reminder now: switched on, tracker active, and able to edit it."""
    if not row.enabled:
        return False
    tracker = session.get(Tracker, row.tracker_id)
    user = session.get(User, row.user_id)
    if tracker is None or user is None or tracker.status != "active":
        return False
    return user_role(session, user, tracker.id) in ("editor", "owner")


def sync_reminder(session, row: CalendarReminder, now_utc: datetime, force: bool = False) -> Action | None:
    """Send what the person's calendar needs, if anything. Returns the action delivered, or ``None``."""
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
    if action is None:
        return None

    sequence = 0 if row.sent_at is None else row.sequence + 1
    method = "CANCEL" if action == "cancel" else "REQUEST"
    try:
        organizer = smtp.get_smtp_config(session)["from_"]
        smtp.send_message(build_invite_email(series, organizer, user.email, method, sequence, now_utc))
    except Exception as exc:
        logger.exception("Calendar reminder %s for tracker %s, user %s failed", action, row.tracker_id, row.user_id)
        session.rollback()
        row = session.get(CalendarReminder, (row.user_id, row.tracker_id))
        row.last_error = error_text(exc)
        session.commit()
        return None
    row.sequence = sequence
    row.sent_state = "cancelled" if action == "cancel" else "sent"
    row.sent_fingerprint = None if action == "cancel" else current
    row.sent_at = now_utc
    row.last_error = None
    session.commit()
    return action


def sync_all(session, now_utc: datetime) -> int:
    """Bring every switched-on or delivered reminder up to date. Returns the number delivered."""
    keys = session.execute(
        select(CalendarReminder.user_id, CalendarReminder.tracker_id)
        .where(or_(CalendarReminder.enabled.is_(True), CalendarReminder.sent_state == "sent"))
        .order_by(CalendarReminder.tracker_id, CalendarReminder.user_id)
    ).all()
    delivered = 0
    for user_id, tracker_id in keys:
        try:
            row = session.get(CalendarReminder, (user_id, tracker_id))
            if row is not None and sync_reminder(session, row, now_utc) is not None:
                delivered += 1
        except Exception:
            session.rollback()
            logger.exception("Calendar reminder for tracker %s, user %s could not be processed", tracker_id, user_id)
    return delivered
