"""The live weekly report page (spec section 7.1)."""

from __future__ import annotations

import re
from datetime import date

from flask import Response, abort, g, jsonify, render_template, request

from ..auth import require_tracker_role
from ..db import get_session
from ..engine.weeks import week_endings
from . import bp
from .build import build_report, compute_position, current_report_week
from .chart_data import chart_payload
from .render import html_to_pdf, html_to_png, render_print_html


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


@bp.get("/trackers/<int:tracker_id>/report")
@require_tracker_role("viewer")
def view(tracker_id: int):
    tracker = g.tracker
    report = build_report(get_session(), tracker, _report_week(tracker), today())
    weeks = week_endings(tracker.first_week_ending, tracker.last_week_ending)
    return render_template(
        "report/page.html",
        tracker=tracker,
        report=report,
        weeks=weeks,
        page_title=f"{tracker.name} report",
        current_page="trackers",
    )


@bp.get("/trackers/<int:tracker_id>/report/data.json")
@require_tracker_role("viewer")
def chart_data(tracker_id: int):
    """The weekly series behind the interactive charts, for the same week as the report page."""
    tracker = g.tracker
    position = compute_position(get_session(), tracker, _report_week(tracker), today())
    return jsonify(chart_payload(tracker, position.rows))


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "tracker"


def _export(tracker_id: int, extension: str, convert, mimetype: str) -> Response:
    tracker = g.tracker
    report = build_report(get_session(), tracker, _report_week(tracker), today())
    data = convert(render_print_html(report))
    filename = f"{_slug(tracker.name)}-week-ending-{report.week_ending.isoformat()}.{extension}"
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
