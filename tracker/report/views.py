"""The live weekly report page (spec section 7.1)."""

from __future__ import annotations

from datetime import date

from flask import abort, g, render_template, request

from ..auth import require_tracker_role
from ..db import get_session
from ..engine.weeks import week_endings
from . import bp
from .build import build_report


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


@bp.get("/trackers/<int:tracker_id>/report")
@require_tracker_role("viewer")
def view(tracker_id: int):
    tracker = g.tracker
    report = build_report(get_session(), tracker, _requested_week(tracker), today())
    weeks = week_endings(tracker.first_week_ending, tracker.last_week_ending)
    return render_template(
        "report/page.html",
        tracker=tracker,
        report=report,
        weeks=weeks,
        page_title=f"{tracker.name} report",
        current_page="trackers",
    )
