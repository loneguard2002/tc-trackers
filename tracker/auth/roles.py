"""Per-tracker roles. Administrators count as owner on every tracker."""

from __future__ import annotations

from functools import wraps

from flask import abort, g
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Tracker, TrackerRole, User
from .session import current_user, login_required

ROLE_ORDER = {"viewer": 1, "editor": 2, "owner": 3}


def user_role(session: Session, user: User, tracker_id: int) -> str | None:
    if user.is_admin:
        return "owner"
    return session.scalar(
        select(TrackerRole.role).where(TrackerRole.user_id == user.id, TrackerRole.tracker_id == tracker_id)
    )


def visible_trackers(session: Session, user: User) -> list[Tracker]:
    query = select(Tracker).order_by(Tracker.name, Tracker.id)
    if not user.is_admin:
        query = query.join(TrackerRole, TrackerRole.tracker_id == Tracker.id).where(TrackerRole.user_id == user.id)
    return list(session.scalars(query))


def require_tracker_role(min_role: str):
    """Decorate a view taking ``tracker_id``.

    Anonymous users go to the sign-in page. A missing tracker, a missing role and an insufficient role all give 404,
    so the existence of a tracker is never revealed. Sets ``g.tracker`` and ``g.role``.
    """
    if min_role not in ROLE_ORDER:
        raise ValueError(f"Unknown role: {min_role}")

    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, tracker_id: int, **kwargs):
            user = current_user()
            db = get_session()
            tracker = db.get(Tracker, tracker_id)
            role = user_role(db, user, tracker_id) if tracker is not None else None
            if tracker is None or role is None or ROLE_ORDER[role] < ROLE_ORDER[min_role]:
                abort(404)
            g.tracker, g.role = tracker, role
            return view(*args, tracker_id=tracker_id, **kwargs)

        return wrapped

    return decorator
