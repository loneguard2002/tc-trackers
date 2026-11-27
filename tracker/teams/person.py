"""The Teams person view (spec 2026-11-26-teams-simple-redesign-design.md 4.8): which teams someone is in and
reaches, which trackers they can see and why, whether they can see one tracker, and the rights their permission sets
give. Built on ``tracker_access_routes`` and ``set_permission_sources``, so it agrees with Users › Access."""

from __future__ import annotations

from typing import NamedTuple

from sqlalchemy.orm import Session

from ..auth import ROLE_ORDER
from ..auth.permissions import PERMISSIONS, set_permission_sources
from ..auth.roles import Route, tracker_access_routes
from ..models import TeamMember, Tracker, User
from .layout import main_path
from .tree import TeamRow, descendants, sorted_by_name

ROUTE_NAMES = {"admin": "Administrator", "direct": "Given directly on this tracker", "all": "View all trackers"}


class TeamLine(NamedTuple):
    team: TeamRow
    how: str  # "Member", or "Through <team>": the team they are in that reaches this one
    role: str
    member: bool


class TrackerLine(NamedTuple):
    tracker: Tracker
    role: str  # the highest role over every route
    routes: list[tuple[str, str]]  # (plain words, the role it gives)


class CheckAnswer(NamedTuple):
    tracker: Tracker
    text: str  # "Yes, as Editor." or why not
    routes: list[tuple[str, str]]
    highest_wins: bool  # several routes: "the highest role wins"


class RightsLine(NamedTuple):
    source: str  # "Set PMO, held directly" or "Set PMO, held by team PMO Office"
    permissions: list[str]  # the permissions' names, in the app's order


def first_name(user: User) -> str:
    return (user.full_name.split() or [user.full_name])[0]


def person_teams(session: Session, rows: list[TeamRow], user: User) -> list[TeamLine]:
    """The teams the person is a member of, by name, then the teams below them that they reach, by name. A reached
    team names the member team above it giving the highest role (the first by name on a tie)."""
    by_id = {row.id: row for row in rows}
    held = {
        team_id: role
        for team_id, role in session.query(TeamMember.team_id, TeamMember.role).filter(TeamMember.user_id == user.id)
        if team_id in by_id
    }
    members = [TeamLine(row, "Member", held[row.id], True) for row in sorted_by_name(by_id[t] for t in held)]
    reached: dict[int, tuple[str, str]] = {}  # team id -> (role, through)
    for member in sorted_by_name(by_id[t] for t in held):
        for team_id in descendants(rows, member.id) - set(held):
            kept = reached.get(team_id)
            if kept is None or ROLE_ORDER[held[member.id]] > ROLE_ORDER[kept[0]]:
                reached[team_id] = (held[member.id], member.name)
    through = [
        TeamLine(row, f"Through {reached[row.id][1]}", reached[row.id][0], False)
        for row in sorted_by_name(by_id[t] for t in reached)
    ]
    return members + through


def _words(route: Route, rows: list[TeamRow]) -> str:
    if route.kind == "team":
        return "Member of " + " › ".join(row.name for row in main_path(rows, int(route.subject)))
    if route.kind == "region":
        return f"{route.subject} regional access"
    return ROUTE_NAMES.get(route.kind, route.text)


def person_trackers(session: Session, rows: list[TeamRow], user: User) -> list[TrackerLine]:
    """Every tracker the person can see, by name, with every route in plain words; empty while inactive."""
    return [
        TrackerLine(access.tracker, access.role, [(_words(route, rows), route.role) for route in access.routes])
        for access in tracker_access_routes(session, user)
    ]


def check_answer(session: Session, rows: list[TeamRow], user: User, tracker: Tracker) -> CheckAnswer:
    """Whether the person can see ``tracker``, in a sentence, with the routes when they can."""
    name = first_name(user)
    if user.status != "active":
        return CheckAnswer(tracker, f"No. {name} is inactive, so has no access to any tracker.", [], False)
    line = next((t for t in person_trackers(session, rows, user) if t.tracker.id == tracker.id), None)
    if line is not None:
        return CheckAnswer(tracker, f"Yes, as {line.role.title()}.", line.routes, len(line.routes) > 1)
    team = next((row for row in rows if row.id == tracker.team_id), None)
    if team is None:
        return CheckAnswer(tracker, f"{tracker.name} is in no team. {name} has no access to it.", [], False)
    text = (
        f"{tracker.name} belongs to {team.name}. {name} is not in that team or any team above it, and has no other "
        "access to it."
    )
    return CheckAnswer(tracker, text, [], False)


def person_rights(session: Session, user: User) -> list[RightsLine]:
    """Each permission set the person holds, directly or through a team they are in, with what it allows."""
    order = list(PERMISSIONS)
    grouped: dict[str, list[str]] = {}
    for permission, source in set_permission_sources(session, user):
        grouped.setdefault(source, []).append(permission)
    return [
        RightsLine(source, [PERMISSIONS[p][0] for p in sorted(set(perms), key=order.index)])
        for source, perms in grouped.items()
    ]
