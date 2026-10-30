"""The team tree (spec section 6.4): ordering, descendants and path labels over plain rows, and their loaders.

The tree functions take every team as ``TeamRow`` tuples and touch no database. Cycles are prevented when teams are
moved; a team caught in one would never be reached from the top level and is left out of ``order_tree`` and ``paths``.
"""

from __future__ import annotations

from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Team

PATH_SEPARATOR = " › "
TEAM_CHOICE_ERROR = "Choose a team from the list."
_MAX_ID = 2**31 - 1  # the largest Postgres integer; a larger id cannot exist and must not reach the query


class TeamRow(NamedTuple):
    id: int
    parent_id: int | None
    name: str


def children_map(rows: list[TeamRow]) -> dict[int | None, list[TeamRow]]:
    """Parent id (``None`` for the top level) to its child teams, sorted by name ignoring case."""
    children: dict[int | None, list[TeamRow]] = {}
    for row in rows:
        children.setdefault(row.parent_id, []).append(row)
    for siblings in children.values():
        siblings.sort(key=lambda row: (row.name.casefold(), row.id))
    return children


def order_tree(rows: list[TeamRow]) -> list[tuple[TeamRow, int]]:
    """Every team in pre-order with its depth (0 for the top level)."""
    children = children_map(rows)
    ordered: list[tuple[TeamRow, int]] = []
    stack = [(row, 0) for row in reversed(children.get(None, []))]
    while stack:
        row, depth = stack.pop()
        ordered.append((row, depth))
        stack.extend((child, depth + 1) for child in reversed(children.get(row.id, [])))
    return ordered


def descendants(rows: list[TeamRow], team_id: int) -> set[int]:
    """The team and every team below it."""
    children = children_map(rows)
    found = {team_id}
    pending = [team_id]
    while pending:
        for child in children.get(pending.pop(), []):
            if child.id not in found:
                found.add(child.id)
                pending.append(child.id)
    return found


def paths(rows: list[TeamRow]) -> dict[int, str]:
    """Team id to its path label from the top, for example ``"Infrastructure › Windows"``."""
    labels: dict[int, str] = {}
    for row, _depth in order_tree(rows):
        parent = labels.get(row.parent_id) if row.parent_id is not None else None
        labels[row.id] = f"{parent}{PATH_SEPARATOR}{row.name}" if parent else row.name
    return labels


def load_team_rows(session: Session, lock: bool = False) -> list[TeamRow]:
    """Every team; with ``lock`` the rows are read ``FOR UPDATE`` so a concurrent move cannot form a cycle."""
    query = select(Team.id, Team.parent_id, Team.name).order_by(Team.id)
    if lock:
        query = query.with_for_update()
    return [TeamRow(*row) for row in session.execute(query)]


def team_choices(session: Session) -> list[tuple[int, str]]:
    """``(id, path label)`` for every team in tree order, for selects."""
    rows = load_team_rows(session)
    labels = paths(rows)
    return [(row.id, labels[row.id]) for row, _depth in order_tree(rows)]


def parse_team_id(session: Session, value: str | None) -> tuple[Team | None, str | None]:
    """A team chosen in a form: ``(None, None)`` for no team, ``(None, message)`` for anything but an existing id."""
    text = (value or "").strip()
    if not text:
        return None, None
    if not (text.isascii() and text.isdigit()) or int(text) > _MAX_ID:
        return None, TEAM_CHOICE_ERROR
    team = session.get(Team, int(text))
    return (team, None) if team is not None else (None, TEAM_CHOICE_ERROR)
