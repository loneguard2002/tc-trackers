"""Activity › Overview: how Progress Tracker is used over time (design: claude.ai/artifact/KNqTyQUCmetrW5Dj5RY47o).

Every figure is built from the entries the viewer can already see in the log (``scope.visible_entries``), so a person
who is not an administrator sees figures for their own trackers and the areas they manage only.

Rulings (27 Nov 2026):
- Weeks run Saturday to Friday and end on Friday, in UTC like the log's times.
- A sign-in is a password or Microsoft sign-in; failed sign-ins are not counted, and do not make a person active.
- A change is any entry a person made that is not a sign-in. Entries the app writes on its own (no person) are left out.
- A tracker's weekly update for a week is the first of: its weekly update saved for that week, or an entry recorded
  for that week. On time: by the end of the tracker's week-ending day (UTC). Late: after it. Not updated: none, and the
  week has ended. Still due: none yet, and the week has not ended. Archived trackers are not listed.
- The figures reach back only as far as Activity keeps entries; the page says so when a period reaches past that.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from typing import NamedTuple

from flask import render_template, request, url_for
from sqlalchemy import func, select

from ..auth import current_user, tracker_roles
from ..auth.permissions import permission_required, user_permissions
from ..db import get_session
from ..models import AuditLog, CompletionEntry, Tracker, User
from . import bp
from .kinds import KIND_LABELS, NOT_CHANGES, SIGN_INS, kind_of
from .retention import retention_days
from .scope import visible_entries

PERIODS = {4: "4 weeks", 12: "12 weeks", 26: "6 months", 52: "12 months"}
PERIOD_WORDS = {4: "the last 4 weeks", 12: "the last 12 weeks", 26: "the last 6 months", 52: "the last 12 months"}
PREVIOUS_WORDS = {
    4: "the 4 weeks before",
    12: "the 12 weeks before",
    26: "the 6 months before",
    52: "the 12 months before",
}
DEFAULT_PERIOD = 12
METRICS = {
    "changes": ("Changes made", "Every change a person made. Sign-ins are not counted.", ("change", "changes")),
    "people": (
        "People active",
        "People with at least one entry that week, sign-ins included.",
        ("person active", "people active"),
    ),
    "signins": (
        "Sign-ins",
        "Password and Microsoft sign-ins. Failed sign-ins are not counted.",
        ("sign-in", "sign-ins"),
    ),
}
DEFAULT_METRIC = "changes"
FAILED_SIGN_INS = NOT_CHANGES - SIGN_INS
FRIDAY = 4
HISTORY = 104  # weeks kept in view: the longest period and the period before it
GRID_WEEKS = 12  # weeks in Weekly updates by tracker
HEAT_WEEKS = 53  # columns in the heatmap
TRACKER_ROWS = 8  # trackers shown before "Show all"
TOP_PEOPLE = 6
DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
FULL_DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
STATUS_WORDS = {
    "done": "updated by the week’s end",
    "late": "updated late",
    "missed": "not updated",
    "due": "still due",
    "none": "not tracked that week",
}

# Chart geometry (SVG user units). The weekly chart scales with its box; the heatmap keeps its size and scrolls.
CHART_W, CHART_LEFT, CHART_TOP, CHART_H = 1000, 52, 12, 200
HEAT_CELL, HEAT_PITCH, HEAT_TOP = 11, 14, 20  # the squares; the day names and shares sit beside them, unscrolled


def utcnow() -> datetime:
    """Now, in UTC (a function so tests can fix the clock)."""
    return datetime.now(timezone.utc)


def week_end(day: date) -> date:
    """The Friday that ends ``day``'s week (Saturday to Friday)."""
    return day + timedelta(days=(FRIDAY - day.weekday()) % 7)


def midnight(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=timezone.utc)


def short(day: date) -> str:
    return f"{day.day} {day:%b}"


def long_day(day: date) -> str:
    return f"{DAY_NAMES[day.weekday()]} {day.day} {day:%b %Y}"


def number(value: int) -> str:
    return f"{value:,}"


def plural(value: int, one: str, many: str) -> str:
    return f"{number(value)} {one if value == 1 else many}"


