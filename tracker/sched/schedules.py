"""Turn a job's schedule spec into concrete UTC fire times.

This module is deliberately pure: no database, no clock of its own, no I/O.
Everything it needs arrives as an argument, which is what makes the awkward
cases (DST, month ends, holidays) testable without a fixture.

Four schedule kinds, per the implementation pack:

    simple           every N minutes/hours/days from an anchor
    cron             a standard 5-field cron expression
    monthly_pattern  a day of the month, or an Nth weekday, or an Nth
                     business day — including counting backwards from the end
    business_day     every business day at a fixed local time

The spec is stored as JSON rather than as a cron string so that the three
non-cron kinds keep their meaning. "First business day of the month" cannot
be written as cron at all, and reducing it to one would throw away the intent
the moment someone opens the edit screen.

Times are computed in the job's own timezone and converted to UTC on the way
out, because "06:00 in London" has to stay 06:00 across a DST boundary — the
whole point of storing a timezone per job.
"""
from __future__ import annotations

import calendar as _calendar
import datetime as dt
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

SCHEDULE_KINDS = ("simple", "cron", "monthly_pattern", "business_day")

# Guard against a spec that matches almost nothing (or nothing at all) turning
# a planning pass into an unbounded loop. A 48h horizon can't legitimately
# need more than a few thousand candidate days.
_MAX_CANDIDATE_DAYS = 800
_MAX_OCCURRENCES = 10_000


class ScheduleError(ValueError):
    """A schedule spec that cannot be interpreted."""


@dataclass(frozen=True)
class Calendar:
    """Which days are working days for a given country.

    Weekends live here rather than as a global constant because they are not
    universal — the UAE moved from a Fri/Sat weekend to Sat/Sun in January
    2022, and Dubai is in scope. A hardcoded Sat/Sun would silently produce
    wrong fire times the day a Gulf desk is added.
    """

    country_code: str = ""
    # ISO weekday numbers, Monday = 0.
    weekend_days: frozenset[int] = frozenset({5, 6})
    holidays: frozenset[dt.date] = field(default_factory=frozenset)
    #: The last date this calendar's holiday data actually covers. `None` means
    #: "no holiday data at all", which is not the same as "no holidays": an
    #: empty calendar that has never been refreshed cannot tell a working day
    #: from Christmas.
    data_through: dt.date | None = None

    def is_business_day(self, d: dt.date) -> bool:
        return d.weekday() not in self.weekend_days and d not in self.holidays

    def covers(self, d: dt.date) -> bool:
        """Is `d` inside the range this calendar can actually answer for?

        A calendar with no country code is the weekends-only default. It needs
        no data, so it covers every date forever — a job that names no calendar
        must not start holding because of a mechanism it never opted into.

        A *named* calendar is only as good as the dates loaded into it. Past
        its horizon `is_business_day` would keep answering, cheerfully, and
        every answer would be "not a holiday" — which is right about 96% of the
        time and catastrophically wrong the rest. Refusing to answer is the
        only honest option, and it is why this returns a bool rather than
        letting the caller guess.
        """
        if not self.country_code:
            return True
        return self.data_through is not None and d <= self.data_through


#: Used when a job names no calendar. Sat/Sun weekend, no holidays — the
#: behaviour you would get from a scheduler with no holiday support at all,
#: so an unconfigured job is never *worse* off than before.
DEFAULT_CALENDAR = Calendar(country_code="")


