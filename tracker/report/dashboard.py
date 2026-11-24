"""The data behind the report's "Status at a glance" view: the answer card now; tiles, strip and risks follow."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from ..engine.calc import Headline
from ..formatting import fmt_num
from ..models import User
from ..trackers.targets import TargetEntry, target_as_of, target_history
from .build import Report

TONES = {"Red": "red", "Amber": "amber", "Green": "green"}


@dataclass(frozen=True)
class StatusWeek:
    week_ending: date
    status: str | None


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
    locations: list = field(default_factory=list)
    risks: list = field(default_factory=list)


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


def _behind_plan(report: Report) -> int | None:
    row = next((r for r in report.rows if r.week_ending == report.week_ending), None)
    if row is None or row.cum_target is None or row.cum_actual is None:
        return None
    return row.cum_target - row.cum_actual


def build_dashboard(session: Session, report: Report, today: date) -> Dashboard:
    tracker = report.tracker
    target = target_as_of(session, tracker, report.week_ending)
    inputs = report.inputs
    written_by = written_on = None
    if inputs is not None:
        author = session.get(User, inputs.prepared_by) if inputs.prepared_by else None
        written_by = author.full_name if author else None
        written_on = inputs.updated_at.astimezone(ZoneInfo(tracker.send_timezone)).date()
    status = inputs.status if inputs else None
    return Dashboard(
        target=target,
        targets=target_history(session, tracker, report.week_ending),
        answer=answer_sentence(report.headline, target, _behind_plan(report)),
        tone=TONES.get(status, "none"),
        needed=(inputs.decisions or None) if inputs else None,
        written_by=written_by,
        written_on=written_on,
    )
