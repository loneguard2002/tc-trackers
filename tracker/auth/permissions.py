"""Permissions granted by permission sets (spec sections 6.2 and 7).

A user holds a permission when an administrator, or when a permission set that contains it is held by the user
directly or by a team the user is a direct member of (any role; a team does not pass its sets down the hierarchy).
"""

from __future__ import annotations

from functools import wraps

from flask import abort, g
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import PermissionSet, PermissionSetHolder, PermissionSetPermission, Team, TeamMember, User
from .session import _to_login, current_user

PERMISSIONS: dict[str, tuple[str, str]] = {
    "manage_users": (
        "Manage users",
        "Approve pending Entra users; create local users; reset local users' passwords; disable and re-enable users.",
    ),
    "manage_teams": (
        "Manage teams",
        "Create, rename, move and delete teams; add and remove members and change their roles; put trackers in teams "
        "and move them between teams; manage direct per-tracker roles (the tracker Access screen).",
    ),
    "create_trackers": ("Create trackers", "Create trackers, in any team or in none."),
    "import_workbooks": (
        "Import workbooks",
        "Use the Import workbook screen and the import confirmation, which creates a tracker.",
    ),
    "manage_email_settings": ("Manage email settings", "Change the application's email (SMTP) settings."),
    "view_all_trackers": ("View all trackers", "Viewer on every tracker."),
    "view_activity": ("View activity", "Read the Activity screen."),
}

# How the Permission sets screen groups the permissions on each card. Every permission appears in exactly one group.
PERMISSION_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("People and teams", ("manage_users", "manage_teams")),
    ("Trackers", ("create_trackers", "import_workbooks", "view_all_trackers")),
    ("Application", ("manage_email_settings", "view_activity")),
)


def user_permissions(session: Session, user: User) -> frozenset[str]:
    """Every permission the user holds; nothing for a user who is not active."""
    if user.status != "active":
        return frozenset()
    if user.is_admin:
        return frozenset(PERMISSIONS)
    member_teams = select(TeamMember.team_id).where(TeamMember.user_id == user.id)
    names = session.scalars(
        select(PermissionSetPermission.permission)
        .join(PermissionSetHolder, PermissionSetHolder.set_id == PermissionSetPermission.set_id)
        .where((PermissionSetHolder.user_id == user.id) | PermissionSetHolder.team_id.in_(member_teams))
        .distinct()
    )
    return frozenset(name for name in names if name in PERMISSIONS)


def set_permission_sources(session: Session, user: User) -> list[tuple[str, str]]:
    """``(permission, source)`` for every permission the user's sets grant, whatever the account's status.

    Sources read ``"Set PMO, held directly"`` or ``"Set PMO, held by team PMO Office"`` (the team's path), ordered by
    set name, then direct holdings first, then team path. The administrator flag is not a source here.
    """
    from ..teams.tree import load_team_rows, paths  # here: importing tracker.teams at load time would be circular

    labels = paths(load_team_rows(session))
    holdings = session.execute(
        select(PermissionSet.name, PermissionSetPermission.permission, PermissionSetHolder.team_id, Team.name)
        .join(PermissionSetHolder, PermissionSetHolder.set_id == PermissionSet.id)
        .join(PermissionSetPermission, PermissionSetPermission.set_id == PermissionSet.id)
        .outerjoin(Team, Team.id == PermissionSetHolder.team_id)
        .outerjoin(TeamMember, (TeamMember.team_id == PermissionSetHolder.team_id) & (TeamMember.user_id == user.id))
        .where((PermissionSetHolder.user_id == user.id) | TeamMember.user_id.is_not(None))
    ).all()
    found = []
    for set_name, permission, team_id, team_name in holdings:
        if permission not in PERMISSIONS:
            continue
        held_by = "held directly" if team_id is None else f"held by team {labels.get(team_id, team_name)}"
        found.append((set_name.casefold(), set_name, team_id is not None, held_by, permission))
    return [(permission, f"Set {name}, {held_by}") for _key, name, _by_team, held_by, permission in sorted(found)]


def permission_sources(session: Session, user: User) -> dict[str, list[str]]:
    """Every permission the user holds, in the order of ``PERMISSIONS``, with where each comes from.

    ``"Administrator"`` for the administrator flag, then each set granting it. Nothing for a user who is not active.
    """
    if user.status != "active":
        return {}
    sources: dict[str, list[str]] = {name: ["Administrator"] for name in PERMISSIONS} if user.is_admin else {}
    for permission, source in set_permission_sources(session, user):
        sources.setdefault(permission, []).append(source)
    return {name: sources[name] for name in PERMISSIONS if name in sources}


def has_permission(user: User | None, permission: str) -> bool:
    """Whether the user holds the permission, worked out once per request and user."""
    if permission not in PERMISSIONS:
        raise ValueError(f"Unknown permission: {permission}")
    if user is None:
        return False
    cache = g.setdefault("permission_cache", {})
    if user.id not in cache:
        cache[user.id] = user_permissions(get_session(), user)
    return permission in cache[user.id]


def permission_required(permission: str):
    """Decorate a view: anonymous users go to sign in, users without the permission get 403."""
    if permission not in PERMISSIONS:
        raise ValueError(f"Unknown permission: {permission}")

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = current_user()
            if user is None:
                return _to_login()
            if not has_permission(user, permission):
                abort(403, description="You do not have permission to open this page.")
            return view(*args, **kwargs)

        return wrapped

    return decorator
