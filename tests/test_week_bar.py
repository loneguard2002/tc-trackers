"""The week bar's deadline and state texts (pure; no database)."""

from __future__ import annotations

from datetime import date, datetime, time, timezone

from tracker.entries.week_bar import deadline, next_reminder, week_state
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
        "status": "active",
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


def test_an_archived_tracker_promises_no_report():
    text, tone = deadline(make(status="archived"), FRIDAY, None, utc(2026, 11, 18, 9, 0))
    assert (text, tone) == ("Archived: no report goes out", "muted")


def test_an_archived_tracker_still_shows_a_report_that_went_out():
    text, _ = deadline(make(status="archived"), FRIDAY, utc(2026, 11, 20, 17, 2), utc(2026, 11, 22, 9, 0))
    assert text == "Report sent on Fri 20 Nov at 17:02"


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


def test_a_dst_change_week_reads_the_send_in_local_time():
    # London ends summer time on Sunday 25 Oct 2026; the Friday after it is on GMT, the one before on BST.
    tracker = make(first_week_ending=date(2026, 9, 4), last_week_ending=date(2026, 12, 18))
    assert deadline(tracker, date(2026, 10, 30), None, utc(2026, 10, 30, 16, 59))[0] == "Report goes out today at 17:00"
    assert deadline(tracker, date(2026, 10, 30), None, utc(2026, 10, 30, 17, 0))[0] == (
        "Report was due on Fri 30 Oct at 17:00"
    )
    assert deadline(tracker, date(2026, 10, 23), None, utc(2026, 10, 23, 16, 0))[0] == (
        "Report was due on Fri 23 Oct at 17:00"
    )
    assert deadline(tracker, date(2026, 10, 23), None, utc(2026, 10, 23, 15, 59))[1] == "warning"
    # Sent at 16:02 UTC on 30 Oct is 16:02 GMT; on 23 Oct 16:02 UTC is 17:02 BST.
    assert deadline(tracker, date(2026, 10, 23), utc(2026, 10, 23, 16, 2), utc(2026, 11, 1, 9, 0))[0] == (
        "Report sent on Fri 23 Oct at 17:02"
    )


def test_a_week_several_weeks_ahead():
    assert deadline(make(), date(2026, 12, 18), None, utc(2026, 11, 20, 9, 0)) == (
        "Report goes out on Fri 18 Dec at 17:00",
        "warning",
    )


def test_next_reminder_on_the_week_ending_day_before_and_after_08_45():
    tracker = make()
    assert next_reminder(tracker, utc(2026, 11, 20, 8, 44)) == FRIDAY
    assert next_reminder(tracker, utc(2026, 11, 20, 8, 45)) == date(2026, 11, 27)


def test_next_reminder_after_the_last_week_ending():
    tracker = make(last_week_ending=FRIDAY)
    assert next_reminder(tracker, utc(2026, 11, 20, 8, 44)) == FRIDAY
    assert next_reminder(tracker, utc(2026, 11, 20, 8, 45)) is None


def test_next_reminder_uses_the_trackers_zone():
    tracker = make(send_timezone="Asia/Tokyo")
    # 23:44 UTC on Thursday is 08:44 on Friday in Tokyo; a minute later the reminder has gone.
    assert next_reminder(tracker, utc(2026, 11, 19, 23, 44)) == FRIDAY
    assert next_reminder(tracker, utc(2026, 11, 19, 23, 45)) == date(2026, 11, 27)
    # 22:00 UTC on Friday is already Saturday in Tokyo.
    assert next_reminder(tracker, utc(2026, 11, 20, 22, 0)) == date(2026, 11, 27)
