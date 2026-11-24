"""The JSON payload behind the interactive charts on the live report page."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from ..engine.calc import IN_PROGRESS, WeekRow
from ..trackers.targets import TargetEntry
from .charts import PALETTE, chart_series


def chart_payload(
    tracker,
    rows: list[WeekRow],
    report_week: date | None = None,
    targets: Iterable[TargetEntry] = (),
    forecast_end: date | None = None,
) -> dict:
    """Weeks, series and colours for the browser charts; the same values the report pictures draw.

    ``report_week``, ``targets`` (the target changes made by then; a removed target has no date, so no line, but keeps
    its number) and ``forecast_end`` serve the Status at a glance chart; the classic charts ignore them.
    """
    return {
        "unit_label": tracker.unit_label,
        "palette": PALETTE,
        "weeks": [row.week_ending.isoformat() for row in rows],
        "series": chart_series(rows),
        # The week in progress has a part-week actual, drawn paler.
        "in_progress": [row.state == IN_PROGRESS for row in rows],
        "report_week": report_week.isoformat() if report_week else None,
        "targets": [
            {"date": entry.date.isoformat(), "number": entry.number, "current": entry.current}
            for entry in targets
            if entry.date is not None
        ],
        "forecast_end": forecast_end.isoformat() if forecast_end else None,
    }
