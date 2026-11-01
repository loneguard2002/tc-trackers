"""What moving a team would change: who loses, gains or changes a role on the trackers that move with it.

Only people who belong to some team can be affected by a move; administrators and people who are not active are left
out. The preview moves the team inside a savepoint, reads everyone's roles again and rolls the savepoint back.
"""

from __future__ import annotations

from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.roles import tracker_roles
from ..models import Team, TeamMember, Tracker, User
from .tree import descendants, load_team_rows


class AccessChange(NamedTuple):
    user: User
    tracker: Tracker
    before: str | None
    after: str | None


class MoveImpact(NamedTuple):
    losses: list[AccessChange]
    gains: list[AccessChange]
    changes: list[AccessChange]
    trackers: list[Tracker]  # every tracker in the team and below, archived included, by name


def move_impact(session: Session, team: Team, new_parent_id: int | None) -> MoveImpact:
    """Compare each person's role on each tracker in the team and below before and after moving ``team``.

    Leaves the session as it found it: the move is made in a savepoint that is always rolled back.
    """
    subtree = descendants(load_team_rows(session), team.id)
    trackers = list(
        session.scalars(select(Tracker).where(Tracker.team_id.in_(subtree)).order_by(Tracker.name, Tracker.id))
    )
    tracker_ids = {tracker.id for tracker in trackers}
    by_id = {tracker.id: tracker for tracker in trackers}
    users = list(
        session.scalars(
            select(User)
            .where(User.status == "active", User.is_admin.is_(False), User.id.in_(select(TeamMember.user_id)))
            .order_by(User.id)
        )
    )

    def read() -> dict[int, dict[int, str]]:
        return {
            user.id: {t: role for t, role in tracker_roles(session, user).items() if t in tracker_ids} for user in users
        }

    before = read()
    try:
        with session.begin_nested() as savepoint:
            team.parent_id = new_parent_id
            session.flush()
            after = read()
            savepoint.rollback()
    finally:
        session.expire(team)
    losses, gains, changes = [], [], []
    for user in users:
        for tracker_id in tracker_ids:
            was, now = before[user.id].get(tracker_id), after[user.id].get(tracker_id)
            if was == now:
                continue
            item = AccessChange(user, by_id[tracker_id], was, now)
            (losses if now is None else gains if was is None else changes).append(item)
    for found in (losses, gains, changes):
        found.sort(key=lambda c: (c.user.full_name.casefold(), c.tracker.name.casefold(), c.tracker.id, c.user.id))
    return MoveImpact(losses, gains, changes, trackers)
