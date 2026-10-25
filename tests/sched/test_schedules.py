"""Schedule arithmetic: cron_for and the fire-time logic. No database required."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from types import SimpleNamespace

from tracker.sched.runner import cron_for, due_week_ending
from tracker.sched.schedules import next_occurrences


def tracker(**overrides):
    values = {
        "week_ending_weekday": 4,
        "send_time": time(17, 0),
        "send_timezone": "Europe/London",
        "first_week_ending": date(2026, 9, 4),
        "last_week_ending": date(2026, 12, 25),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def test_cron_for_friday_1700():
    assert cron_for(tracker()) == "0 17 * * 5"


def test_cron_for_sunday_and_minutes():
    assert cron_for(tracker(week_ending_weekday=6, send_time=time(8, 5))) == "5 8 * * 0"
    assert cron_for(tracker(week_ending_weekday=0)) == "0 17 * * 1"


def test_cron_for_fires_on_the_week_ending_day():
    fires = next_occurrences(
        "cron", {"expr": cron_for(tracker())}, "Europe/London", datetime(2026, 10, 12), datetime(2026, 10, 20)
    )
    assert fires == [datetime(2026, 10, 16, 16, 0)]


def test_due_after_fire_time_london():
    # Friday 16 October 2026 17:00 in London (BST) is 16:00 UTC.
    assert due_week_ending(tracker(), utc(2026, 10, 16, 16, 5)) == date(2026, 10, 16)


def test_due_exactly_at_fire_time():
    assert due_week_ending(tracker(), utc(2026, 10, 16, 16, 0)) == date(2026, 10, 16)


def test_not_due_before_fire_time():
    assert due_week_ending(tracker(), utc(2026, 10, 16, 15, 55)) is None


def test_dst_end_week():
    # Friday 30 October 2026 is after the clocks go back (25 October): 17:00 London is 17:00 UTC.
    assert due_week_ending(tracker(), utc(2026, 10, 30, 16, 5)) is None
    assert due_week_ending(tracker(), utc(2026, 10, 30, 17, 5)) == date(2026, 10, 30)


def test_fire_older_than_24h_skipped():
    assert due_week_ending(tracker(), utc(2026, 10, 17, 16, 1)) is None
    assert due_week_ending(tracker(), utc(2026, 10, 17, 15, 59)) == date(2026, 10, 16)


def test_week_outside_tracker_not_due():
    assert due_week_ending(tracker(first_week_ending=date(2026, 10, 23)), utc(2026, 10, 16, 16, 5)) is None
    assert due_week_ending(tracker(last_week_ending=date(2026, 10, 9)), utc(2026, 10, 16, 16, 5)) is None


def test_week_boundaries_inclusive():
    assert due_week_ending(tracker(first_week_ending=date(2026, 10, 16)), utc(2026, 10, 16, 16, 5)) == date(
        2026, 10, 16
    )
    assert due_week_ending(tracker(last_week_ending=date(2026, 10, 16)), utc(2026, 10, 16, 16, 5)) == date(2026, 10, 16)


def test_local_date_differs_from_utc_date():
    # Friday 17:00 in Auckland (NZDT, UTC+13) is Friday 04:00 UTC; Friday 23:30 in Los Angeles is Saturday UTC.
    nz = tracker(send_timezone="Pacific/Auckland")
    assert due_week_ending(nz, utc(2026, 10, 16, 4, 5)) == date(2026, 10, 16)
    la = tracker(send_timezone="America/Los_Angeles", send_time=time(23, 30))
    assert due_week_ending(la, utc(2026, 10, 17, 6, 35)) == date(2026, 10, 16)


def test_run_scheduler_once_exits_non_zero_on_failure(app, monkeypatch):
    from tracker.sched import runner

    def boom(session, now):
        raise RuntimeError("boom")

    monkeypatch.setattr(runner, "run_scheduler_cycle", boom)
    result = app.test_cli_runner().invoke(args=["run-scheduler", "--once"])
    assert result.exit_code == 1


def test_run_scheduler_once_logs_result(app, monkeypatch):
    from tracker.sched import runner

    monkeypatch.setattr(runner, "run_scheduler_cycle", lambda session, now: 3)
    result = app.test_cli_runner().invoke(args=["run-scheduler", "--once"])
    assert result.exit_code == 0 and "3 send(s) attempted" in result.output
