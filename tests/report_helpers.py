"""Database-free report fixtures shared by the report and render tests."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from tracker.engine.calc import WeekRow, build_week_rows
from tracker.report.charts import cumulative_chart, remaining_chart, weekly_chart

FRIDAY = 4
WEEKS = [date(2026, 9, 4), date(2026, 9, 11), date(2026, 9, 18), date(2026, 9, 25)]


def sample_rows() -> list[WeekRow]:
    return build_week_rows(
        WEEKS,
        {w: 10 for w in WEEKS},
        {WEEKS[0]: 8, WEEKS[1]: 12},
        100,
        0,
        3,
        date(2026, 9, 12),
        FRIDAY,
    )


def synthetic_report(in_progress: bool = False):
    from tracker.engine.calc import GroupInput, build_headline, group_positions
    from tracker.report.build import Report

    rows = sample_rows()
    positions = group_positions([GroupInput(1, "Site A", 100, 0, 0, None, "Red", "c", False)], {1: 20})
    headline = build_headline(rows, positions, 0, date(2026, 12, 25), WEEKS[1])
    tracker = SimpleNamespace(
        id=1, name="Stub tracker", unit_label="devices", group_label="Site", moving_average_weeks=3, status="active"
    )
    risk = SimpleNamespace(
        ref="R1", description="d", owner_role="Programme Lead", status="In progress", rag="Red", target_date=None
    )
    charts = {
        "remaining": remaining_chart(rows, "devices"),
        "weekly": weekly_chart(rows),
        "cumulative": cumulative_chart(rows),
    }
    report = Report(tracker, WEEKS[1], WEEKS[1], in_progress, rows, headline, positions, [risk], 1, 1, None, charts)
    return report, tracker