def tracker_week(end: date, weekday: int) -> date:
    """The day with ``weekday`` in the Saturday-to-Friday week ending ``end``: a tracker's own week ending there."""
    return end - timedelta(days=(FRIDAY - weekday) % 7)


def update_status(first: datetime | None, week_ending: date, now: datetime) -> str:
    """done, late, missed or due: the weekly update for one tracker week, from the time it was first updated."""
    cut_off = midnight(week_ending + timedelta(days=1))
    if first is not None:
        return "done" if first < cut_off else "late"
    return "due" if now < cut_off else "missed"


class Weeks(NamedTuple):
    ends: list[date]  # Fridays, oldest first; the last is the current week
    today: date

    @property
    def current(self) -> int:
        return len(self.ends) - 1

    def index(self, day: date) -> int:
        return self.current - (self.ends[-1] - week_end(day)).days // 7

    def start(self, w: int) -> date:
        return self.ends[w] - timedelta(days=6)

    def last_day(self, w: int) -> date:
        return min(self.ends[w], self.today)


def _option(value, current, label: str, url: str) -> dict:
    return {"label": label, "url": url, "current": value == current}


def _delta(diff: int, unit: str, previous: str) -> dict:
    if diff == 0:
        return {"text": f"Same as {previous}", "tone": "flat"}
    sign = "+" if diff > 0 else "−"
    return {"text": f"{sign}{number(abs(diff))}{unit} on {previous}", "tone": "up" if diff > 0 else "down"}


