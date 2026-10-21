from datetime import date, timedelta

import pytest

from tracker.engine.weeks import (
    first_week_ending,
    in_progress_week,
    max_last_week_ending,
    report_date_to_week_ending,
    week_ending_for,
    week_endings,
)

FRI = 4


def test_week_ending_for_midweek():
    assert week_ending_for(date(2026, 10, 14), FRI) == date(2026, 10, 16)


def test_week_ending_for_on_the_day():
    assert week_ending_for(date(2026, 10, 16), FRI) == date(2026, 10, 16)


def test_first_week_ending_matches_week_ending_for():
    assert first_week_ending(date(2026, 10, 14), FRI) == date(2026, 10, 16)
    assert first_week_ending(date(2026, 10, 16), FRI) == date(2026, 10, 16)


def test_monday_report_maps_to_previous_friday():
    # 2026-10-12 is a Monday; the brief's 2026-10-13 (Tuesday) -> 2026-10-10 (Saturday) is not a Friday.
    assert report_date_to_week_ending(date(2026, 10, 12), FRI) == date(2026, 10, 9)


def test_report_date_on_week_ending_day_maps_to_previous_week():
    assert report_date_to_week_ending(date(2026, 10, 16), FRI) == date(2026, 10, 9)


def test_week_endings_52_max():
    first = date(2026, 1, 2)
    assert len(week_endings(first, max_last_week_ending(first))) == 52
    with pytest.raises(ValueError):
        week_endings(first, first + timedelta(weeks=52))


def test_max_last_week_ending_is_51_weeks_after_first():
    first = date(2026, 1, 2)
    assert max_last_week_ending(first) == first + timedelta(weeks=51)


def test_week_endings_misaligned():
    with pytest.raises(ValueError):
        week_endings(date(2026, 1, 2), date(2026, 1, 10))


def test_week_endings_last_before_first_raises():
    first = date(2026, 1, 2)
    with pytest.raises(ValueError):
        week_endings(first, first - timedelta(weeks=1))


def test_week_endings_single_entry():
    first = date(2026, 1, 2)
    assert week_endings(first, first) == [first]


def test_week_endings_are_seven_days_apart():
    first = date(2026, 1, 2)
    result = week_endings(first, first + timedelta(weeks=3))
    assert result == [first + timedelta(weeks=n) for n in range(4)]


def test_in_progress_week():
    assert in_progress_week(date(2026, 10, 14), FRI) == date(2026, 10, 16)
    assert in_progress_week(date(2026, 10, 16), FRI) is None


@pytest.mark.parametrize("bad_weekday", [-1, 7, 10])
def test_invalid_weekday_raises(bad_weekday):
    d = date(2026, 10, 14)
    with pytest.raises(ValueError):
        week_ending_for(d, bad_weekday)
    with pytest.raises(ValueError):
        first_week_ending(d, bad_weekday)
    with pytest.raises(ValueError):
        report_date_to_week_ending(d, bad_weekday)
    with pytest.raises(ValueError):
        in_progress_week(d, bad_weekday)
