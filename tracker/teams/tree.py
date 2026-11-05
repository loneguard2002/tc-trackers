"""The team tree (spec sections 6.4 and 5): higher teams, descendants, ancestors and labels over plain rows.

A team sits under zero or more higher teams (``team_parents``); none means top level. The tree functions take every
team as ``TeamRow`` tuples and touch no database. Cycles are prevented when teams are moved; a team caught in one is
never reached from the top level, and every walk ends on a team already seen.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import NamedTuple

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from ..ids import parse_id
from ..models import Team, TeamParent

TEAM_CHOICE_ERROR = "Choose a team from the list."
ALREADY_MEMBER_MESSAGE = "That person is already a member of this team."
CHOOSE_ROLE_MESSAGE = "Choose a role: viewer, editor or owner."


class TeamRow(NamedTuple):
    id: int
    name: str
    parent_ids: tuple[int, ...]  # the higher teams, ascending; empty for the top level


def _name_key(row: TeamRow) -> tuple[str, int]:
    return row.name.casefold(), row.id


def children_map(rows: list[TeamRow]) -> dict[int | None, list[TeamRow]]:
    """Higher team id (``None`` for the top level) to the teams below it, sorted by name ignoring case.

    A team with several higher teams is listed under each of them.
    """
    children: dict[int | None, list[TeamRow]] = {}
    for row in rows:
        for parent_id in row.parent_ids or (None,):
            children.setdefault(parent_id, []).append(row)
    for siblings in children.values():
        siblings.sort(key=_name_key)
    return children


def descendants(rows: list[TeamRow], team_id: int) -> set[int]:
    """The team and every team below it, by any path."""
    children = children_map(rows)
    found = {team_id}
    pending = [team_id]
    while pending:
        for child in children.get(pending.pop(), []):
            if child.id not in found:
                found.add(child.id)
                pending.append(child.id)
    return found


def ancestors(rows: list[TeamRow], team_id: int) -> list[int]:
    """Every team above the team, by any path, once each and without the team itself.

    Nearest first: level by level, each level sorted by name ignoring case, then id.
    """
    by_id = {row.id: row for row in rows}
    seen = {team_id}
    found: list[int] = []
    level = [team_id]
    while level:
        above = {
            parent_id
            for current in level
            for parent_id in (by_id[current].parent_ids if current in by_id else ())
            if parent_id not in seen and parent_id in by_id
        }
        level = [row.id for row in sorted((by_id[parent_id] for parent_id in above), key=_name_key)]
        seen.update(level)
        found.extend(level)
    return found


def team_labels(rows: list[TeamRow]) -> dict[int, str]:
    """Team id to the team's name, which is unique.

    Use this wherever a team is named in an activity entry or on a screen.
    """
    return {row.id: row.name for row in rows}


def load_team_rows(session: Session, lock: bool = False) -> list[TeamRow]:
    """Every team by id; with ``lock`` the ``teams`` rows are read ``FOR UPDATE`` before the links.

    Every change to the links takes that lock first, so a concurrent move cannot form a cycle.
    """
    query = select(Team.id, Team.name).order_by(Team.id)
    if lock:
        query = query.with_for_update()
    teams = session.execute(query).all()
    parents: dict[int, list[int]] = {}
    links = select(TeamParent.team_id, TeamParent.parent_id).order_by(TeamParent.team_id, TeamParent.parent_id)
    for team_id, parent_id in session.execute(links):
        parents.setdefault(team_id, []).append(parent_id)
    return [TeamRow(team_id, name, tuple(parents.get(team_id, ()))) for team_id, name in teams]


def team_choices(session: Session) -> list[tuple[int, str]]:
    """``(id, name)`` for every team, sorted by name ignoring case, then id, for selects."""
    return [(row.id, row.name) for row in sorted(load_team_rows(session), key=_name_key)]


def set_team_parents(session: Session, team_id: int, parent_ids: Iterable[int]) -> None:
    """Replace the team's higher teams with ``parent_ids`` (the caller checks for cycles and commits)."""
    session.execute(delete(TeamParent).where(TeamParent.team_id == team_id))
    links = [{"team_id": team_id, "parent_id": parent_id} for parent_id in sorted(set(parent_ids))]
    if links:
        session.execute(insert(TeamParent), links)


def parse_team_id(session: Session, value: str | None) -> tuple[Team | None, str | None]:
    """A team chosen in a form: ``(None, None)`` for no team, ``(None, message)`` for anything but an existing id."""
    if not (value or "").strip():
        return None, None
    team_id = parse_id(value)
    team = session.get(Team, team_id) if team_id is not None else None
    return (team, None) if team is not None else (None, TEAM_CHOICE_ERROR)
