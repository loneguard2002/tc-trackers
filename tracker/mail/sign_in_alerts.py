"""The email to the people who manage sign-in protection when a failed sign-in starts a block.

It goes to every active holder of Manage sign-in protection (administrators included), only when the mail server is
configured and they have not switched it off on Admin › Sign-in protection. At most one goes out every ``ALERT_GAP``,
however many blocks start, so an attack cannot flood the inbox: the email lists everyone blocked at the time it is sent,
and the count beside Sign-in protection in the menu shows every block, emailed or not. The gap is claimed in
``app_settings`` before sending, so two workers cannot both send; a failed delivery gives the claim back. Nothing here
ever stops the sign-in that set it off.
"""

from __future__ import annotations

import logging
from datetime import timedelta, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert

from ..audit import record
from ..auth import throttle
from ..auth.permissions import user_permissions
from ..models import AppSetting, User
from . import smtp
from .access import TIME_FORMAT, build_email, mail_configured

logger = logging.getLogger(__name__)

ALERT_GAP = timedelta(minutes=15)
LAST_ALERT_KEY = "login_block_alert_sent_at"  # when the last email went out (UTC, ISO 8601)
KIND_NAMES = {"account": "Account", "address": "Address"}
PERMISSION = "manage_sign_in_protection"


def recipients(session) -> list[str]:
    """The active people who can open Sign-in protection, by email."""
    people = session.scalars(select(User).where(User.status == "active").order_by(User.email))
    return [person.email for person in people if PERMISSION in user_permissions(session, person)]


def _claim(session, now_text: str, cutoff_text: str) -> bool:
    """Take the gap: ``True`` when no email went out after ``cutoff_text``. The times are UTC ISO 8601 text of one
    format, so comparing the text compares the times."""
    claim = (
        insert(AppSetting)
        .values(key=LAST_ALERT_KEY, value=now_text)
        .on_conflict_do_update(index_elements=["key"], set_={"value": now_text}, where=AppSetting.value <= cutoff_text)
        .returning(AppSetting.key)
    )
    return session.execute(claim).scalar_one_or_none() is not None


def _give_back(session, previous: str | None) -> None:
    if previous is None:
        session.execute(delete(AppSetting).where(AppSetting.key == LAST_ALERT_KEY))
    else:
        session.execute(update(AppSetting).where(AppSetting.key == LAST_ALERT_KEY).values(value=previous))
    session.commit()


def send_block_alert(session) -> bool:
    """Email the people who manage sign-in protection who is blocked now, unless an email went out in the last
    ``ALERT_GAP``. ``True`` when it was sent. Call it after the failed sign-in is committed; it commits."""
    try:
        limits = throttle.load_limits(session)
        if not limits.email_admins or not mail_configured(session):
            return False
        team = recipients(session)
        if not team:
            return False
        now = session.scalar(select(func.now())).astimezone(timezone.utc)
        previous = session.scalar(select(AppSetting.value).where(AppSetting.key == LAST_ALERT_KEY))
        if not _claim(session, now.isoformat(), (now - ALERT_GAP).isoformat()):
            session.rollback()
            return False
        session.commit()
        _, rows = throttle.summaries(session, limits)
        blocked = [row for row in rows if row.blocked]
        if not blocked:  # unblocked in the moment between the failure and now
            _give_back(session, previous)
            return False
        count = len(blocked)
        msg = build_email(
            session,
            f"Progress Tracker: sign-in blocked for {count} account{'' if count == 1 else 's'} or address"
            f"{'' if count == 1 else 'es'}",
            "sign_in_blocked",
            bcc=team,
            rows=blocked,
            kind_names=KIND_NAMES,
            limits=limits,
            gap_minutes=int(ALERT_GAP.total_seconds() // 60),
            sent=now.strftime(TIME_FORMAT),
        )
    except Exception:
        logger.exception("The sign-in block email could not be prepared")
        session.rollback()
        return False
    try:
        smtp.send_message(msg)
    except Exception:
        logger.exception("The sign-in block email could not be sent")
        _give_back(session, previous)
        return False
    record(
        session,
        user_id=None,
        tracker_id=None,
        action="sign_in_alert_sent",
        entity="app_settings",
        entity_id="sign_in_limits",
        detail={"blocked": count, "recipients": team},
    )
    session.commit()
    return True
