"""The texts on the Weekly update page's week bar: whether the week is written and when its report goes out."""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from ..models import ReportInput, Tracker


def week_state(row: ReportInput | None) -> str:
    """``Not written yet``, or ``Written`` and the saved status (written means a status or a headline is saved)."""
    if row is None or not (row.status or row.headline):
        return "Not written yet"
    return f"Written · {row.status or 'status not set'}"


def short_date(value: date | None) -> str:
    """A date without its year, such as ``18 Dec``; the missing-value dash for ``None``."""
    return "\u2013" if value is None else f"{value.day} {value:%b}"


def _day(moment: datetime) -> str:
    return f"{moment:%a} {moment.day} {moment:%b}"


def deadline(tracker: Tracker, week, sent_at: datetime | None, now_utc: datetime) -> tuple[str, str]:
    """The deadline text and its tone (``warning`` or ``muted``) for the shown week. Pure; no database.

    The week's send fires on the week-ending day at the tracker's send time, in its time zone. A report that went
    out is reported as sent, whatever the schedule says now.
    """
    zone = ZoneInfo(tracker.send_timezone)
    if sent_at is not None:
        local = sent_at.astimezone(zone)
        return f"Report sent on {_day(local)} at {local:%H:%M}", "muted"
    if not tracker.schedule_enabled:
        return "Automatic sending is off", "muted"
    fires = datetime.combine(week, tracker.send_time, tzinfo=zone)
    at = f"{_day(fires)} at {fires:%H:%M}"
    now = now_utc.astimezone(timezone.utc)
    if fires <= now:
        return f"Report was due on {at}", "muted"
    days = (week - now.astimezone(zone).date()).days
    when = {0: "today", 1: "tomorrow"}.get(days)
    return (f"Report goes out {when} at {fires:%H:%M}" if when else f"Report goes out on {at}"), "warning"
