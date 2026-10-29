"""The JSON payload behind the interactive charts on the live report page."""

from __future__ import annotations

from ..engine.calc import IN_PROGRESS, WeekRow
from .charts import PALETTE, chart_series


def chart_payload(tracker, rows: list[WeekRow]) -> dict:
    """Weeks, series and colours for the browser charts; the same values the report pictures draw."""
    return {
        "unit_label": tracker.unit_label,
        "palette": PALETTE,
        "weeks": [row.week_ending.isoformat() for row in rows],
        "series": chart_series(rows),
        # The week in progress has a part-week actual, drawn paler.
        "in_progress": [row.state == IN_PROGRESS for row in rows],
    }
