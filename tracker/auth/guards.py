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

Validate the input (duplicates, names, stale ids) before calling ``raises_own_access``: its flush is where an
``IntegrityError`` would otherwise surface. The two reads are separate READ COMMITTED reads, so a grant committed
concurrently in between can only cause a wrongful refusal, never a missed promotion.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import User
from .roles import ROLE_ORDER, tracker_roles

SELF_PROMOTION_MESSAGE = "You cannot make a change that gives you more access to a tracker. Ask an administrator."


def snapshot_access(session: Session, actor: User) -> dict[int, str] | None:
    """The actor's tracker roles before a change, or ``None`` for an administrator (exempt from the guard).

    Raises ``RuntimeError`` when the session already holds pending changes: the snapshot would include them (by
    autoflush) and the guard would then compare the change with itself.
    """
    if actor.is_admin:
        return None
    if session.new or session.dirty or session.deleted:
        raise RuntimeError("snapshot_access must run before the change is made")
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
