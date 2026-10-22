"""The report model: one tracker at one week-ending, built from the engine and the stored weekly inputs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import NamedTuple

from sqlalchemy import select

from ..engine.calc import GroupPosition, Headline, WeekRow, build_headline, build_week_rows, group_positions
from ..engine.weeks import week_endings
from ..models import ReportInput, Risk, Tracker
from ..trackers.views import load_engine_inputs
from .charts import cumulative_chart, remaining_chart, weekly_chart

RAG_ORDER = {"Red": 0, "Amber": 1, "Green": 2}
TOP_RISKS = 3


@dataclass
class Report:
    tracker: Tracker
    week_ending: date
    as_of: date
    in_progress: bool
    rows: list[WeekRow]
    headline: Headline
    groups: list[GroupPosition]
    top_risks: list[Risk]
    open_risks: int
    red_risks: int
    inputs: ReportInput | None
    charts: dict[str, bytes]


class Position(NamedTuple):
    """The engine output for one tracker at one report week."""

    week_ending: date
    as_of: date
    rows: list[WeekRow]
    groups: list[GroupPosition]
    headline: Headline


def default_report_week(tracker: Tracker, today: date) -> date:
    """The latest week-ending on or before ``today``, or the first week if none has passed."""
    weeks = week_endings(tracker.first_week_ending, tracker.last_week_ending)
    passed = [w for w in weeks if w <= today]
    return passed[-1] if passed else weeks[0]


def compute_position(session, tracker: Tracker, week_ending: date | None, today: date) -> Position:
    """Run the engine for ``week_ending`` (default: the default report week); entries are cut off at ``as_of``."""
    if week_ending is None:
        week_ending = default_report_week(tracker, today)
    as_of = min(week_ending, today)
    weeks, targets, actuals, group_inputs, entry_totals = load_engine_inputs(session, tracker, as_of)
    positions = group_positions(group_inputs, entry_totals)
    rows = build_week_rows(
        weeks,
        targets,
        actuals,
        sum(p.baseline for p in positions),
        tracker.completed_before_first,
        tracker.moving_average_weeks,
        as_of,
        tracker.week_ending_weekday,
    )
    headline = build_headline(rows, positions, tracker.completed_before_first, tracker.target_completion, week_ending)
    return Position(week_ending, as_of, rows, positions, headline)


def select_top_risks(risks, limit: int = TOP_RISKS) -> list:
    """Open risks ordered by RAG (Red, Amber, Green, none), then target date (none last), then reference."""
    live = [r for r in risks if r.status != "Closed"]
    live.sort(
        key=lambda r: (
            RAG_ORDER.get(r.rag, len(RAG_ORDER)),
            r.target_date is None,
            r.target_date or date.max,
            r.ref,
        )
    )
    return live[:limit]


def build_report(session, tracker: Tracker, week_ending: date | None, today: date, chart_format: str = "svg") -> Report:
    position = compute_position(session, tracker, week_ending, today)
    risks = list(session.scalars(select(Risk).where(Risk.tracker_id == tracker.id, Risk.status != "Closed")))
    charts = {
        "remaining": remaining_chart(position.rows, tracker.unit_label, chart_format),
        "weekly": weekly_chart(position.rows, chart_format),
        "cumulative": cumulative_chart(position.rows, chart_format),
    }
    return Report(
        tracker=tracker,
        week_ending=position.week_ending,
        as_of=position.as_of,
        in_progress=position.week_ending > today,
        rows=position.rows,
        headline=position.headline,
        groups=position.groups,
        top_risks=select_top_risks(risks),
        open_risks=len(risks),
        red_risks=sum(1 for r in risks if r.rag == "Red"),
        inputs=session.get(ReportInput, (tracker.id, position.week_ending)),
        charts=charts,
    )
