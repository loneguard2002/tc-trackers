"""Weekly figures, moving-average forecast and headline numbers. Pure functions, standard library only.

Percentages are fractions between 0 and 1. Nothing is rounded here; presentation rounds.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from math import ceil, floor

from tracker.engine.weeks import in_progress_week

COMPLETE = "complete"
IN_PROGRESS = "in_progress"
FUTURE = "future"


@dataclass(frozen=True)
class WeekRow:
    week_ending: date
    target: int | None
    actual: int | None
    variance: int | None
    cum_target: int | None
    cum_actual: int | None
    planned_remaining: int | None
    actual_remaining: int | None
    pct_complete: float | None
    moving_average: float | None
    forecast_remaining: float | None
    state: str


@dataclass(frozen=True)
class GroupInput:
    group_id: int
    name: str
    baseline: int
    starting_completed: int
    ready_not_complete: int
    planned_completion: date | None
    rag: str | None
    comment: str | None
    retired: bool


@dataclass(frozen=True)
class GroupPosition:
    group_id: int
    name: str
    baseline: int
    deployed: int
    ready_not_complete: int
    remaining: int
    pct_complete: float | None
    planned_completion: date | None
    rag: str | None
    comment: str | None
    retired: bool


@dataclass(frozen=True)
class Headline:
    total_scope: int
    completed: int
    pct_complete: float | None
    remaining: int
    report_week: date
    forecast_based_on: date | None
    forecast_rate: float | None
    planned_completion: date | None
    forecast_completion: date | None
    target_completion: date | None
    weeks_left: int | None
    required_rate: float | None
    forecast_vs_target_days: int | None
    this_week_actual: int | None
    this_week_target: int | None
    next_week_target: int | None
    totals_check_ok: bool
    verdict: str


def _plural(n: int) -> str:
    return f"{n} week" if n == 1 else f"{n} weeks"


def build_week_rows(
    weeks: list[date],
    targets: dict[date, int | None],
    actuals: dict[date, int],
    total_scope: int,
    completed_before_first: int,
    ma_weeks: int,
    as_of: date,
    weekday: int,
) -> list[WeekRow]:
    in_progress = in_progress_week(as_of, weekday)
    rows: list[WeekRow] = []
    cum_target: int | None = completed_before_first
    cum_actual: int | None = completed_before_first
    complete_actuals: list[int] = []
    last_rate: float | None = None
    last_forecast: float | None = None
    seen_complete = False

    for week in weeks:
        if week <= as_of:
            state = COMPLETE
            actual: int | None = actuals.get(week, 0)
        elif week == in_progress:
            state = IN_PROGRESS
            actual = actuals.get(week, 0)
        else:
            state = FUTURE
            actual = None

        target = targets.get(week)
        variance = actual - target if actual is not None and target is not None else None

        cum_target = cum_target + target if cum_target is not None and target is not None else None
        cum_actual = cum_actual + actual if cum_actual is not None and actual is not None else None
        planned_remaining = total_scope - cum_target if cum_target is not None else None
        actual_remaining = total_scope - cum_actual if cum_actual is not None else None
        pct = cum_actual / total_scope if cum_actual is not None and total_scope else None

        moving_average: float | None = None
        forecast: float | None
        if state == COMPLETE:
            complete_actuals.append(actual)  # type: ignore[arg-type]
            window = complete_actuals[-max(1, min(ma_weeks, len(complete_actuals))) :]
            moving_average = sum(window) / len(window)
            last_rate = moving_average
            forecast = float(actual_remaining) if actual_remaining is not None else None
            last_forecast = forecast
            seen_complete = True
        elif seen_complete and last_rate is not None and last_forecast is not None:
            forecast = max(0.0, last_forecast - last_rate)
            last_forecast = forecast
        else:
            forecast = None

        rows.append(
            WeekRow(
                week_ending=week,
                target=target,
                actual=actual,
                variance=variance,
                cum_target=cum_target,
                cum_actual=cum_actual,
                planned_remaining=planned_remaining,
                actual_remaining=actual_remaining,
                pct_complete=pct,
                moving_average=moving_average,
                forecast_remaining=forecast,
                state=state,
            )
        )
    return rows


def group_positions(groups: list[GroupInput], entry_totals: dict[int, int]) -> list[GroupPosition]:
    positions = []
    for g in groups:
        deployed = g.starting_completed + entry_totals.get(g.group_id, 0)
        positions.append(
            GroupPosition(
                group_id=g.group_id,
                name=g.name,
                baseline=g.baseline,
                deployed=deployed,
                ready_not_complete=g.ready_not_complete,
                remaining=g.baseline - deployed,
                pct_complete=deployed / g.baseline if g.baseline else None,
                planned_completion=g.planned_completion,
                rag=g.rag,
                comment=g.comment,
                retired=g.retired,
            )
        )
    return positions


def _verdict(remaining: int, total_scope: int, forecast: date | None, target: date | None) -> str:
    # An empty scope is not "complete": there is nothing to forecast.
    if total_scope > 0 and remaining <= 0:
        return "Complete"
    if forecast is None:
        return "No forecast yet"
    if target is None:
        return "No target set"
    days = (forecast - target).days
    if days > 0:
        return f"Forecast {_plural(ceil(days / 7))} behind target"
    if days <= -7:
        return f"Forecast {_plural(floor(-days / 7))} ahead of target"
    return "On track for target"


def build_headline(
    rows: list[WeekRow],
    positions: list[GroupPosition],
    completed_before_first: int,
    target_completion: date | None,
    report_week: date,
) -> Headline:
    """Build the headline figures.

    Precondition: the group positions' ``deployed`` figures (from ``entry_totals``) must cover entries with
    ``entry_date <= as_of``, the same cut-off used for the rows' actuals.
    """
    total_scope = sum(p.baseline for p in positions)
    completed = sum(p.deployed for p in positions)
    remaining = total_scope - completed

    basis = None
    for row in rows:
        if row.state == COMPLETE and row.week_ending <= report_week:
            basis = row
    # Complete or in-progress rows both reflect entries up to ``as_of``, so either may anchor the totals check.
    check_row = None
    for row in rows:
        if row.week_ending <= report_week and row.cum_actual is not None:
            check_row = row

    rate = basis.moving_average if basis is not None else None
    forecast_completion: date | None = None
    if basis is not None and basis.actual_remaining is not None:
        if basis.actual_remaining <= 0:
            forecast_completion = basis.week_ending
        elif rate is not None and rate > 0:
            forecast_completion = basis.week_ending + timedelta(days=ceil(basis.actual_remaining / rate) * 7)

    planned_completion = next(
        (r.week_ending for r in rows if r.planned_remaining is not None and r.planned_remaining <= 0), None
    )

    weeks_left: int | None = None
    required_rate: float | None = None
    if target_completion is not None:
        weeks_left = max(0, ceil((target_completion - report_week).days / 7))
        if weeks_left > 0:
            required_rate = remaining / weeks_left

    days_vs_target = (
        (forecast_completion - target_completion).days
        if forecast_completion is not None and target_completion is not None
        else None
    )

    by_week = {r.week_ending: r for r in rows}
    this_week = by_week.get(report_week)
    next_week = by_week.get(report_week + timedelta(days=7))

    expected_completed = check_row.cum_actual if check_row is not None else completed_before_first

    return Headline(
        total_scope=total_scope,
        completed=completed,
        pct_complete=completed / total_scope if total_scope else None,
        remaining=remaining,
        report_week=report_week,
        forecast_based_on=basis.week_ending if basis is not None else None,
        forecast_rate=rate,
        planned_completion=planned_completion,
        forecast_completion=forecast_completion,
        target_completion=target_completion,
        weeks_left=weeks_left,
        required_rate=required_rate,
        forecast_vs_target_days=days_vs_target,
        this_week_actual=this_week.actual if this_week is not None else None,
        this_week_target=this_week.target if this_week is not None else None,
        next_week_target=next_week.target if next_week is not None else None,
        totals_check_ok=completed == expected_completed,
        verdict=_verdict(remaining, total_scope, forecast_completion, target_completion),
    )
