"""Report charts rendered with matplotlib's object-oriented API (no pyplot, so safe under threaded workers).

Plan is a dashed grey line, actual a solid blue line and forecast a dotted amber line. Every chart renders with empty
data and then shows a "No data yet" note.
"""

from __future__ import annotations

from datetime import date
from io import BytesIO

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.dates import DateFormatter
from matplotlib.figure import Figure

from ..engine.calc import COMPLETE, WeekRow

PLAN = "#888888"
ACTUAL = "#2c7be5"
FORECAST = "#d39e00"
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


def actual_series(rows: list[WeekRow], attr: str) -> tuple[list[date], list[float]]:
    """The actual line: completed weeks only, so that a part-week figure never draws a flat segment."""
    return _series(rows, attr, include=lambda r: r.state == COMPLETE)


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


def weekly_chart(rows: list[WeekRow], fmt: str = "svg") -> bytes:
    """Weekly actual (blue bars) against the weekly target (dashed grey)."""
    fig, ax = _new_figure("Weekly actual against target")
    tx, ty = _series(rows, "target")
    bx, by = _series(rows, "actual")
    if bx:
        ax.bar(bx, by, width=5, color=ACTUAL, label="Actual")
    if tx:
        ax.plot(tx, ty, color=PLAN, linestyle="--", linewidth=1.6, marker="o", markersize=3, label="Target")
    return _finish(fig, ax, bool(tx or bx), fmt)


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
