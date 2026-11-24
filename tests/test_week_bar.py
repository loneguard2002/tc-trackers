"""The week bar's deadline and state texts (pure; no database)."""

from __future__ import annotations

from datetime import date, datetime, time, timezone

from tracker.entries.week_bar import deadline, week_state
from tracker.models import ReportInput, Tracker

FRIDAY = date(2026, 11, 20)


def make(**kw) -> Tracker:
    values = {
        "week_ending_weekday": 4,
        "first_week_ending": date(2026, 9, 4),
        "last_week_ending": date(2026, 12, 18),
        "send_time": time(17, 0),
        "send_timezone": "Europe/London",
        "schedule_enabled": True,
    }
    values.update(kw)
    return Tracker(**values)


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def test_the_send_is_today():
    assert deadline(make(), FRIDAY, None, utc(2026, 11, 20, 9, 0)) == ("Report goes out today at 17:00", "warning")


def test_the_send_is_tomorrow():
    assert deadline(make(), FRIDAY, None, utc(2026, 11, 19, 20, 0)) == ("Report goes out tomorrow at 17:00", "warning")


def test_the_send_is_further_away():
    text, tone = deadline(make(), date(2026, 11, 27), None, utc(2026, 11, 20, 18, 0))
    assert (text, tone) == ("Report goes out on Fri 27 Nov at 17:00", "warning")


def test_the_send_time_is_read_in_the_trackers_zone():
    tracker = make(send_timezone="Asia/Tokyo")
    # 23:30 UTC on Thursday is 08:30 on Friday in Tokyo: the send at 17:00 Tokyo time is still today.
    assert deadline(tracker, FRIDAY, None, utc(2026, 11, 19, 23, 30))[0] == "Report goes out today at 17:00"


def test_a_sent_week_says_when_in_the_trackers_zone():
    text, tone = deadline(make(), FRIDAY, utc(2026, 11, 20, 17, 2), utc(2026, 11, 22, 9, 0))
    assert (text, tone) == ("Report sent on Fri 20 Nov at 17:02", "muted")


def test_a_sent_week_wins_over_sending_off():
    assert (
        deadline(make(schedule_enabled=False), FRIDAY, utc(2026, 11, 20, 17, 2), utc(2026, 11, 22, 9, 0))[1] == "muted"
    )


def test_sending_off():
    assert deadline(make(schedule_enabled=False), FRIDAY, None, utc(2026, 11, 18, 9, 0)) == (
        "Automatic sending is off",
        "muted",
    )


def test_a_passed_send_time_with_nothing_sent():
    assert deadline(make(), FRIDAY, None, utc(2026, 11, 23, 9, 0)) == ("Report was due on Fri 20 Nov at 17:00", "muted")


def test_just_before_and_just_after_the_send_time():
    assert deadline(make(), FRIDAY, None, utc(2026, 11, 20, 16, 59))[1] == "warning"
    assert deadline(make(), FRIDAY, None, utc(2026, 11, 20, 17, 0))[1] == "muted"


def test_week_state():
    assert week_state(None) == "Not written yet"
    assert week_state(ReportInput(status=None, headline="", decisions="")) == "Not written yet"
    assert week_state(ReportInput(status="Amber", headline="", decisions="")) == "Written · Amber"
    assert week_state(ReportInput(status=None, headline="Slow", decisions="")) == "Written · status not set"
