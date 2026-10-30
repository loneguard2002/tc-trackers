"""The activity retention setting and the daily prune (spec sections 6.2, 8.1 and 8.2).

Retention is optional: an absent setting keeps entries indefinitely. The worker prunes at most once a UTC day; the
day is claimed through ``audit_last_pruned`` so that two workers never prune twice.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from flask import flash, redirect, url_for
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..audit import NO_CHANGES_MESSAGE, change, record
from ..models import AppSetting, AuditLog

RETENTION_KEY = "audit_retention_days"
LAST_PRUNED_KEY = "audit_last_pruned"
MIN_RETENTION_DAYS = 90
MAX_RETENTION_DAYS = 3650
RETENTION_ERROR = "Enter a whole number of days from 90 to 3,650, or leave the box empty to keep entries indefinitely."
# Plain digits, or digits grouped in threes by commas as the screen writes them ("3,650"); nothing else.
_DAYS_PATTERN = re.compile(r"[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+")
_MAX_DAYS_TEXT = 12  # longer text cannot be a valid period, and is refused before any conversion


def retention_days(session: Session) -> int | None:
    """The retention period in days, or ``None`` to keep entries indefinitely."""
    value = session.scalar(select(AppSetting.value).where(AppSetting.key == RETENTION_KEY))
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def parse_retention(value: str | None) -> tuple[int | None, str | None]:
    """``(days, error)`` for the text of the retention box; blank means indefinitely. Surrounding spaces are ignored."""
    text = (value or "").strip()
    if not text:
        return None, None
    if len(text) > _MAX_DAYS_TEXT or not _DAYS_PATTERN.fullmatch(text):
        return None, RETENTION_ERROR
    days = int(text.replace(",", ""))
    if not MIN_RETENTION_DAYS <= days <= MAX_RETENTION_DAYS:
        return None, RETENTION_ERROR
    return days, None


def prune_audit_log(session: Session, now_utc: datetime) -> int | None:
    """Delete entries older than the retention period, once a UTC day. Returns the number removed.

    ``None`` when no retention is set or today's prune was already claimed. An entry is recorded only when something
    was removed (a stated narrower reading of spec 8.2).
    """
    days = retention_days(session)
    if days is None:
        return None
    now_utc = now_utc.astimezone(timezone.utc)
    today = now_utc.date().isoformat()
    claim = (
        insert(AppSetting)
        .values(key=LAST_PRUNED_KEY, value=today)
        .on_conflict_do_update(index_elements=["key"], set_={"value": today}, where=AppSetting.value != today)
        .returning(AppSetting.key)
    )
    if session.execute(claim).scalar_one_or_none() is None:
        session.rollback()
        return None
    cutoff = now_utc - timedelta(days=days)
    removed = session.execute(delete(AuditLog).where(AuditLog.at < cutoff)).rowcount
    if removed > 0:
        record(
            session,
            user_id=None,
            tracker_id=None,
            action="audit_pruned",
            entity="audit_log",
            entity_id=None,
            detail={"removed": removed, "cutoff": cutoff.isoformat()},
        )
    session.commit()
    return removed


def save_retention(session: Session, user_id: int, submitted: str | None):
    """Store a submitted retention value and log the change; the response is a redirect to the Activity screen."""
    days, error = parse_retention(submitted)
    if error:
        flash(error, "danger")
        return redirect(url_for("activity.index"))
    before = retention_days(session)
    if days == before:
        flash(NO_CHANGES_MESSAGE, "info")
    else:
        if days is None:
            session.execute(delete(AppSetting).where(AppSetting.key == RETENTION_KEY))
        else:
            session.merge(AppSetting(key=RETENTION_KEY, value=str(days)))
        record(
            session,
            user_id=user_id,
            tracker_id=None,
            action="audit_retention_changed",
            entity="app_settings",
            entity_id=RETENTION_KEY,
            detail=change(before, days),
        )
        session.commit()
        flash("Retention saved.", "success")
    return redirect(url_for("activity.index"))
