"""The live weekly report page (spec section 7.1)."""

from __future__ import annotations

from datetime import date

from flask import abort, g, render_template, request

from ..auth import require_tracker_role
from ..db import get_session
from ..engine.weeks import week_endings
from . import bp
from .build import build_report


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


@bp.get("/trackers/<int:tracker_id>/report")
@require_tracker_role("viewer")
def view(tracker_id: int):
    tracker = g.tracker
    report = build_report(get_session(), tracker, _requested_week(tracker), date.today())
    weeks = week_endings(tracker.first_week_ending, tracker.last_week_ending)
    return render_template(
        "report/page.html",
        report=report,
        weeks=weeks,
        page_title=f"{tracker.name} report",
        current_page="trackers",
    )
