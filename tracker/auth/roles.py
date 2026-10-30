"""Per-tracker roles (spec section 6.1).

An active user's role on a tracker is the highest of: administrator (owner everywhere), a direct role, a team role
(membership of the tracker's team or of any team above it) and the ``view_all_trackers`` permission (viewer
everywhere). Users who are not active have no access.
"""

from __future__ import annotations

from functools import wraps
from typing import NamedTuple

from flask import abort, g
from sqlalchemy import Select, Subquery, case, func, literal, or_, select, union_all
from sqlalchemy.orm import Session

from ..audit import change, record
from ..db import get_session
from ..models import (
    PermissionSetHolder,
    PermissionSetPermission,
    Team,
    TeamMember,
    Tracker,
    TrackerRole,
    User,
)
from .session import current_user, login_required

ROLE_ORDER = {"viewer": 1, "editor": 2, "owner": 3}
ROLE_BY_RANK = {1: "viewer", 2: "editor", 3: "owner"}


def _rank(role_column):
    return case(ROLE_ORDER, value=role_column)


def _grants(user_id: int) -> Subquery:
    """Every (tracker_id, rank) the user holds by a direct role, a team role or ``view_all_trackers``.

    The team walk uses ``UNION`` rather than ``UNION ALL`` so it ends even if a cycle ever reached the table.
    """
    reach = (
        select(TeamMember.team_id.label("team_id"), _rank(TeamMember.role).label("rank"))
        .where(TeamMember.user_id == user_id)
        .cte("reach", recursive=True)
    )
    reach = reach.union(select(Team.id, reach.c.rank).join(reach, Team.parent_id == reach.c.team_id))
    member_teams = select(TeamMember.team_id).where(TeamMember.user_id == user_id)
    view_all = (
        select(literal(1))
        .select_from(PermissionSetHolder)
        .join(
            PermissionSetPermission,
            (PermissionSetPermission.set_id == PermissionSetHolder.set_id)
            & (PermissionSetPermission.permission == "view_all_trackers"),
        )
        .where(or_(PermissionSetHolder.user_id == user_id, PermissionSetHolder.team_id.in_(member_teams)))
        .exists()
    )
    return union_all(
        select(TrackerRole.tracker_id.label("tracker_id"), _rank(TrackerRole.role).label("rank")).where(
            TrackerRole.user_id == user_id
        ),
        select(Tracker.id, reach.c.rank).join(reach, Tracker.team_id == reach.c.team_id),
        select(Tracker.id, literal(1)).where(view_all),
    ).subquery("grants")


def _role_ranks(user_id: int) -> Select:
    """The highest rank per tracker the user reaches: ``(tracker_id, rank)``."""
    grants = _grants(user_id)
    return select(grants.c.tracker_id, func.max(grants.c.rank).label("rank")).group_by(grants.c.tracker_id)


def tracker_roles(session: Session, user: User) -> dict[int, str]:
    """Tracker id to the user's highest role, for every tracker the user reaches (archived included)."""
    if user.status != "active":
        return {}
    if user.is_admin:
        return dict.fromkeys(session.scalars(select(Tracker.id)), "owner")
    return {tracker_id: ROLE_BY_RANK[rank] for tracker_id, rank in session.execute(_role_ranks(user.id))}


def user_role(session: Session, user: User, tracker_id: int) -> str | None:
    if user.status != "active":
        return None
    if user.is_admin:
        return "owner"
    ranks = _role_ranks(user.id).subquery()
    rank = session.scalar(select(ranks.c.rank).where(ranks.c.tracker_id == tracker_id))
    return ROLE_BY_RANK[rank] if rank is not None else None


class TeamAccess(NamedTuple):
    user: User
    path: str
    role: str


def team_access(session: Session, tracker: Tracker) -> list[TeamAccess]:
    """Who reaches the tracker through a team: one row per membership of an active user in its team or a team above.

    ``path`` is the path of the team the person belongs to. Sorted by user name, then path. Empty without a team.
    """
    if tracker.team_id is None:
        return []
    from ..teams.tree import load_team_rows, paths  # here: importing tracker.teams at load time would be circular

    rows = load_team_rows(session)
    parents = {row.id: row.parent_id for row in rows}
    labels = paths(rows)
    reaching: set[int] = set()
    team_id = tracker.team_id
    while team_id is not None and team_id not in reaching:  # the guard ends a walk through a cycle
        reaching.add(team_id)
        team_id = parents.get(team_id)
    found = session.execute(
        select(User, TeamMember.team_id, TeamMember.role)
        .join(TeamMember, TeamMember.user_id == User.id)
        .where(TeamMember.team_id.in_(reaching), User.status == "active")
    )
    access = [TeamAccess(user, labels[team], role) for user, team, role in found if team in labels]
    return sorted(access, key=lambda a: (a.user.full_name.lower(), a.user.full_name, a.path, a.user.id))


def visible_trackers(session: Session, user: User) -> list[Tracker]:
    """Every tracker the user reaches, ordered by name then id, in one SQL statement."""
    if user.status != "active":
        return []
    query = select(Tracker).order_by(Tracker.name, Tracker.id)
    if not user.is_admin:
        ranks = _role_ranks(user.id).subquery()
        query = query.join(ranks, ranks.c.tracker_id == Tracker.id)
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


def give_creator_ownership(session: Session, tracker: Tracker, actor: User) -> None:
    """Make a non-administrator who has just created ``tracker`` its owner, and log it (the caller commits).

    An administrator is owner everywhere already and gets no role. This is the only code that gives a creator the
    owner role, for the New tracker screen and for the workbook import alike.
    """
    if actor.is_admin:
        return
    session.add(TrackerRole(user_id=actor.id, tracker_id=tracker.id, role="owner"))
    record(
        session,
        user_id=actor.id,
        tracker_id=tracker.id,
        action="role_set",
        entity="user",
        entity_id=actor.id,
        detail=change(None, "owner"),
        target_user_id=actor.id,
    )
