"""PLACEHOLDER tracker views.

These stubs exist only so that the role tests of Task 5 can exercise ``require_tracker_role``.
Task 6 replaces ``view`` and Task 7 replaces ``new_entry``; delete this module's routes then.
"""

from __future__ import annotations

from flask import Blueprint

from ..auth import require_tracker_role

bp = Blueprint("trackers", __name__)


@bp.get("/trackers/<int:tracker_id>")
@require_tracker_role("viewer")
def view(tracker_id: int):
    return "placeholder"  # PLACEHOLDER: replaced in Task 6


@bp.get("/trackers/<int:tracker_id>/entries/new")
@require_tracker_role("editor")
def new_entry(tracker_id: int):
    return "placeholder"  # PLACEHOLDER: replaced in Task 7
