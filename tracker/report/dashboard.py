"""The data behind the report's "Status at a glance" view: the answer card, tiles, status strip, risks, locations."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from math import ceil
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..engine.calc import COMPLETE, GroupPosition, Headline
from ..formatting import fmt_num, fmt_pct, fmt_rate
from ..models import ReportInput, User
from ..trackers.targets import TargetEntry, moves, shows_history, target_history
from .build import Report
from .charts import unit_title

TONES = {"Red": "red", "Amber": "amber", "Green": "green"}
STRIP_WEEKS = 12
LETTERS = {"Red": "R", "Amber": "A", "Green": "G"}


@dataclass(frozen=True)
class StatusWeek:
    week_ending: date
    status: str | None


@dataclass(frozen=True)
class RiskLine:
    ref: str
    description: str
    rag: str | None
    owner: str
    location: str | None
    due: str  # "Due 4 Dec", "4 days past 20 Nov" or "No due date"
    past: bool


@dataclass(frozen=True)
class LocationLine:
    group: GroupPosition
    note: str


@dataclass(frozen=True)
class TargetLine:
    """One row of "Target date changes"."""

    number: int
    current: bool
    date_text: str  # "18 Dec", or "No target" once removed
    text: str  # "Moved on 12 Oct, 7 days later: Kit delayed."


@dataclass
class Dashboard:
    target: date | None
    targets: list[TargetEntry]
    answer: str
    tone: str
    needed: str | None
    written_by: str | None
    written_on: date | None
    tiles: dict = field(default_factory=dict)
    statuses: list[StatusWeek] = field(default_factory=list)
    status_summary: str = ""
    locations: list[LocationLine] = field(default_factory=list)
    risks: list[RiskLine] = field(default_factory=list)
    chart_subtitle: str = ""
    target_lines: list[TargetLine] = field(default_factory=list)
    target_note: str = ""  # "moved twice, 14 days later than first set"


def _short(day: date) -> str:
    return f"{day.day} {day:%b}"


def _span(days: int) -> str:
    return "a week" if days == 7 else f"{days} day{'' if days == 1 else 's'}"


def answer_sentence(headline: Headline, target: date | None, behind_plan: int | None) -> str:
    """The one-sentence answer: done, on course, late, or not yet known. ``behind_plan`` is units behind plan."""
    if headline.total_scope > 0 and headline.remaining == 0:
        return f"All {fmt_num(headline.total_scope)} done."
    forecast = headline.forecast_completion
    if forecast is None:
        return "Not enough completed weeks to forecast yet."
    if target is None:
        return f"Forecast to finish on {_short(forecast)}. No target date is set."
    days = (forecast - target).days
    if days > 0:
        return f"Forecast to finish on {_short(forecast)}, {_span(days)} after the {_short(target)} target."
    when = "on the target date" if days == 0 else f"{_span(-days)} before the {_short(target)} target"
    behind = f", though {fmt_num(behind_plan)} behind plan" if behind_plan and behind_plan > 0 else ""
    return f"On course to finish on {_short(forecast)}, {when}{behind}."


def _complete_rows(report: Report) -> list:
    """The completed weeks up to the report week: a week still in progress has only a part-week figure."""
    return [r for r in report.rows if r.week_ending <= report.week_ending and r.state == COMPLETE]


def _behind_plan(report: Report) -> int | None:
    """Units behind plan at the last completed week on or before the report week (where the chart's Actual ends)."""
    complete = _complete_rows(report)
    row = complete[-1] if complete else None
    if row is None or row.cum_target is None or row.cum_actual is None:
        return None
    return row.cum_target - row.cum_actual


def _days(days: int) -> str:
    return f"{days} day{'' if days == 1 else 's'}"


def _spark(report: Report) -> dict | None:
    """The completed weeks' actuals up to the report week as a 120 by 32 polyline, with the last point for a dot."""
    values = [r.actual for r in _complete_rows(report) if r.actual is not None]
    if not values:
        return None
    width, height, pad = 120, 32, 4
    top = max(max(values), 1)
    step = (width - 2 * pad) / max(len(values) - 1, 1)
    points = [(pad + i * step, height - pad - v / top * (height - 2 * pad)) for i, v in enumerate(values)]
    return {
        "points": " ".join(f"{x:.1f},{y:.1f}" for x, y in points),
        "last_x": f"{points[-1][0]:.1f}",
        "last_y": f"{points[-1][1]:.1f}",
    }


def _rate_bar(rate: float | None, needed: float | None) -> tuple[str | None, str | None]:
    """The fill and the needed mark as percentages of one scale, a little longer than the larger of the two."""
    scale = max(rate or 0, needed or 0) * 1.25
    if scale <= 0:
        return None, None
    fill = f"{rate / scale * 100:.2f}" if rate is not None else None
    return fill, (f"{needed / scale * 100:.2f}" if needed is not None else None)


def _timeline(week_ending: date, forecast: date | None, target: date | None) -> dict | None:
    """Positions (0 to 100) of the forecast dot and the target mark on a line from the report week onwards."""
    if forecast is None and target is None:
        return None
    last = max(d for d in (week_ending, forecast, target) if d is not None)
    span = max((last - week_ending).days, 1)

    def at(day: date | None) -> str | None:
        """A day's place on the line; a day before the report week sits at its start, never before it."""
        return None if day is None else f"{6 + max((day - week_ending).days, 0) / span * 88:.2f}"

    return {"forecast": at(forecast), "target": at(target), "start": at(week_ending), "end": at(last)}


def _needed_rate(remaining: int, target: date | None, week_ending: date) -> float | None:
    """The weekly rate needed to meet ``target`` from the report week, by the engine's formula (``required_rate``), but
    for the target in force that week rather than today's."""
    if target is None:
        return None
    weeks_left = max(0, ceil((target - week_ending).days / 7))
    return remaining / weeks_left if weeks_left > 0 else None


def _moved_text(targets: list[TargetEntry]) -> str | None:
    """ "Target moved twice: 4 Dec → 11 Dec → 18 Dec" for the current target since it was last set; "Target set
    again: 18 Dec" when it was set again after a removal and not moved since; nothing otherwise."""
    if not targets or targets[-1].kind == "removed":
        return None
    removals = [i for i, e in enumerate(targets) if e.kind == "removed"]
    run = targets[removals[-1] + 1 :] if removals else targets
    count = moves(run)
    if count == 0:
        return f"Target set again: {_short(run[-1].date)}" if removals else None
    times = {1: "once", 2: "twice"}.get(count, f"{count} times")
    return f"Target moved {times}: {' → '.join(_short(e.date) for e in run)}"


def build_tiles(report: Report, target: date | None, targets: list[TargetEntry]) -> dict:
    """The four figure tiles. Each is a dict of the display strings and the numbers for its small visual."""
    h = report.headline
    completed = {
        "value": fmt_num(h.completed),
        "unit": f"of {fmt_num(h.total_scope)}",
        "pct": f"{min(max(h.completed / h.total_scope * 100, 0), 100):.2f}" if h.total_scope else "0.00",
        "sub": f"{fmt_pct(h.pct_complete)} · {fmt_num(h.remaining)} left",
        "label": f"{fmt_pct(h.pct_complete)} complete",
    }

    actual, planned = h.this_week_actual, h.this_week_target
    # A week still in progress has a part-week figure: "28 so far of 40 target", and what is left is "to go", not short.
    so_far = report.in_progress and actual is not None
    unit = "" if planned is None else f"of {fmt_num(planned)} target"
    week = {
        "value": "–" if actual is None else fmt_num(actual),
        "unit": f"so far {unit}".strip() if so_far else unit,
        "tone": "",
        "spark": _spark(report),
    }
    if actual is not None and planned is not None:
        gap = actual - planned
        if so_far and gap < 0:
            week["sub"] = f"{fmt_num(-gap)} to go"
        else:
            week["tone"] = "danger" if gap < 0 else "success"
            week["sub"] = "On target" if gap == 0 else f"{'+' if gap > 0 else '−'}{abs(gap)} against target"
        if h.next_week_target is not None:
            week["sub"] += f" · next week {fmt_num(h.next_week_target)}"
    else:
        week["sub"] = "No target for this week"

    rate, needed = h.forecast_rate, _needed_rate(h.remaining, target, report.week_ending)
    fill, mark = _rate_bar(rate, needed)
    rate_tile = {
        "label": f"Rate ({report.tracker.moving_average_weeks} wk)",
        "value": "–" if rate is None else fmt_rate(rate),
        "unit": "a week",
        "fill": fill,
        "mark": mark,
        "tone": "",
    }
    if needed is None:
        rate_tile["sub"] = "No required rate"
    else:
        rate_tile["sub"] = f"{fmt_rate(needed)} a week needed"
        rate_tile["tone"] = "success" if rate is not None and rate >= needed else "danger"

    forecast = h.forecast_completion
    days = (forecast - target).days if forecast is not None and target is not None else None
    if days is None:
        sub = "No target date" if target is None else "No forecast yet"
    elif days > 0:
        sub = f"{_days(days)} after the {_short(target)} target"
    elif days < 0:
        sub = f"{_days(-days)} before the {_short(target)} target"
    else:
        sub = "On the target date"
    forecast_tile = {
        "value": "–" if forecast is None else _short(forecast),
        "sub": sub,
        "tone": "" if days is None else ("danger" if days > 0 else "success"),
        "timeline": _timeline(report.week_ending, forecast, target),
        "moved": _moved_text(targets),
    }
    return {"completed": completed, "week": week, "rate": rate_tile, "forecast": forecast_tile}


def summarise_statuses(weeks: list[StatusWeek]) -> str:
    """The streak ending at the last week ("Amber for 3 weeks") and the Red weeks shown ("Red once, on 9 Oct")."""
    if not any(w.status for w in weeks):
        return "No statuses yet."
    parts = []
    streak, last = 0, weeks[-1].status
    if last:
        for w in reversed(weeks):
            if w.status != last:
                break
            streak += 1
        parts.append(f"{last} for {streak} week{'' if streak == 1 else 's'}")
    # The Red weeks outside the streak ending at the last week (all of them when the streak is not Red).
    reds = [w for w in weeks[: len(weeks) - streak] if w.status == "Red"]
    if reds:
        before = " before" if last == "Red" else ""
        if len(reds) > 2:
            parts.append(f"Red {len(reds)} times{before}")
        else:
            when = " and ".join(_short(w.week_ending) for w in reds)
            parts.append(f"Red {'once' if len(reds) == 1 else 'twice'}{before}, on {when}")
    return "; ".join(parts) + "." if parts else "No status for the report week."


def _status_weeks(session: Session, report: Report) -> list[StatusWeek]:
    shown = [r.week_ending for r in report.rows if r.week_ending <= report.week_ending][-STRIP_WEEKS:]
    saved = dict(
        session.execute(
            select(ReportInput.week_ending, ReportInput.status).where(
                ReportInput.tracker_id == report.tracker.id, ReportInput.week_ending.in_(shown)
            )
        ).all()
    )
    return [StatusWeek(week, saved.get(week) or None) for week in shown]


def _risk_lines(report: Report, on: date) -> list[RiskLine]:
    """The top risks, with how far past due each is on ``on`` (the report week's end, or today while it runs)."""
    places = {g.group_id: g.name for g in report.groups}
    lines = []
    for risk in report.top_risks:
        due = risk.target_date
        past = due is not None and due < on
        if due is None:
            text = "No due date"
        elif past:
            text = f"{_days((on - due).days)} past {_short(due)}"
        else:
            text = f"Due {_short(due)}"
        lines.append(
            RiskLine(
                risk.ref, risk.description or "", risk.rag, risk.owner_role or "", places.get(risk.group_id), text, past
            )
        )
    return lines


def _location_lines(report: Report) -> list[LocationLine]:
    live = [g for g in report.groups if not g.retired]
    live.sort(key=lambda g: (g.pct_complete is None, g.pct_complete or 0, g.name))
    lines = []
    for g in live:
        note = [f"{fmt_num(g.remaining)} left"]
        if g.starting_completed:
            note.append(f"{fmt_num(g.starting_completed)} done before the first week")
        if g.ready_not_complete:
            note.append(f"{fmt_num(g.ready_not_complete)} ready, not yet complete")
        if g.planned_completion:
            note.append(f"planned {_short(g.planned_completion)}")
        lines.append(LocationLine(g, " · ".join(note)))
    return lines


def target_lines(targets: list[TargetEntry]) -> list[TargetLine]:
    """The "Target date changes" rows: what happened, when, by how many days, and why."""
    lines = []
    for entry in targets:
        on = _short(entry.changed_on) if entry.changed_on else ""
        if not on:
            text = "In place before changes were recorded."
        elif entry.kind == "set":
            text = f"Set on {on}" + (f": {entry.reason}." if entry.reason else ".")
        else:
            if entry.kind == "removed":
                text = f"Target removed on {on}"
            else:
                days = entry.days or 0
                text = f"Moved on {on}, {_days(abs(days))} {'later' if days > 0 else 'earlier'}"
            text += f": {entry.reason}." if entry.reason else ". No reason given."
        date_text = _short(entry.date) if entry.date else "No target"
        lines.append(TargetLine(entry.number, entry.current, date_text, text))
    return lines


def target_note(targets: list[TargetEntry]) -> str:
    """ "moved twice, 14 days later than first set"; empty when the date never moved from one date to another."""
    count = moves(targets)
    dated = [e for e in targets if e.date is not None]
    if count == 0 or not dated:
        return ""
    times = {1: "once", 2: "twice"}.get(count, f"{count} times")
    note = f"moved {times}"
    if targets[-1].date is None:
        return note
    shift = (dated[-1].date - dated[0].date).days
    if shift == 0:
        return f"{note}, back to the date first set"
    return f"{note}, {_days(abs(shift))} {'later' if shift > 0 else 'earlier'} than first set"


def build_dashboard(session: Session, report: Report, today: date) -> Dashboard:
    tracker = report.tracker
    targets = target_history(session, tracker, report.week_ending)
    target = targets[-1].date if targets else None  # the target in force at the end of the report week
    inputs = report.inputs
    written_by = written_on = None
    if inputs is not None:
        author = session.get(User, inputs.prepared_by) if inputs.prepared_by else None
        written_by = author.full_name if author else None
        written_on = inputs.updated_at.astimezone(ZoneInfo(tracker.send_timezone)).date()
    status = inputs.status if inputs else None
    statuses = _status_weeks(session, report)
    return Dashboard(
        target=target,
        targets=targets,
        answer=answer_sentence(report.headline, target, _behind_plan(report)),
        tone=TONES.get(status, "none"),
        needed=(inputs.decisions or None) if inputs else None,
        written_by=written_by,
        written_on=written_on,
        tiles=build_tiles(report, target, targets),
        statuses=statuses,
        status_summary=summarise_statuses(statuses),
        locations=_location_lines(report),
        risks=_risk_lines(report, min(today, report.week_ending)),
        chart_subtitle=unit_title(tracker.unit_label or "units", "left to do, by week ending"),
        target_lines=target_lines(targets) if shows_history(targets) else [],
        target_note=target_note(targets),
    )