def _nice_top(maximum: int) -> tuple[int, int]:
    """A round axis top above ``maximum`` and the step between its gridlines (four or five lines)."""
    raw = max(maximum, 1) / 4
    magnitude = 10 ** max(len(str(int(raw))) - 1, 0)
    step = next(int(m * magnitude) for m in (1, 2, 5, 10) if m * magnitude >= raw)
    step = max(step, 1)
    top = -(-max(maximum, 1) // step) * step
    if top <= maximum:
        top += step
    return top, step


def _log_url(**args) -> str:
    return url_for("activity.index", **{key: value for key, value in args.items() if value not in (None, "")})


@bp.get("/overview")
@permission_required("view_activity")
def overview():
    db = get_session()
    viewer = current_user()
    now = utcnow()
    today = now.date()
    period = request.args.get("period", type=int)
    period = period if period in PERIODS else DEFAULT_PERIOD
    metric = request.args.get("metric", "")
    metric = metric if metric in METRICS else DEFAULT_METRIC
    show_all = request.args.get("trackers") == "all"

    can_open = None if viewer.is_admin else tracker_roles(db, viewer)
    scope = visible_entries(viewer, user_permissions(db, viewer), can_open)
    base = [scope] if scope is not None else []

    weeks = Weeks([week_end(today) - timedelta(weeks=HISTORY - 1 - i) for i in range(HISTORY)], today)
    cur = weeks.current
    first_day = weeks.start(0)

    # One pass over the entries the viewer can see: per day, action and person.
    day_col = func.date(func.timezone("UTC", AuditLog.at))
    rows = db.execute(
        select(day_col, AuditLog.action, AuditLog.user_id, func.count())
        .where(*base, AuditLog.at >= midnight(first_day))
        .group_by(day_col, AuditLog.action, AuditLog.user_id)
    ).all()
    changes = [0] * HISTORY
    sign_ins = [0] * HISTORY
    active: list[set[int]] = [set() for _ in range(HISTORY)]
    per_day: Counter[date] = Counter()
    person_week: Counter[tuple[int, int]] = Counter()
    kind_week: Counter[tuple[str, int]] = Counter()
    for day, action, user_id, count in rows:
        w = weeks.index(day)
        if not 0 <= w <= cur:
            continue
        if user_id is not None and action not in FAILED_SIGN_INS:
            active[w].add(user_id)
        if action in SIGN_INS:
            sign_ins[w] += count
        if user_id is not None and action not in NOT_CHANGES:
            changes[w] += count
            per_day[day] += count
            person_week[(user_id, w)] += count
            kind_week[(kind_of(action), w)] += count

    first, prev_first = cur - period + 1, cur - 2 * period + 1
    period_weeks, prev_weeks = range(first, cur + 1), range(prev_first, first)

    def total(series: list[int], span: range) -> int:
        return sum(series[w] for w in span)

    def people_in(span: range) -> int:
        return len(set().union(*(active[w] for w in span)))

    # The trackers in view and their weekly updates.
    trackers_query = select(Tracker).where(Tracker.status == "active")
    if can_open is not None:
        trackers_query = trackers_query.where(Tracker.id.in_(list(can_open)))
    trackers = list(db.scalars(trackers_query.order_by(Tracker.name, Tracker.id)))
    ids = [t.id for t in trackers]
    firsts: dict[tuple[int, date], datetime] = {}
    if ids:
        for tracker_id, week, at in db.execute(
            select(AuditLog.tracker_id, AuditLog.entity_id, func.min(AuditLog.at))
            .where(AuditLog.action == "inputs_saved", AuditLog.tracker_id.in_(ids), AuditLog.at >= midnight(first_day))
            .group_by(AuditLog.tracker_id, AuditLog.entity_id)
        ):
            try:
                key = (tracker_id, date.fromisoformat(week or ""))
            except ValueError:
                continue
            firsts[key] = min(at, firsts.get(key, at))
        for tracker_id, week, at in db.execute(
            select(CompletionEntry.tracker_id, CompletionEntry.week_ending, func.min(CompletionEntry.created_at))
            .where(CompletionEntry.tracker_id.in_(ids), CompletionEntry.week_ending >= first_day)
            .group_by(CompletionEntry.tracker_id, CompletionEntry.week_ending)
        ):
            key = (tracker_id, week)
            firsts[key] = min(at, firsts.get(key, at))

    def status_of(tracker: Tracker, w: int) -> str:
        day = tracker_week(weeks.ends[w], tracker.week_ending_weekday)
        created = tracker.created_at.astimezone(timezone.utc).date() if tracker.created_at else day
        if day < tracker.first_week_ending or day > tracker.last_week_ending or day < created:
            return "none"
        return update_status(firsts.get((tracker.id, day)), day, now)

    statuses = {t.id: [status_of(t, w) for w in range(HISTORY)] for t in trackers}

    def on_time(span: range) -> tuple[int, int]:
        done = counted = 0
        for series in statuses.values():
            for w in span:
                if series[w] in ("done", "late", "missed"):
                    counted += 1
                    done += series[w] == "done"
        return done, counted

    # Headline figures.
    users_total = db.scalar(select(func.count(User.id)).where(User.status == "active")) or 0
    people_now, people_before = people_in(period_weeks), people_in(prev_weeks)
    signs_now, signs_before = total(sign_ins, period_weeks), total(sign_ins, prev_weeks)
    changes_now, changes_before = total(changes, period_weeks), total(changes, prev_weeks)
    ok_now, all_now = on_time(range(first, cur))
    ok_before, all_before = on_time(prev_weeks)
    pct_now = round(ok_now * 100 / all_now) if all_now else None
    pct_before = round(ok_before * 100 / all_before) if all_before else None
    previous = PREVIOUS_WORDS[period]
    kpis = [
        {
            "label": "People active",
            "value": number(people_now),
            "unit": f"of {number(users_total)}",
            "delta": _delta(people_now - people_before, "", previous),
        },
        {
            "label": "Sign-ins",
            "value": number(signs_now),
            "unit": "",
            "delta": _delta(signs_now - signs_before, "", previous),
        },
        {
            "label": "Changes made",
            "value": number(changes_now),
            "unit": "",
            "delta": _delta(changes_now - changes_before, "", previous),
        },
        {
            "label": "Weekly updates on time",
            "value": f"{pct_now}%" if pct_now is not None else "–",
            "unit": f"{number(ok_now)} of {number(all_now)}" if all_now else "no weekly updates due",
            "delta": _delta(pct_now - pct_before, " points", previous)
            if pct_now is not None and pct_before is not None
            else {"text": f"Nothing to compare in {previous}", "tone": "flat"},
        },
    ]

    def overview_url(**changes_) -> str:
        args = {"period": period, "metric": metric, "trackers": "all" if show_all else None}
        args.update(changes_)
        if args.get("period") == DEFAULT_PERIOD:
            args["period"] = None
        if args.get("metric") == DEFAULT_METRIC:
            args["metric"] = None
        return url_for("activity.overview", **{k: v for k, v in args.items() if v is not None})

    periods = [_option(n, period, label, overview_url(period=n)) for n, label in PERIODS.items()]
    metrics = [_option(key, metric, spec[0], overview_url(metric=key) + "#weekly") for key, spec in METRICS.items()]

    # The weekly chart.
    def value_of(w: int) -> int:
        return len(active[w]) if metric == "people" else sign_ins[w] if metric == "signins" else changes[w]

    values = [value_of(w) for w in period_weeks]
    top, step = _nice_top(max(values, default=0))
    slot = (CHART_W - CHART_LEFT) / period
    gap = slot * (0.3 if period <= 12 else 0.2)
    label_every = 1 if period <= 4 else 2 if period <= 12 else 4 if period <= 26 else 8
    created_by_week: dict[int, list[str]] = {}
    for t in trackers:
        if t.created_at:
            w = weeks.index(t.created_at.astimezone(timezone.utc).date())
            created_by_week.setdefault(w, []).append(t.name)
    unit = METRICS[metric][2]
    bars = []
    for i, w in enumerate(period_weeks):
        value = values[i]
        height = value / top * CHART_H
        is_now = w == cur
        when = (
            f"This week so far ({short(weeks.start(w))} to {short(today)})"
            if is_now
            else f"Week ending {short(weeks.ends[w])}"
        )
        made = created_by_week.get(w, [])
        bars.append(
            {
                "x": round(CHART_LEFT + i * slot + gap / 2, 2),
                "y": round(CHART_TOP + CHART_H - height, 2),
                "w": round(slot - gap, 2),
                "h": round(height, 2),
                "cx": round(CHART_LEFT + i * slot + slot / 2, 2),
                "now": is_now,
                "tip": f"{when}: {plural(value, *unit)}",
                "url": _log_url(**{"from": weeks.start(w).isoformat(), "to": weeks.last_day(w).isoformat()}),
                "label": ("This week" if is_now else short(weeks.ends[w]))
                if (period - 1 - i) % label_every == 0
                else "",
                "made": (", ".join(made) + (" were" if len(made) > 1 else " was") + " created that week")
                if made
                else "",
            }
        )
    ticks = [
        {"label": number(v), "y": round(CHART_TOP + CHART_H - v / top * CHART_H, 2)} for v in range(0, top + 1, step)
    ]

    # The heatmap: one square per day, Monday to Sunday, the last 53 weeks.
    monday = today - timedelta(days=today.weekday())
    heat_first = monday - timedelta(weeks=HEAT_WEEKS - 1)
    # Four shades by share of the busiest day, so the busiest day is always the darkest.
    peak = max((v for d, v in per_day.items() if heat_first <= d <= today), default=0)

    def level(v: int) -> int:
        return 0 if v <= 0 or not peak else min(4, -(-v * 4 // peak))

    week_changes: Counter[date] = Counter()
    for d, v in per_day.items():
        week_changes[week_end(d)] += v
    weekday_totals = [0] * 7
    busiest: tuple[int, date | None] = (0, None)
    heat_cells, heat_months = [], []
    for c in range(HEAT_WEEKS):
        col_monday = heat_first + timedelta(weeks=c)
        x = c * HEAT_PITCH
        if col_monday.day <= 7 or (c == 0 and col_monday.day <= 21):
            heat_months.append({"x": x, "label": f"{col_monday:%b}"})
        for k in range(7):
            day = col_monday + timedelta(days=k)
            if day > today:
                continue
            v = per_day.get(day, 0)
            weekday_totals[k] += v
            if v > busiest[0]:
                busiest = (v, day)
            words = "no changes" if v == 0 else plural(v, "change", "changes")
            share = round(v * 100 / week_changes[week_end(day)]) if v and week_changes[week_end(day)] else 0
            detail = (
                f"{long_day(day)}: {words}"
                + (f", {share}% of the changes in the week ending {short(week_end(day))}" if v else "")
                + (" so far today" if day == today else "")
                + "."
            )
            heat_cells.append(
                {
                    "x": x,
                    "y": HEAT_TOP + k * HEAT_PITCH,
                    "level": level(v),
                    "tip": f"{long_day(day)}: {words}" + (" so far" if day == today else ""),
                    "detail": detail,
                    "url": _log_url(**{"from": day.isoformat(), "to": day.isoformat()}),
                }
            )
    heat_total = sum(weekday_totals)
    heat_width = HEAT_WEEKS * HEAT_PITCH - (HEAT_PITCH - HEAT_CELL)
    heat_days = [
        {
            "label": DAY_NAMES[k],
            "y": HEAT_TOP + k * HEAT_PITCH + HEAT_CELL - 1,
            "share": f"{round(weekday_totals[k] * 100 / heat_total)}%" if heat_total else "–",
            "tip": f"{FULL_DAY_NAMES[k]}: {plural(weekday_totals[k], 'change', 'changes')} in 12 months",
        }
        for k in range(7)
    ]
    if heat_total:
        top_day = max(range(7), key=lambda k: weekday_totals[k])
        heat_note = (
            f"Busiest day: {long_day(busiest[1])}, {plural(busiest[0], 'change', 'changes')}. "
            f"{FULL_DAY_NAMES[top_day]} has {round(weekday_totals[top_day] * 100 / heat_total)}% of the year’s changes."
        )
    else:
        heat_note = "No changes in the last 12 months."

    # Weekly updates by tracker.
    grid_first = cur - GRID_WEEKS + 1
    week_heads = [
        {
            "day": weeks.ends[w].day,
            "month": f"{weeks.ends[w]:%b}" if w == grid_first or weeks.ends[w].day <= 7 else "",
            "tip": f"Week ending {short(weeks.ends[w])}",
        }
        for w in range(grid_first, cur + 1)
    ]
    tracker_changes: Counter[int] = Counter()
    if ids:
        tracker_changes.update(
            dict(
                db.execute(
                    select(AuditLog.tracker_id, func.count())
                    .where(
                        *base,
                        AuditLog.tracker_id.in_(ids),
                        AuditLog.user_id.is_not(None),
                        AuditLog.action.not_in(sorted(NOT_CHANGES)),
                        AuditLog.at >= midnight(weeks.start(grid_first)),
                    )
                    .group_by(AuditLog.tracker_id)
                ).all()
            )
        )
    grid_from = weeks.start(grid_first).isoformat()
    rows_all = []
    for t in trackers:
        series = statuses[t.id]
        complete = [series[w] for w in range(grid_first, cur) if series[w] != "none"]
        ok = complete.count("done")
        last = next((w for w in range(cur, -1, -1) if series[w] in ("done", "late")), None)
        missed_last = series[cur - 1] == "missed"
        rows_all.append(
            {
                "name": t.name,
                "url": _log_url(q=t.name, **{"from": grid_from}),
                "cells": [
                    {
                        "status": series[w],
                        "alert": w == cur - 1 and series[w] == "missed",
                        "tip": f"Week ending {short(weeks.ends[w])}: {STATUS_WORDS[series[w]]}",
                    }
                    for w in range(grid_first, cur + 1)
                ],
                "on_time": f"{ok} of {len(complete)}" if complete else "–",
                "last": "This week"
                if last == cur
                else f"Week to {short(weeks.ends[last])}"
                if last is not None
                else "–",
                "missed_last": missed_last,
                "changes": number(tracker_changes.get(t.id, 0)),
                "ratio": ok / len(complete) if complete else 1.0,
            }
        )
    rows_all.sort(key=lambda r: (not r["missed_last"], r["ratio"], r["name"].lower()))
    missed = [r["name"] for r in rows_all if r["missed_last"]]
    last_week = short(weeks.ends[cur - 1])
    if not trackers:
        finding = ""
    elif missed:
        finding = (
            f"{plural(len(missed), 'tracker', 'trackers')} missed the update for the week ending {last_week}: "
            + (", ".join(missed[:-1]) + " and " + missed[-1] if len(missed) > 1 else missed[0])
            + "."
        )
    else:
        finding = f"Every tracker was updated for the week ending {last_week}."

    # Who made the changes, and what changed.
    period_from = weeks.start(first).isoformat()
    person_totals: Counter[int] = Counter()
    for (user_id, w), n in person_week.items():
        if first <= w <= cur:
            person_totals[user_id] += n
    top_people = person_totals.most_common(TOP_PEOPLE)
    names = (
        {
            uid: (name, status)
            for uid, name, status in db.execute(
                select(User.id, User.full_name, User.status).where(User.id.in_([uid for uid, _ in top_people]))
            )
        }
        if top_people
        else {}
    )
    most = top_people[0][1] if top_people else 1
    people = [
        {
            "name": names.get(uid, ("Unknown person", ""))[0],
            "deleted": names.get(uid, ("", ""))[1] == "deleted",
            "initials": "".join(part[0] for part in names.get(uid, ("?", ""))[0].split()[:2]).upper() or "?",
            "count": number(n),
            "share": f"{round(n * 100 / changes_now)}% of changes" if changes_now else "",
            "bar": round(n * 100 / most, 1),
            "url": _log_url(person=uid, **{"from": period_from}),
        }
        for uid, n in top_people
    ]
    kind_totals: Counter[str] = Counter()
    for (kind, w), n in kind_week.items():
        if first <= w <= cur:
            kind_totals[kind] += n
    kind_most = max(kind_totals.values(), default=1)
    kinds = [
        {
            "label": label,
            "count": number(kind_totals[key]),
            "share": f"{round(kind_totals[key] * 100 / changes_now)}%" if changes_now else "",
            "bar": round(kind_totals[key] * 100 / kind_most, 1),
            "url": _log_url(kind=key, **{"from": period_from}),
        }
        for key, label in KIND_LABELS.items()
        if kind_totals[key]
    ]

    # The summary line and the retention note.
    words = PERIOD_WORDS[period]
    lede = (
        f"Over {words}, {number(people_now)} of {number(users_total)} people used Progress Tracker"
        f" and made {plural(changes_now, 'change', 'changes')}"
    )
    if trackers:
        lede += "; " + (
            f"{plural(len(missed), 'tracker', 'trackers')} missed last week’s update"
            if missed
            else "every tracker was updated last week"
        )
    lede += "."
    kept = retention_days(db)
    oldest_needed = min(weeks.start(prev_first), heat_first)
    retention_note = (
        f"Activity keeps entries for {plural(kept, 'day', 'days')},"
        f" so figures before {long_day(today - timedelta(days=kept))} are incomplete."
        if kept and today - timedelta(days=kept) > oldest_needed
        else ""
    )
    return render_template(
        "activity/overview.html",
        current_page="activity",
        lede=lede,
        retention_note=retention_note,
        periods=periods,
        kpis=kpis,
        metrics=metrics,
        chart_title=f"{METRICS[metric][0]} per week",
        chart_note=METRICS[metric][1],
        chart={"width": CHART_W, "height": CHART_TOP + CHART_H + 44, "left": CHART_LEFT, "base": CHART_TOP + CHART_H},
        bars=bars,
        ticks=ticks,
        heat={"width": heat_width, "height": HEAT_TOP + 7 * HEAT_PITCH, "cell": HEAT_CELL},
        heat_cells=heat_cells,
        heat_months=heat_months,
        heat_days=heat_days,
        heat_note=heat_note,
        heat_levels=range(5),
        week_heads=week_heads,
        tracker_rows=rows_all if show_all else rows_all[:TRACKER_ROWS],
        tracker_total=len(rows_all),
        tracker_more=len(rows_all) > TRACKER_ROWS,
        show_all=show_all,
        rows_toggle_url=overview_url(trackers=None if show_all else "all") + "#trackers",
        finding=finding,
        finding_missed=bool(missed),
        people=people,
        people_note=f"Changes made over {words}. Sign-ins are not counted.",
        kinds=kinds,
        kinds_note=f"{plural(changes_now, 'change', 'changes')} over {words}, by kind.",
        period_log_url=_log_url(**{"from": period_from}),
    )
