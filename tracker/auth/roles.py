"""Per-tracker roles (spec section 6.1).

An active user's role on a tracker is the highest of: administrator (owner everywhere), a direct role, a team role
(membership of the tracker's team or of any team above it, by any path) and the ``view_all_trackers`` permission (viewer
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
    PermissionSet,
    PermissionSetHolder,
    PermissionSetPermission,
    TeamMember,
    TeamParent,
    Tracker,
    TrackerRole,
    User,
)
from .session import current_user, login_required

ROLE_ORDER = {"viewer": 1, "editor": 2, "owner": 3}
ROLE_BY_RANK = {1: "viewer", 2: "editor", 3: "owner"}
ROLES = tuple(ROLE_ORDER)  # the roles in rising order, for selects and checks


def _rank(role_column):
    return case(ROLE_ORDER, value=role_column)


def _grants(user_id: int) -> Subquery:
    """Every (tracker_id, rank) the user holds by a direct role, a team role or ``view_all_trackers``.

    The team walk goes down every link to a lower team. It uses ``UNION`` rather than ``UNION ALL`` so it ends even if
    a cycle ever reached the table; several paths to one tracker give several rows, and the highest rank wins.
    """
    reach = (
        select(TeamMember.team_id.label("team_id"), _rank(TeamMember.role).label("rank"))
        .where(TeamMember.user_id == user_id)
        .cte("reach", recursive=True)
    )
    reach = reach.union(select(TeamParent.team_id, reach.c.rank).join(reach, TeamParent.parent_id == reach.c.team_id))
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
    team_name: str  # the team the person belongs to
    role: str
    team_id: int | None = None  # the team the person belongs to, for a link


def team_access(session: Session, tracker: Tracker) -> list[TeamAccess]:
    """Who reaches the tracker through a team: one row per membership of an active user in its team or a team above.

    A team above counts once however many paths lead from it. Sorted by user name, then team name. Empty without a
    team.
    """
    if tracker.team_id is None:
        return []
    # here: importing tracker.teams at load time is circular
    from ..teams.tree import ancestors, load_team_rows, team_labels

    rows = load_team_rows(session)
    labels = team_labels(rows)
    reaching = {tracker.team_id, *ancestors(rows, tracker.team_id)}
    found = session.execute(
        select(User, TeamMember.team_id, TeamMember.role)
        .join(TeamMember, TeamMember.user_id == User.id)
        .where(TeamMember.team_id.in_(reaching), User.status == "active")
    )
    access = [TeamAccess(user, labels.get(team, ""), role, team) for user, team, role in found]
    return sorted(access, key=lambda a: (a.user.full_name.lower(), a.user.full_name, a.team_name.casefold(), a.user.id))


class Route(NamedTuple):
    text: str
    role: str  # the role this route gives; it "sets the role" when it equals the tracker's effective role


class TrackerAccess(NamedTuple):
    tracker: Tracker
    role: str
    routes: list[Route]


def tracker_access_routes(session: Session, user: User) -> list[TrackerAccess]:
    """Every tracker the user reaches, with the highest role and every route that gives one (Effective access).

    Routes read ``"Administrator"``, ``"Direct role: Viewer"``, ``"Team Windows: Editor"`` (one per team the user
    belongs to, by team name) and ``"View all trackers: Viewer"``, in that order. The roles agree with
    ``tracker_roles``. Sorted by tracker name, then id; empty for a user who is not active.
    """
    if user.status != "active":
        return []
    from ..teams.tree import descendants, load_team_rows, team_labels  # here: see team_access
    from .permissions import set_permission_sources

    trackers = {tracker.id: tracker for tracker in session.scalars(select(Tracker))}
    routes: dict[int, list[tuple[str, str]]] = {}  # tracker id -> [(role, route text)]

    def add(tracker_ids, role: str, text: str) -> None:
        for tracker_id in tracker_ids:
            if tracker_id in trackers:
                routes.setdefault(tracker_id, []).append((role, text))

    if user.is_admin:
        add(trackers, "owner", "Administrator")
    direct = session.execute(select(TrackerRole.tracker_id, TrackerRole.role).where(TrackerRole.user_id == user.id))
    for tracker_id, role in direct:
        add([tracker_id], role, f"Direct role: {role.title()}")
    rows = load_team_rows(session)
    labels = team_labels(rows)
    by_team: dict[int, list[int]] = {}
    for tracker in trackers.values():
        if tracker.team_id is not None:
            by_team.setdefault(tracker.team_id, []).append(tracker.id)
    memberships = session.execute(select(TeamMember.team_id, TeamMember.role).where(TeamMember.user_id == user.id))
    for team_id, role in sorted(memberships, key=lambda m: (labels.get(m.team_id, "").casefold(), m.team_id)):
        reached = [tracker_id for team in descendants(rows, team_id) for tracker_id in by_team.get(team, [])]
        add(reached, role, f"Team {labels.get(team_id, '')}: {role.title()}")
    if any(permission == "view_all_trackers" for permission, _source in set_permission_sources(session, user)):
        add(trackers, "viewer", "View all trackers: Viewer")
    access = [
        TrackerAccess(
            trackers[tracker_id],
            ROLE_BY_RANK[max(ROLE_ORDER[role] for role, _text in found)],
            [Route(text, role) for role, text in found],
        )
        for tracker_id, found in routes.items()
    ]
    return sorted(access, key=lambda a: (a.tracker.name, a.tracker.id))


class AccessRow(NamedTuple):
    user: User
    role: str  # the highest role over every route; agrees with ``user_role``
    direct_role: str | None
    teams: list[TeamAccess]
    view_all_sets: list[str]  # names of sets granting view_all_trackers, held directly or through a team they belong to
    admin: bool


def tracker_access_list(session: Session, tracker: Tracker) -> list[AccessRow]:
    """Every active user who can open the tracker, once, with each route that gives access.

    Sorted by name (case-insensitive), then id. Inactive users never appear.
    """
    users = {u.id: u for u in session.scalars(select(User).where(User.status == "active"))}
    direct = {
        r.user_id: r.role
        for r in session.scalars(select(TrackerRole).where(TrackerRole.tracker_id == tracker.id))
        if r.user_id in users
    }
    teams: dict[int, list[TeamAccess]] = {}
    for access in team_access(session, tracker):
        teams.setdefault(access.user.id, []).append(access)
    view_all: dict[int, set[str]] = {}
    holdings = session.execute(
        select(PermissionSet.name, PermissionSetHolder.user_id, PermissionSetHolder.team_id)
        .join(PermissionSetHolder, PermissionSetHolder.set_id == PermissionSet.id)
        .join(
            PermissionSetPermission,
            (PermissionSetPermission.set_id == PermissionSet.id)
            & (PermissionSetPermission.permission == "view_all_trackers"),
        )
    ).all()
    members: dict[int, list[int]] = {}
    team_ids = {team_id for _name, _user, team_id in holdings if team_id is not None}
    if team_ids:
        for team_id, user_id in session.execute(
            select(TeamMember.team_id, TeamMember.user_id).where(TeamMember.team_id.in_(team_ids))
        ):
            members.setdefault(team_id, []).append(user_id)
    for name, user_id, team_id in holdings:
        for holder in [user_id] if team_id is None else members.get(team_id, []):
            if holder in users:
                view_all.setdefault(holder, set()).add(name)
    rows = []
    for user_id, user in users.items():
        ranks = [ROLE_ORDER[a.role] for a in teams.get(user_id, [])]
        if user_id in direct:
            ranks.append(ROLE_ORDER[direct[user_id]])
        if user_id in view_all:
            ranks.append(ROLE_ORDER["viewer"])
        if user.is_admin:
            ranks.append(ROLE_ORDER["owner"])
        if not ranks:
            continue
        sets = sorted(view_all.get(user_id, ()), key=lambda n: (n.casefold(), n))
        rows.append(
            AccessRow(user, ROLE_BY_RANK[max(ranks)], direct.get(user_id), teams.get(user_id, []), sets, user.is_admin)
        )
    return sorted(rows, key=lambda r: (r.user.full_name.casefold(), r.user.id))


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
