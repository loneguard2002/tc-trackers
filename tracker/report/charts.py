"""Report charts rendered with matplotlib's object-oriented API (no pyplot, so safe under threaded workers).

Plan is a dashed grey line, actual a solid blue line and forecast a dotted amber line. Every chart renders with empty
data and then shows a "No data yet" note.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
from io import BytesIO

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.dates import DateFormatter
from matplotlib.figure import Figure
from matplotlib.ticker import MultipleLocator

from ..engine.calc import COMPLETE, IN_PROGRESS, WeekRow
from ..trackers.targets import TargetEntry, shows_history

PLAN = "#888888"
ACTUAL = "#2c7be5"
FORECAST = "#d39e00"
TARGET_BAR = "#b9c3d3"
DONE_BAR = "#2f9e76"
PALETTE = {"plan": PLAN, "actual": ACTUAL, "forecast": FORECAST}
# The Status at a glance chart's lines (always light: the picture is white; the live chart has a dark set too).
GLANCE_ACTUAL = "#1260d0"
GLANCE_PLAN = "#008f82"
GLANCE_FORECAST = "#c27a00"
GLANCE_INK = "#14213d"
FORMATS = {"svg": "svg", "png": "png"}
SIZE = (7.0, 3.2)


def _series(rows: list[WeekRow], attr: str, include=None) -> tuple[list[date], list[float]]:
    xs: list[date] = []
    ys: list[float] = []
    for row in rows:
        value = getattr(row, attr)
        if value is None or (include is not None and not include(row)):
            continue
        xs.append(row.week_ending)
        ys.append(value)
    return xs, ys


def actual_series(rows: list[WeekRow], attr: str, upto: date | None = None) -> tuple[list[date], list[float]]:
    """The actual line: completed weeks only, so that a part-week figure never draws a flat segment."""
    return _series(rows, attr, include=lambda r: r.state == COMPLETE and (upto is None or r.week_ending <= upto))


def chart_series(rows: list[WeekRow]) -> dict[str, list[float | None]]:
    """The values each chart draws, one per row (``None`` where no point is drawn), for the browser charts.

    The inclusion rules match the matplotlib charts below: actual remaining and cumulative actual cover completed weeks
    only, and the forecast runs from the last completed week and needs at least two points.
    """

    def column(attr: str, include=None) -> list[float | None]:
        return [getattr(r, attr) if include is None or include(r) else None for r in rows]

    def complete(row: WeekRow) -> bool:
        return row.state == COMPLETE

    last_complete = max((r.week_ending for r in rows if r.moving_average is not None), default=None)
    forecast = column(
        "forecast_remaining", include=lambda r: last_complete is not None and r.week_ending >= last_complete
    )
    if sum(v is not None for v in forecast) < 2:
        forecast = [None] * len(rows)
    return {
        "planned_remaining": column("planned_remaining"),
        "actual_remaining": column("actual_remaining", complete),
        "forecast_remaining": forecast,
        "target": column("target"),
        "actual": column("actual"),
        "cum_target": column("cum_target"),
        "cum_actual": column("cum_actual", complete),
    }


def _render(fig: Figure, fmt: str) -> bytes:
    if fmt not in FORMATS:
        raise ValueError(f"Unsupported chart format: {fmt!r}")
    FigureCanvasAgg(fig)
    buffer = BytesIO()
    kwargs = {"dpi": 150} if fmt == "png" else {}
    fig.savefig(buffer, format=FORMATS[fmt], facecolor="white", **kwargs)
    return buffer.getvalue()


def _new_figure(title: str, ylabel: str = ""):
    fig = Figure(figsize=SIZE, layout="constrained")
    ax = fig.add_subplot()
    ax.set_title(title, fontsize=10, loc="left")
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=8)
    ax.tick_params(labelsize=8)
    ax.grid(True, alpha=0.25)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    return fig, ax


def _finish(fig: Figure, ax, has_data: bool, fmt: str) -> bytes:
    if has_data:
        ax.xaxis.set_major_formatter(DateFormatter("%d %b"))
        ax.legend(fontsize=8, frameon=False, loc="best")
    else:
        ax.set_xticks([])
        ax.set_yticks([])
        ax.text(0.5, 0.5, "No data yet", transform=ax.transAxes, ha="center", va="center", fontsize=12, color=PLAN)
    return _render(fig, fmt)


def remaining_chart(rows: list[WeekRow], unit_label: str, fmt: str = "svg") -> bytes:
    """Remaining against plan: planned (dashed grey), actual (solid blue) and forecast (dotted amber)."""
    fig, ax = _new_figure("Remaining", unit_label)
    px, py = _series(rows, "planned_remaining")
    ax_, ay = actual_series(rows, "actual_remaining")
    # The forecast starts from the last completed week, which carries the actual remaining as its first point.
    last_complete = max((r.week_ending for r in rows if r.moving_average is not None), default=None)
    fx, fy = _series(
        rows, "forecast_remaining", include=lambda r: last_complete is not None and r.week_ending >= last_complete
    )
    if px:
        ax.plot(px, py, color=PLAN, linestyle="--", linewidth=1.6, label="Plan")
    if ax_:
        ax.plot(ax_, ay, color=ACTUAL, linestyle="-", linewidth=2.2, label="Actual")
    if len(fx) > 1:
        ax.plot(fx, fy, color=FORECAST, linestyle=":", linewidth=2.2, label="Forecast")
    return _finish(fig, ax, bool(px or ax_ or len(fx) > 1), fmt)


def glance_x_range(weeks: Sequence[date], targets: Sequence[date], forecast_end: date | None) -> tuple[date, date]:
    """The x-axis span, on the weekly grid, from the first week to the latest of the last week, the forecast end and
    every target (and back to the earliest target if that is before the first week), so no target line is clipped."""
    dates = [*weeks, *targets, *([forecast_end] if forecast_end else [])]
    anchor = weeks[0] if weeks else min(dates)
    before = -(-(anchor - min(dates)).days // 7)  # whole weeks, rounded up
    after = -(-(max(dates) - anchor).days // 7)
    return anchor - timedelta(days=7 * before), anchor + timedelta(days=7 * after)


def nice_step(top: float) -> int:
    """A y-axis step from 10, 20, 25, 50, 100, 200, ... that gives at most six ticks up to ``top``."""
    magnitude = 10
    while True:
        for factor in (1, 2, 2.5, 5):
            step = int(factor * magnitude)
            if -(-top // step) <= 6:
                return step
        magnitude *= 10


def week_label(report_week: date, in_progress: bool) -> str:
    """The report-week marker: "This week, ending 16 Oct" while the week is in progress, else "Week ending 16 Oct"."""
    return f"{'This week, ending' if in_progress else 'Week ending'} {report_week.day} {report_week:%b}"


def target_label_text(entry: TargetEntry, numbered: bool) -> str:
    """An earlier target is just its number; the current one says "Target 18 Dec", behind its number when numbered."""
    if entry.date is None or not entry.current:
        return str(entry.number)
    words = f"Target {entry.date.day} {entry.date:%b}"
    return f"{entry.number}  {words}" if numbered else words


def glance_plan_points(rows: list[WeekRow]) -> tuple[list[date], list[float]]:
    """The plan line: remaining never below none left, and nothing after the first week it reaches it."""
    xs: list[date] = []
    ys: list[float] = []
    for x, y in zip(*_series(rows, "planned_remaining")):
        if ys and ys[-1] <= 0:
            break
        xs.append(x)
        ys.append(max(0, y))
    return xs, ys


def _day_label(day: date, first_of_month: bool) -> str:
    return f"{day.day}\n{day:%b}" if first_of_month else str(day.day)


def remaining_glance_chart(
    rows: list[WeekRow],
    unit_label: str,
    report_week: date,
    targets: Sequence[TargetEntry],
    forecast_end: date | None,
    fmt: str = "svg",
) -> bytes:
    """The Status at a glance Remaining chart: actual (solid, a dot per week), plan (dashed, a ring per week) and
    forecast (dotted) down to none left, the report week, and a dashed line per target (earlier ones faint, numbered).

    Every artist has a ``gid`` (``glance-actual``, ``glance-target-2``, ...) so the SVG can be inspected."""
    fig, ax = _new_figure("", unit_label)
    px, py = glance_plan_points(rows)
    ax_, ay = actual_series(rows, "actual_remaining", report_week)
    if not (px or ax_):
        return _finish(fig, ax, False, fmt)
    dated = [t for t in targets if t.date is not None]
    low, high = glance_x_range([r.week_ending for r in rows], [t.date for t in dated], forecast_end)
    ax.set_xlim(low - timedelta(days=2), high + timedelta(days=2))
    if px:
        ax.plot(
            px,
            py,
            color=GLANCE_PLAN,
            linestyle="--",
            linewidth=1.6,
            marker="o",
            markersize=5,
            markerfacecolor="white",
            markeredgewidth=1.4,
            label="Plan",
            gid="glance-plan",
        )
    if ax_:
        ax.plot(
            ax_,
            ay,
            color=GLANCE_ACTUAL,
            linestyle="-",
            linewidth=2.2,
            marker="o",
            markersize=4.5,
            label="Actual",
            gid="glance-actual",
        )
        if forecast_end and forecast_end > ax_[-1] and ay[-1] > 0:
            ax.plot(
                [ax_[-1], forecast_end],
                [ay[-1], 0],
                color=GLANCE_FORECAST,
                linestyle=":",
                linewidth=2.2,
                label="Forecast",
                gid="glance-forecast",
            )
    top = max([*py, *ay, 1])
    step = nice_step(top)
    ax.set_ylim(0, top * 1.12)
    ax.yaxis.set_major_locator(MultipleLocator(step))
    ax.axvline(report_week, color=GLANCE_INK, linewidth=1, alpha=0.6, gid="glance-report-week")
    ax.annotate(
        week_label(report_week, any(r.week_ending == report_week and r.state == IN_PROGRESS for r in rows)),
        (report_week, top * 1.12),
        fontsize=7,
        ha="center",
        va="bottom",
        annotation_clip=False,
        color=GLANCE_INK,
    )
    numbered = shows_history(targets)
    for entry in dated:
        faint = not entry.current
        ax.axvline(
            entry.date,
            color=GLANCE_INK,
            linestyle="--",
            linewidth=1.2,
            alpha=0.35 if faint else 0.9,
            gid=f"glance-target-{entry.number}",
        )
        text = target_label_text(entry, numbered)
        label = ax.annotate(
            text,
            (entry.date, top * 1.12),
            fontsize=7,
            ha="center",
            va="bottom",
            annotation_clip=False,
            color=GLANCE_INK if entry.current else "#5d6b83",
            bbox={
                "boxstyle": "circle,pad=0.25" if faint else "round,pad=0.25",
                "fc": "white",
                "ec": GLANCE_INK,
                "alpha": 1,
            },
        )
        label.set_gid(f"glance-target-label-{entry.number}")
    weeks = [low + timedelta(days=7 * i) for i in range(((high - low).days // 7) + 1)]
    ticks, labels, last_month = [], [], None
    for week in weeks:
        ticks.append(week)
        labels.append(_day_label(week, week.month != last_month))
        last_month = week.month
    ax.set_xticks(ticks, labels, fontsize=7)
    ax.legend(fontsize=8, frameon=False, loc="upper right", ncols=3)
    return _render(fig, fmt)


def weekly_chart(rows: list[WeekRow], fmt: str = "svg") -> bytes:
    """Weekly actual (blue bars; the week in progress paler) against the weekly target (dashed grey)."""
    fig, ax = _new_figure("Weekly actual against target")
    tx, ty = _series(rows, "target")
    bx, by = _series(rows, "actual", include=lambda r: r.state != IN_PROGRESS)
    px, py = _series(rows, "actual", include=lambda r: r.state == IN_PROGRESS)
    if bx:
        ax.bar(bx, by, width=5, color=ACTUAL, label="Actual")
    if px:
        ax.bar(px, py, width=5, color=ACTUAL, alpha=0.4, label="This week so far")
    if tx:
        ax.plot(tx, ty, color=PLAN, linestyle="--", linewidth=1.6, marker="o", markersize=3, label="Target")
    return _finish(fig, ax, bool(tx or bx or px), fmt)


def cumulative_chart(rows: list[WeekRow], fmt: str = "svg") -> bytes:
    """Cumulative target (dashed grey) against cumulative actual (solid blue)."""
    fig, ax = _new_figure("Cumulative completed")
    px, py = _series(rows, "cum_target")
    ax_, ay = actual_series(rows, "cum_actual")
    if px:
        ax.plot(px, py, color=PLAN, linestyle="--", linewidth=1.6, label="Plan")
    if ax_:
        ax.plot(ax_, ay, color=ACTUAL, linestyle="-", linewidth=2.2, label="Actual")
    return _finish(fig, ax, bool(px or ax_), fmt)


def unit_title(unit_label: str, rest: str) -> str:
    """An axis title such as "Devices remaining": the unit with only its first letter raised ("kWh" stays "KWh",
    never "Kwh"), or the rest alone, capitalised, without a unit."""
    unit = unit_label.strip()
    return f"{unit[:1].upper()}{unit[1:]} {rest}" if unit else rest.capitalize()


def email_chart(rows: list[WeekRow], unit_label: str, report_week: date, fmt: str = "png") -> bytes:
    """The email's chart, both axes titled. Left axis: remaining against plan (the remaining chart's lines). Right axis:
    each week's target (grey bars) and what was done (green bars) up to the report week, and next week's target."""
    fig, ax = _new_figure("", unit_title(unit_label, "remaining"))
    ax.set_xlabel("Week ending", fontsize=8)
    bars = ax.twinx()
    bars.set_ylabel(unit_title(unit_label, "per week"), fontsize=8)
    bars.tick_params(labelsize=8)
    bars.spines["top"].set_visible(False)
    ax.set_zorder(bars.get_zorder() + 1)  # the lines in front of the bars
    ax.patch.set_visible(False)
    px, py = _series(rows, "planned_remaining")
    ax_, ay = actual_series(rows, "actual_remaining")
    last_complete = max((r.week_ending for r in rows if r.moving_average is not None), default=None)
    fx, fy = _series(
        rows, "forecast_remaining", include=lambda r: last_complete is not None and r.week_ending >= last_complete
    )
    tx, ty = _series(rows, "target", include=lambda r: r.week_ending <= report_week + timedelta(days=7))
    dx, dy = _series(rows, "actual", include=lambda r: r.week_ending <= report_week)
    if tx:
        bars.bar([x - timedelta(days=1.5) for x in tx], ty, width=3, color=TARGET_BAR, label="Weekly target")
    if dx:
        bars.bar([x + timedelta(days=1.5) for x in dx], dy, width=3, color=DONE_BAR, label="Done that week")
    if max(ty + dy, default=0) > 0:
        bars.set_ylim(0, max(ty + dy) * 3)  # the bars keep to the lower third, under the lines
    if px:
        ax.plot(px, py, color=PLAN, linestyle="--", linewidth=1.6, label="Plan")
    if ax_:
        ax.plot(ax_, ay, color=ACTUAL, linestyle="-", linewidth=2.2, label="Actual")
    if len(fx) > 1:
        ax.plot(fx, fy, color=FORECAST, linestyle=":", linewidth=2.2, label="Forecast")
    has_data = bool(px or ax_ or len(fx) > 1 or tx or dx)
    if not has_data:
        bars.set_yticks([])
        bars.set_ylabel("")
        return _finish(fig, ax, False, fmt)
    ax.xaxis.set_major_formatter(DateFormatter("%d %b"))
    lines, labels = ax.get_legend_handles_labels()
    bar_lines, bar_labels = bars.get_legend_handles_labels()
    ax.legend(lines + bar_lines, labels + bar_labels, fontsize=7, frameon=False, loc="upper right", ncols=2)
    return _render(fig, fmt)
