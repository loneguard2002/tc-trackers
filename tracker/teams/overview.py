"""What the Teams New view shows (spec 2026-11-26-teams-new-view-design.md): the hierarchy as a chart, the counts on
its boxes, and, for a team, the chains of teams above it.

Like ``tree.py``, the chart and chain functions take every team as ``TeamRow`` tuples and touch no database; every
walk ends on a team already on its path, so corrupted data holding a cycle cannot hang a page.
"""

from __future__ import annotations

from typing import NamedTuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import ROLE_ORDER
from ..models import TeamMember, Tracker, User
from .tree import TeamRow, ancestors, sorted_by_name

FOLD_FROM_DEPTH = 3  # the top level is depth 1
FOLD_OVER = 8  # a team at that depth or deeper with more teams below it than this shows them folded


class ChartNode(NamedTuple):
    row: TeamRow
    children: list[ChartNode]
    also_under: list[str]  # the other higher teams' names, by name: the team shows once, under the first
    folded: bool  # its children show folded, as "+N teams"


def chart(rows: list[TeamRow]) -> list[ChartNode]:
    """The top-level teams, each with the teams below it. A team under several teams sits under the first by name
    and names the others in ``also_under``."""
    by_id = {row.id: row for row in rows}
    placed_under: dict[int | None, list[TeamRow]] = {}
    also: dict[int, list[str]] = {}
    for row in rows:
        parents = sorted_by_name(by_id[parent_id] for parent_id in row.parent_ids if parent_id in by_id)
        placed_under.setdefault(parents[0].id if parents else None, []).append(row)
        also[row.id] = [parent.name for parent in parents[1:]]

    def build(parent_id: int | None, depth: int, path: frozenset[int]) -> list[ChartNode]:
        nodes = []
        for row in sorted_by_name(placed_under.get(parent_id, [])):
            if row.id in path:  # a cycle in corrupted data: stop here
                continue
            children = build(row.id, depth + 1, path | {row.id})
            folded = depth >= FOLD_FROM_DEPTH and len(children) > FOLD_OVER
            nodes.append(ChartNode(row, children, also[row.id], folded))
        return nodes

    return build(None, 1, frozenset())


def chart_order(nodes: list[ChartNode], depth: int = 1) -> list[tuple[TeamRow, int]]:
    """The chart's teams top down, each with its depth (1 for the top level), as the chart lists them."""
    found: list[tuple[TeamRow, int]] = []
    for node in nodes:
        found.append((node.row, depth))
        found.extend(chart_order(node.children, depth + 1))
    return found


MAX_CHAINS = 6


def paths_to(rows: list[TeamRow], team_id: int, parent_ids: frozenset[int] | None = None) -> list[list[TeamRow]]:
    """Each chain of teams from the top level down to just above the team, by name; none for a top-level team.
    ``parent_ids`` stands in for the team's own higher teams (a change being previewed). At most ``MAX_CHAINS``."""
    by_id = {row.id: row for row in rows}

    def up(current: int, path: frozenset[int]) -> list[list[TeamRow]]:
        chains: list[list[TeamRow]] = []
        for parent_id in by_id[current].parent_ids if current in by_id else ():
            if parent_id in path or parent_id not in by_id:  # a cycle in corrupted data, or a team just deleted
                continue
            chains.extend([*chain, by_id[parent_id]] for chain in up(parent_id, path | {parent_id}) or [[]])
        return chains

    if parent_ids is None:
        chains = up(team_id, frozenset({team_id}))
    else:
        chains = []
        for parent_id in parent_ids:
            if parent_id in by_id and parent_id != team_id:
                above = up(parent_id, frozenset({team_id, parent_id})) or [[]]
                chains.extend([*chain, by_id[parent_id]] for chain in above)
    chains.sort(key=lambda chain: [(row.name.casefold(), row.id) for row in chain])
    return chains[:MAX_CHAINS]


def ancestor_levels(rows: list[TeamRow], team_id: int) -> dict[int, int]:
    """Each team above the team to how many levels up it is by the shortest path (1 for a higher team)."""
    by_id = {row.id: row for row in rows}
    levels: dict[int, int] = {}
    current, level, seen = [team_id], 0, {team_id}
    while current:
        level += 1
        above = []
        for team in current:
            for parent_id in by_id[team].parent_ids if team in by_id else ():
                if parent_id not in seen and parent_id in by_id:
                    seen.add(parent_id)
                    levels[parent_id] = level
                    above.append(parent_id)
        current = above
    return levels


def member_counts(session: Session) -> dict[int, int]:
    """Team id to its number of active direct members."""
    return dict(
        session.execute(
            select(TeamMember.team_id, func.count())
            .join(User, User.id == TeamMember.user_id)
            .where(User.status == "active")
            .group_by(TeamMember.team_id)
        ).all()
    )


def tracker_counts(session: Session) -> dict[int, int]:
    """Team id to its number of active (not archived) trackers."""
    return dict(
        session.execute(
            select(Tracker.team_id, func.count())
            .where(Tracker.status != "archived", Tracker.team_id.is_not(None))
            .group_by(Tracker.team_id)
        ).all()
    )


class ReachPerson(NamedTuple):
    name: str
    role: str  # the highest role the person reaches the team with
    team_name: str  # the team that role comes from: the team itself, or the nearest team above holding it


def reach_people(session: Session, rows: list[TeamRow]) -> dict[int, list[ReachPerson]]:
    """Team id to every active person in it or in a team above it, once each, with their highest role: Owners first,
    then Editors, then Viewers, each by name. A team placed under it would be reached by the same people."""
    names = {row.id: row.name for row in rows}
    held: dict[int, list[tuple[int, str, str]]] = {}  # team id to (user id, name, role) for its active members
    for team_id, user_id, full_name, role in session.execute(
        select(TeamMember.team_id, User.id, User.full_name, TeamMember.role)
        .join(User, User.id == TeamMember.user_id)
        .where(User.status == "active")
    ):
        held.setdefault(team_id, []).append((user_id, full_name, role))
    found: dict[int, list[ReachPerson]] = {}
    for row in rows:
        best: dict[int, ReachPerson] = {}  # by user id: two people can share a name
        for team_id in [row.id, *ancestors(rows, row.id)]:  # nearest first, so a tie keeps the nearest team
            for user_id, full_name, role in held.get(team_id, []):
                kept = best.get(user_id)
                if kept is None or ROLE_ORDER[role] > ROLE_ORDER[kept.role]:
                    best[user_id] = ReachPerson(full_name, role, names[team_id])
        found[row.id] = sorted(best.values(), key=lambda p: (-ROLE_ORDER[p.role], p.name.casefold(), p.name))
    return found
