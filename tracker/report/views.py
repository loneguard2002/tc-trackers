"""The live weekly report page (spec section 7.1)."""

from __future__ import annotations

import re
from datetime import date

from flask import Response, abort, g, jsonify, render_template, request, session

from ..auth import require_tracker_role
from ..auth.roles import ROLE_ORDER
from ..db import get_session
from ..engine.weeks import week_endings
from ..trackers.targets import target_history
from . import bp
from .build import build_report, compute_position, current_report_week
from .chart_data import chart_payload
from .charts import cumulative_chart, remaining_chart, remaining_glance_chart, weekly_chart
from .dashboard import build_dashboard
from .render import html_to_pdf, html_to_png, render_print_dashboard_html, render_print_html


def today() -> date:
    """The current date; a separate function so that tests can fix the clock."""
    return date.today()


def _requested_week(tracker) -> date | None:
    raw = request.args.get("week")
    if not raw:
        return None
    try:
        week = date.fromisoformat(raw)
    except ValueError:
        abort(400, description="The week must be a date in the form YYYY-MM-DD.")
    if week not in week_endings(tracker.first_week_ending, tracker.last_week_ending):
        abort(404)
    return week


def _report_week(tracker) -> date:
    """The requested week, or the week in progress: the page, its chart data and its downloads agree."""
    return _requested_week(tracker) or current_report_week(tracker, today())


VIEWS = ("new", "classic")
VIEW_KEY = "report_view"


def _chosen_view() -> str:
    """The view asked for with ``?view=`` (kept in the session for the next report), else the one kept, else new. The
    session is written only when the choice changes."""
    asked = request.args.get("view")
    kept = session.get(VIEW_KEY)
    chosen = asked if asked in VIEWS else kept if kept in VIEWS else "new"
    if kept != chosen:
        session[VIEW_KEY] = chosen
    return chosen


@bp.get("/trackers/<int:tracker_id>/report")
@require_tracker_role("viewer")
def view(tracker_id: int):
    tracker = g.tracker
    chosen = _chosen_view()
    # The charts come as separate images (``chart_image``), so the page does not wait for them to be drawn.
    report = build_report(get_session(), tracker, _report_week(tracker), today(), with_charts=False)
    weeks = week_endings(tracker.first_week_ending, tracker.last_week_ending)
    if chosen == "new":
        return render_template(
            "report/dashboard.html",
            tracker=tracker,
            report=report,
            dashboard=build_dashboard(get_session(), report, today()),
            # Editors of an active tracker set a location's status from the report (the location pop-up).
            can_set_locations=ROLE_ORDER[g.role] >= ROLE_ORDER["editor"] and tracker.status == "active",
            weeks=weeks,
            page_title=f"{tracker.name} report",
            current_page="trackers",
        )
    return render_template(
        "report/page.html",
        tracker=tracker,
        report=report,
        weeks=weeks,
        page_title=f"{tracker.name} report",
        current_page="trackers",
    )


# Each takes the engine position, the tracker and the target changes made by the report week.
CHARTS = {
    "remaining": lambda position, tracker, targets: remaining_chart(position.rows, tracker.unit_label),
    "weekly": lambda position, tracker, targets: weekly_chart(position.rows),
    "cumulative": lambda position, tracker, targets: cumulative_chart(position.rows),
    "remaining-glance": lambda position, tracker, targets: remaining_glance_chart(
        position.rows, tracker.unit_label, position.week_ending, targets, position.headline.forecast_completion
    ),
}


@bp.get("/trackers/<int:tracker_id>/report/chart/<name>.svg")
@require_tracker_role("viewer")
def chart_image(tracker_id: int, name: str):
    """One of the report's three pictures, for the same week as the page. The browser replaces them with interactive
    charts; they stay when JavaScript is off or the chart data cannot be loaded."""
    draw = CHARTS.get(name)
    if draw is None:
        abort(404)
    tracker = g.tracker
    position = compute_position(get_session(), tracker, _report_week(tracker), today())
    targets = target_history(get_session(), tracker, position.week_ending)
    return Response(draw(position, tracker, targets), mimetype="image/svg+xml")  # sent "no-store", like every page


@bp.get("/trackers/<int:tracker_id>/report/data.json")
@require_tracker_role("viewer")
def chart_data(tracker_id: int):
    """The weekly series behind the interactive charts, for the same week as the report page."""
    tracker = g.tracker
    position = compute_position(get_session(), tracker, _report_week(tracker), today())
    targets = target_history(get_session(), tracker, position.week_ending)
    return jsonify(
        chart_payload(tracker, position.rows, position.week_ending, targets, position.headline.forecast_completion)
    )


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "tracker"


def _print_html(tracker) -> tuple[str, date]:
    """The document to convert: the new view's layout with ``?view=new`` (its Download buttons ask for it), else the
    classic one. The choice kept for the live page is not used: a download link always says what it gives."""
    if request.args.get("view") == "new":
        session_ = get_session()
        report = build_report(session_, tracker, _report_week(tracker), today(), with_charts=False)
        dashboard = build_dashboard(session_, report, today())
        picture = remaining_glance_chart(
            report.rows, tracker.unit_label, report.week_ending, dashboard.targets, report.headline.forecast_completion
        )
        return render_print_dashboard_html(report, dashboard, picture), report.week_ending
    report = build_report(get_session(), tracker, _report_week(tracker), today())
    return render_print_html(report), report.week_ending


def _export(tracker_id: int, extension: str, convert, mimetype: str) -> Response:
    tracker = g.tracker
    html, week_ending = _print_html(tracker)
    data = convert(html)
    filename = f"{_slug(tracker.name)}-week-ending-{week_ending.isoformat()}.{extension}"
    response = Response(data, mimetype=mimetype)
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@bp.get("/trackers/<int:tracker_id>/report.pdf")
@require_tracker_role("viewer")
def export_pdf(tracker_id: int):
    return _export(tracker_id, "pdf", html_to_pdf, "application/pdf")


@bp.get("/trackers/<int:tracker_id>/report.png")
@require_tracker_role("viewer")
def export_png(tracker_id: int):
    return _export(tracker_id, "png", html_to_png, "image/png")
