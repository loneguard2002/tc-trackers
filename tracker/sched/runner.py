"""Scheduled report sending: which sends are due, claiming them, and the scheduler cycle.

The fire-time arithmetic (``cron_for``, ``due_week_ending``) is pure so that DST and the 24 hour window can be tested
without a database. A due send is claimed by inserting its ``ReportSend`` row through the partial unique index on
``(tracker_id, week_ending) WHERE trigger = 'scheduled'``: only the process whose insert succeeds sends the report.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

from ..mail import sending
from ..models import ReportSend, Tracker
from .schedules import next_occurrences

logger = logging.getLogger(__name__)

LOOKBACK = timedelta(hours=24)


def cron_for(tracker: Tracker) -> str:
    """The cron expression for the tracker's weekly send (cron numbers Sunday as 0)."""
    return f"{tracker.send_time.minute} {tracker.send_time.hour} * * {(tracker.week_ending_weekday + 1) % 7}"


def due_week_ending(tracker: Tracker, now_utc: datetime) -> date | None:
    """The week-ending whose send time has passed within the last 24 hours, or ``None``. Pure; no database.

    The latest fire in ``(now - 24h, now]`` is taken; its local date is the week-ending. Older fires are skipped, and a
    week outside the tracker's weeks is never due.
    """
    now = now_utc.astimezone(timezone.utc).replace(tzinfo=None)
    fires = next_occurrences("cron", {"expr": cron_for(tracker)}, tracker.send_timezone, now - LOOKBACK, now)
    if not fires:
        return None
    local = fires[-1].replace(tzinfo=timezone.utc).astimezone(ZoneInfo(tracker.send_timezone))
    week_ending = local.date()
    if not tracker.first_week_ending <= week_ending <= tracker.last_week_ending:
        return None
    return week_ending


def next_send(tracker: Tracker, now_utc: datetime) -> datetime | None:
    """The next scheduled send, in the tracker's time zone, or ``None`` once the last week-ending has passed. Pure."""
    now = now_utc.astimezone(timezone.utc).replace(tzinfo=None)
    start = max(now, datetime.combine(tracker.first_week_ending - timedelta(days=1), datetime.min.time()))
    fires = next_occurrences(
        "cron", {"expr": cron_for(tracker)}, tracker.send_timezone, start, start + timedelta(days=8)
    )
    zone = ZoneInfo(tracker.send_timezone)
    for fire in fires:
        local = fire.replace(tzinfo=timezone.utc).astimezone(zone)
        if local.date() > tracker.last_week_ending:
            return None
        if local.date() >= tracker.first_week_ending:
            return local
    return None


def due_sends(session, now_utc: datetime) -> list[tuple[int, date]]:
    """``(tracker_id, week_ending)`` pairs that are due and have no scheduled ``ReportSend`` yet."""
    trackers = session.scalars(
        select(Tracker).where(Tracker.status == "active", Tracker.schedule_enabled.is_(True)).order_by(Tracker.id)
    ).all()
    candidates = [(t.id, week) for t in trackers if (week := due_week_ending(t, now_utc)) is not None]
    if not candidates:
        return []
    existing = set(
        session.execute(
            select(ReportSend.tracker_id, ReportSend.week_ending).where(
                ReportSend.trigger == "scheduled", ReportSend.tracker_id.in_([t for t, _ in candidates])
            )
        ).all()
    )
    return [pair for pair in candidates if pair not in {(t, w) for t, w in existing}]


def _claim(session, tracker_id: int, week_ending: date) -> int | None:
    """Insert the scheduled row and commit it; ``None`` when another process already holds this week."""
    statement = (
        insert(ReportSend)
        .values(
            tracker_id=tracker_id,
            week_ending=week_ending,
            trigger="scheduled",
            status="sending",
            recipients=[],
            attempts=0,
        )
        .on_conflict_do_nothing(index_elements=["tracker_id", "week_ending"], index_where=text("trigger = 'scheduled'"))
        .returning(ReportSend.id)
    )
    send_id = session.execute(statement).scalar_one_or_none()
    session.commit()
    return send_id


def _fail_claimed(session, send_id: int, message: str, now: datetime) -> None:
    """Mark a claimed send ``failed`` (no retry) and audit it, so it is never left in ``sending``."""
    session.rollback()
    send = session.scalars(
        select(ReportSend).where(ReportSend.id == send_id).with_for_update().execution_options(populate_existing=True)
    ).one()
    send.status = "failed"
    send.error = message
    send.next_attempt_at = None
    sending._audit(session, send, session.get(Tracker, send.tracker_id), None)
    session.commit()


def _send_claimed(session, tracker_id: int, send_id: int, now: datetime) -> None:
    tracker = session.get(Tracker, tracker_id)
    if not sending.recipient_emails(session, tracker):
        _fail_claimed(session, send_id, sending.NO_RECIPIENTS_MESSAGE, now)
        return
    claimed = session.get(ReportSend, send_id)
    try:
        sending.send_report(session, tracker, claimed.week_ending, "scheduled", None, now, claimed=claimed)
    except Exception as exc:
        logger.exception("Scheduled report send %s failed", send_id)
        _fail_claimed(session, send_id, sending.error_text(exc), now)


def run_scheduler_cycle(session, now_utc: datetime) -> int:
    """Send every due report once, then retry queued sends. Returns the number of sends attempted."""
    attempted = 0
    for tracker_id, week_ending in due_sends(session, now_utc):
        try:
            send_id = _claim(session, tracker_id, week_ending)
            if send_id is None:
                continue
            attempted += 1
            _send_claimed(session, tracker_id, send_id, now_utc)
        except Exception:
            session.rollback()
            logger.exception("Scheduled send for tracker %s, week %s could not be processed", tracker_id, week_ending)
    return attempted + sending.retry_queued(session, now_utc)
