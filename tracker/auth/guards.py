"""The self-promotion guard (spec section 6.3).

A ``manage_teams`` holder who is not an administrator cannot make a change that raises their own role on any tracker
or gives them a tracker they could not reach. Every such change follows one pattern::

    before = snapshot_access(db, actor)
    ...apply the change...
    if raises_own_access(db, actor, before):
        db.rollback()
        flash(SELF_PROMOTION_MESSAGE, "danger")
        return redirect(...)
    record(...)
    db.commit()
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import User
from .roles import ROLE_ORDER, tracker_roles

SELF_PROMOTION_MESSAGE = "You cannot make a change that gives you more access to a tracker. Ask an administrator."


def snapshot_access(session: Session, actor: User) -> dict[int, str] | None:
    """The actor's tracker roles before a change, or ``None`` for an administrator (exempt from the guard)."""
    if actor.is_admin:
        return None
    return tracker_roles(session, actor)


def raises_own_access(session: Session, actor: User, before: dict[int, str] | None) -> bool:
    """Whether the pending change gives the actor a tracker or a higher role than ``before``.

    Flushes the session and recomputes the roles in the same transaction, straight from the database (no cache).
    """
    if before is None:
        return False
    session.flush()
    after = tracker_roles(session, actor)
    return any(
        tracker_id not in before or ROLE_ORDER[role] > ROLE_ORDER[before[tracker_id]]
        for tracker_id, role in after.items()
    )
