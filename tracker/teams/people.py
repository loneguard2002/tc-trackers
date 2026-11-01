"""Who reaches a team: its own members and the members of every team above it (spec sections 1 and 2).

A member of a team above reaches every team below it. Direct members are listed whatever their status; a person who
reaches a team only through one above it counts only while active.
"""

from __future__ import annotations

from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import ROLE_ORDER
from ..models import TeamMember, User
from .tree import TeamRow, load_team_rows, team_labels


class InheritedRole(NamedTuple):
    team_id: int
    path: str
    role: str


class TeamPerson(NamedTuple):
    user: User
    direct_role: str | None
    inherited: list[InheritedRole]

    @property
    def role(self) -> str:
        """The highest role the person holds on the team, direct or inherited."""
        roles = [inherit.role for inherit in self.inherited]
        if self.direct_role is not None:
            roles.append(self.direct_role)
        return max(roles, key=ROLE_ORDER.__getitem__)


def _chain(parents: dict[int, int | None], team_id: int) -> list[int]:
    """The teams above ``team_id``, nearest first; the walk stops at a team already seen."""
    seen = {team_id}
    chain: list[int] = []
    parent = parents.get(team_id)
    while parent is not None and parent not in seen:
        seen.add(parent)
        chain.append(parent)
        parent = parents.get(parent)
    return chain


def _parents(rows: list[TeamRow]) -> dict[int, int | None]:
    return {row.id: row.parent_id for row in rows}


def team_people(session: Session, team_id: int) -> list[TeamPerson]:
    """Every direct member and every active member of a team above, once each, sorted by name then id."""
    rows = load_team_rows(session)
    labels = team_labels(rows)
    above = _chain(_parents(rows), team_id)
    nearness = {above_id: index for index, above_id in enumerate(above)}
    memberships = session.execute(
        select(TeamMember.team_id, TeamMember.role, User)
        .join(User, User.id == TeamMember.user_id)
        .where(TeamMember.team_id.in_([team_id, *above]))
    ).all()

    users: dict[int, User] = {}
    direct: dict[int, str] = {}
    inherited: dict[int, list[InheritedRole]] = {}
    for member_team_id, role, user in sorted(memberships, key=lambda m: nearness.get(m[0], -1)):
        if member_team_id == team_id:
            users[user.id] = user
            direct[user.id] = role
        elif user.status == "active":
            users[user.id] = user
            inherited.setdefault(user.id, []).append(InheritedRole(member_team_id, labels[member_team_id], role))

    people = [TeamPerson(user, direct.get(user_id), inherited.get(user_id, [])) for user_id, user in users.items()]
    return sorted(people, key=lambda person: (person.user.full_name.casefold(), person.user.id))


def reach_counts(session: Session) -> dict[int, int]:
    """Team id to the number of distinct active users who belong to it or to any team above it."""
    parents = _parents(load_team_rows(session))
    members: dict[int, set[int]] = {}
    for member_team_id, user_id in session.execute(
        select(TeamMember.team_id, TeamMember.user_id)
        .join(User, User.id == TeamMember.user_id)
        .where(User.status == "active")
    ):
        members.setdefault(member_team_id, set()).add(user_id)
    return {
        team_id: len(set().union(*(members.get(t, set()) for t in [team_id, *_chain(parents, team_id)])))
        for team_id in parents
    }
