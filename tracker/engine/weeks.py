"""Week-ending date arithmetic. Pure functions, standard library only.

Weekdays are ints with Monday = 0 and Sunday = 6, matching ``date.weekday()``.
"""

from datetime import date, timedelta

MAX_WEEKS_IN_YEAR = 51


def _check_weekday(weekday: int) -> None:
    if not 0 <= weekday <= 6:
        raise ValueError(f"weekday must be 0 (Monday) to 6 (Sunday), got {weekday!r}")


def week_ending_for(d: date, weekday: int) -> date:
    """Return the first date on or after ``d`` that falls on ``weekday``."""
    _check_weekday(weekday)
    return d + timedelta(days=(weekday - d.weekday()) % 7)


def first_week_ending(start: date, weekday: int) -> date:
    """Return the first week-ending on or after ``start``."""
    return week_ending_for(start, weekday)


def max_last_week_ending(first: date) -> date:
    """Return the latest permitted last week-ending for a series starting at ``first``."""
    return first + timedelta(weeks=MAX_WEEKS_IN_YEAR)


def week_endings(first: date, last: date) -> list[date]:
    """Return every week-ending from ``first`` to ``last`` inclusive, seven days apart."""
    if last < first:
        raise ValueError(f"last ({last}) is before first ({first})")
    if (last - first).days % 7 != 0:
        raise ValueError(f"last ({last}) is not a whole number of weeks after first ({first})")
    if last > max_last_week_ending(first):
        raise ValueError(f"last ({last}) is beyond the 52-week limit from first ({first})")
    count = (last - first).days // 7 + 1
    return [first + timedelta(weeks=n) for n in range(count)]


def report_date_to_week_ending(report_date: date, weekday: int) -> date:
    """Return the latest date strictly before ``report_date`` that falls on ``weekday``."""
    _check_weekday(weekday)
    days_back = (report_date.weekday() - weekday) % 7 or 7
    return report_date - timedelta(days=days_back)


def in_progress_week(as_of: date, weekday: int) -> date | None:
    """Return the upcoming week-ending if it has not yet arrived by ``as_of``, otherwise ``None``."""
    ending = week_ending_for(as_of, weekday)
    return ending if ending > as_of else None