def _tz(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except Exception as exc:  # unknown zone, bad tzdata
        raise ScheduleError(f"Unknown timezone {name!r}") from exc


def _parse_at(value, field_name: str = "at") -> dt.time:
    """Parse 'HH:MM' or 'HH:MM:SS' into a time."""
    if isinstance(value, dt.time):
        return value
    if not isinstance(value, str):
        raise ScheduleError(f"{field_name} must be a 'HH:MM' string")
    parts = value.strip().split(":")
    if len(parts) not in (2, 3):
        raise ScheduleError(f"{field_name} must look like '06:00', got {value!r}")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        raise ScheduleError(f"{field_name} must look like '06:00', got {value!r}") from None
    h, m = nums[0], nums[1]
    s = nums[2] if len(nums) == 3 else 0
    if not (0 <= h <= 23 and 0 <= m <= 59 and 0 <= s <= 59):
        raise ScheduleError(f"{field_name} is out of range: {value!r}")
    return dt.time(h, m, s)


def _localise(naive: dt.datetime, tz: ZoneInfo) -> dt.datetime | None:
    """Attach *tz* to a naive local datetime, handling DST oddities.

    Spring forward: the wall-clock time does not exist. Returns None so the
    caller can skip the occurrence rather than invent a time nobody asked for.

    Autumn back: the time happens twice. `fold=0` takes the first, which is
    the earlier UTC instant — a job scheduled for 01:30 runs once, at the
    first 01:30, rather than twice or at the later one.
    """
    aware = naive.replace(tzinfo=tz, fold=0)
    # A non-existent local time round-trips through UTC to a *different* wall
    # clock reading. That is the documented way to detect the gap.
    if aware.astimezone(dt.timezone.utc).astimezone(tz).replace(tzinfo=None) != naive:
        return None
    return aware


def _to_utc(naive: dt.datetime, tz: ZoneInfo) -> dt.datetime | None:
    aware = _localise(naive, tz)
    if aware is None:
        return None
    return aware.astimezone(dt.timezone.utc).replace(tzinfo=None)


def _nth_weekday(year: int, month: int, weekday: int, nth: int) -> dt.date | None:
    """The nth weekday of a month. nth < 0 counts back from the end."""
    days_in_month = _calendar.monthrange(year, month)[1]
    matches = [
        dt.date(year, month, day)
        for day in range(1, days_in_month + 1)
        if dt.date(year, month, day).weekday() == weekday
    ]
    if not matches:
        return None
    idx = nth - 1 if nth > 0 else nth
    try:
        return matches[idx]
    except IndexError:
        # "5th Friday" in a month that has four. Skipped, not clamped —
        # clamping would silently fire on the 4th and read as correct.
        return None


def _nth_business_day(year: int, month: int, nth: int, cal: Calendar) -> dt.date | None:
    """The nth business day of a month. nth < 0 counts back from the end."""
    days_in_month = _calendar.monthrange(year, month)[1]
    matches = [
        d for day in range(1, days_in_month + 1)
        if cal.is_business_day(d := dt.date(year, month, day))
    ]
    if not matches:
        return None
    idx = nth - 1 if nth > 0 else nth
    try:
        return matches[idx]
    except IndexError:
        return None


def _month_iter(start: dt.date, months: int):
    y, m = start.year, start.month
    for _ in range(months):
        yield y, m
        m += 1
        if m == 13:
            y, m = y + 1, 1


# ── the four kinds ───────────────────────────────────────────────────────────

def _simple(spec: dict, tz: ZoneInfo, after: dt.datetime, until: dt.datetime, cal):
    every = spec.get("every")
    unit = (spec.get("unit") or "minutes").lower()
    if not isinstance(every, int) or every <= 0:
        raise ScheduleError("simple schedule needs a positive integer 'every'")
    if unit not in ("minutes", "hours", "days"):
        raise ScheduleError(f"unit must be minutes, hours or days, got {unit!r}")
    step = dt.timedelta(**{unit: every})

    anchor_raw = spec.get("anchor")
    if anchor_raw:
        try:
            anchor = dt.datetime.fromisoformat(str(anchor_raw).replace("Z", ""))
        except ValueError:
            raise ScheduleError(f"anchor is not an ISO timestamp: {anchor_raw!r}") from None
    else:
        # No anchor: align to the epoch so the cadence is stable across
        # restarts instead of drifting to whenever the process last started.
        anchor = dt.datetime(1970, 1, 1)

    # Jump straight to the first occurrence after `after` rather than looping
    # from the anchor, which for an epoch anchor would be millions of steps.
    elapsed = (after - anchor).total_seconds()
    n = int(elapsed // step.total_seconds()) + 1
    cur = anchor + step * n
    while cur <= after:
        cur += step

    out = []
    while cur <= until and len(out) < _MAX_OCCURRENCES:
        out.append(cur)
        cur += step
    return out


# Cron numbers Sunday as 0 (and accepts 7 for it too). APScheduler numbers
# Monday as 0. Its CronTrigger.from_crontab does NOT reconcile the two — as of
# 3.11.3 it passes the field through untouched, so the standard "weekdays"
# expression `0 6 * * 1-5` is read as Tue-Sat: jobs run on Saturday and skip
# Monday. Verified against the installed version, not assumed.
#
# Converting to day *names* sidesteps the numbering entirely, and expanding
# ranges to an explicit list avoids a second trap: APScheduler orders days
# mon..sun, so a wrapping range like cron's `0-2` (Sun,Mon,Tue) is not
# expressible as "sun-tue".
_CRON_DOW = {0: "sun", 1: "mon", 2: "tue", 3: "wed", 4: "thu", 5: "fri", 6: "sat", 7: "sun"}
_DOW_NAME_TO_NUM = {n: i for i, n in _CRON_DOW.items() if i != 7}
_APS_DOW_ORDER = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _dow_value(tok: str) -> int:
    tok = tok.strip().lower()
    if tok in _DOW_NAME_TO_NUM:
        return _DOW_NAME_TO_NUM[tok]
    try:
        v = int(tok)
    except ValueError:
        raise ScheduleError(f"day-of-week value not recognised: {tok!r}") from None
    if not 0 <= v <= 7:
        raise ScheduleError(f"day-of-week out of range: {tok!r}")
    return 0 if v == 7 else v


def _cron_dow_to_names(field: str) -> str:
    """Rewrite a cron day-of-week field as APScheduler day names."""
    days: set[int] = set()
    for token in field.split(","):
        token = token.strip()
        if not token:
            raise ScheduleError("empty day-of-week entry")
        step = 1
        if "/" in token:
            token, raw_step = token.split("/", 1)
            try:
                step = int(raw_step)
            except ValueError:
                raise ScheduleError(f"bad day-of-week step: {raw_step!r}") from None
            if step <= 0:
                raise ScheduleError(f"day-of-week step must be positive: {raw_step!r}")
        token = token.strip()
        if token == "*":
            lo, hi = 0, 6
        elif "-" in token.lstrip("-"):
            lo_s, hi_s = token.split("-", 1)
            lo, hi = _dow_value(lo_s), _dow_value(hi_s)
        else:
            lo = _dow_value(token)
            # `5/2` means "from 5 onwards, every 2nd" — a range to the end.
            hi = 6 if step > 1 else lo
        span = (hi - lo) % 7
        days.update((lo + off) % 7 for off in range(0, span + 1, step))
    if not days:
        raise ScheduleError("day-of-week matched no days")
    if len(days) == 7:
        return "*"
    names = {_CRON_DOW[d] for d in days}
    return ",".join(n for n in _APS_DOW_ORDER if n in names)


def _cron(spec: dict, tz: ZoneInfo, after: dt.datetime, until: dt.datetime, cal):
    expr = spec.get("expr")
    if not expr or not isinstance(expr, str):
        raise ScheduleError("cron schedule needs an 'expr' string")
    # APScheduler is already a dependency and its cron parser is well tested,
    # so it is used here as a *library* even though it no longer drives the
    # scheduler itself. Swapping in croniter later would touch only this
    # function.
    try:
        from apscheduler.triggers.cron import CronTrigger
    except ImportError as exc:
        raise ScheduleError("cron schedules need APScheduler installed") from exc

    parts = expr.split()
    if len(parts) != 5:
        raise ScheduleError(f"cron expression must have 5 fields, got {expr!r}")
    minute, hour, day, month, dow = parts
    try:
        trigger = CronTrigger(
            minute=minute, hour=hour, day=day, month=month,
            day_of_week=_cron_dow_to_names(dow), timezone=tz,
        )
    except ScheduleError:
        raise
    except Exception as exc:
        raise ScheduleError(f"cron expression is not valid: {expr!r}") from exc

    out = []
    # get_next_fire_time is inclusive of `now`, but this window is half-open at
    # the start — otherwise replanning from the last fire re-emits that fire.
    cur = (after + dt.timedelta(seconds=1)).replace(tzinfo=dt.timezone.utc).astimezone(tz)
    end = until.replace(tzinfo=dt.timezone.utc).astimezone(tz)
    prev = None
    while len(out) < _MAX_OCCURRENCES:
        nxt = trigger.get_next_fire_time(prev, cur)
        if nxt is None or nxt > end:
            break
        moment = nxt.astimezone(dt.timezone.utc).replace(tzinfo=None)
        if moment > after:
            out.append(moment)
        prev = nxt
        cur = nxt + dt.timedelta(seconds=1)
    return out


def _monthly_pattern(spec: dict, tz: ZoneInfo, after: dt.datetime, until: dt.datetime, cal: Calendar):
    at = _parse_at(spec.get("at", "00:00"))
    day = spec.get("day")
    nth = spec.get("nth")
    weekday = spec.get("weekday")
    business = spec.get("business_day")

    given = [k for k in ("day", "nth", "business_day") if spec.get(k) is not None]
    if len(given) != 1:
        raise ScheduleError(
            "monthly_pattern needs exactly one of 'day', 'nth' (+'weekday') or 'business_day'"
        )

    start_local = (after.replace(tzinfo=dt.timezone.utc).astimezone(tz)).date()
    end_local = (until.replace(tzinfo=dt.timezone.utc).astimezone(tz)).date()
    months = (end_local.year - start_local.year) * 12 + (end_local.month - start_local.month) + 2

    out = []
    for y, m in _month_iter(start_local.replace(day=1), max(1, months)):
        target: dt.date | None
        if day is not None:
            if not isinstance(day, int) or not (-31 <= day <= 31) or day == 0:
                raise ScheduleError(f"day must be a non-zero integer between -31 and 31, got {day!r}")
            dim = _calendar.monthrange(y, m)[1]
            d = day if day > 0 else dim + day + 1
            # Day 31 in a 30-day month is skipped, not clamped to the 30th.
            target = dt.date(y, m, d) if 1 <= d <= dim else None
        elif nth is not None:
            if weekday is None:
                raise ScheduleError("'nth' also needs 'weekday' (Mon=0 … Sun=6)")
            if not isinstance(weekday, int) or not (0 <= weekday <= 6):
                raise ScheduleError(f"weekday must be 0-6 (Mon=0), got {weekday!r}")
            if not isinstance(nth, int) or nth == 0 or not (-5 <= nth <= 5):
                raise ScheduleError(f"nth must be a non-zero integer between -5 and 5, got {nth!r}")
            target = _nth_weekday(y, m, weekday, nth)
        else:
            if not isinstance(business, int) or business == 0 or not (-31 <= business <= 31):
                raise ScheduleError(
                    f"business_day must be a non-zero integer between -31 and 31, got {business!r}"
                )
            # The *whole* month has to be covered, not just the day we land on.
            # "3rd business day" is a position in a sequence: one unknown
            # holiday earlier in the month moves it, and "last business day"
            # is counted backwards from the 31st. A partially-covered month
            # would resolve to a plausible, wrong date.
            if not cal.covers(dt.date(y, m, _calendar.monthrange(y, m)[1])):
                target = None
            else:
                target = _nth_business_day(y, m, business, cal)

        if target is None:
            continue
        moment = _to_utc(dt.datetime.combine(target, at), tz)
        if moment is not None and after < moment <= until:
            out.append(moment)
    return sorted(out)


def _business_day(spec: dict, tz: ZoneInfo, after: dt.datetime, until: dt.datetime, cal: Calendar):
    at = _parse_at(spec.get("at", "00:00"))
    start_local = (after.replace(tzinfo=dt.timezone.utc).astimezone(tz)).date()
    end_local = (until.replace(tzinfo=dt.timezone.utc).astimezone(tz)).date()

    out = []
    d = start_local
    guard = 0
    while d <= end_local and guard < _MAX_CANDIDATE_DAYS:
        guard += 1
        # Past the calendar's horizon we stop rather than carry on. Every day
        # beyond it would look like a working day, so continuing would not
        # produce *fewer* fires, it would produce confidently wrong ones —
        # including on Christmas Day.
        if not cal.covers(d):
            break
        if cal.is_business_day(d):
            moment = _to_utc(dt.datetime.combine(d, at), tz)
            if moment is not None and after < moment <= until:
                out.append(moment)
        d += dt.timedelta(days=1)
    return out


_KINDS = {
    "simple": _simple,
    "cron": _cron,
    "monthly_pattern": _monthly_pattern,
    "business_day": _business_day,
}


def next_occurrences(
    kind: str,
    spec: dict,
    timezone: str,
    after: dt.datetime,
    until: dt.datetime,
    calendar: Calendar | None = None,
) -> list[dt.datetime]:
    """Every fire time in (after, until], as naive UTC datetimes.

    Half-open at the start so that replanning from the last known fire cannot
    produce that same fire again — `sched_fires` has a UNIQUE(job_id, due_at)
    that would reject it anyway, but relying on a constraint violation to get
    the arithmetic right is not a design.
    """
    if kind not in _KINDS:
        raise ScheduleError(f"Unknown schedule kind {kind!r}")
    if not isinstance(spec, dict):
        raise ScheduleError("schedule spec must be an object")
    if until <= after:
        return []
    return _KINDS[kind](spec, _tz(timezone), after, until, calendar or DEFAULT_CALENDAR)


def describe(kind: str, spec: dict, timezone: str = "UTC") -> str:
    """A one-line human reading of a schedule, for the register and the
    save bar. The edit screen echoes this back before committing, so it has
    to describe the spec as stored rather than as typed."""
    try:
        if kind == "simple":
            every, unit = spec.get("every"), spec.get("unit", "minutes")
            unit_txt = unit[:-1] if every == 1 else unit
            return f"every {every} {unit_txt}"
        if kind == "cron":
            return f"cron: {spec.get('expr', '')}"
        if kind == "business_day":
            return f"every business day at {_parse_at(spec.get('at', '00:00')).strftime('%H:%M')}"
        if kind == "monthly_pattern":
            at = _parse_at(spec.get("at", "00:00")).strftime("%H:%M")
            if spec.get("day") is not None:
                d = spec["day"]
                which = f"day {d}" if d > 0 else ("last day" if d == -1 else f"{-d} days from the end")
                return f"monthly on {which} at {at}"
            if spec.get("business_day") is not None:
                b = spec["business_day"]
                which = f"business day {b}" if b > 0 else (
                    "last business day" if b == -1 else f"{-b} business days from the end")
                return f"monthly on the {which} at {at}"
            nth, wd = spec.get("nth"), spec.get("weekday")
            names = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
            ord_txt = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th", -1: "last"}.get(nth, f"{nth}th")
            return f"monthly on the {ord_txt} {names[wd]} at {at}"
    except Exception:
        pass
    return f"{kind} schedule"
