"""What the Teams New view shows (spec 2026-11-26-teams-new-view-design.md): the hierarchy as a chart, the counts on
its boxes, and, for a team, the chains of teams above it.

Like ``tree.py``, the chart and chain functions take every team as ``TeamRow`` tuples and touch no database; every
walk ends on a team already on its path, so corrupted data holding a cycle cannot hang a page.
"""

from __future__ import annotations

from typing import NamedTuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import TeamMember, Tracker, User
from .layout import main_parent_ids
from .tree import TeamRow, sorted_by_name

FOLD_FROM_DEPTH = 3  # the top level is depth 1
FOLD_OVER = 8  # a team at that depth or deeper with more teams below it than this shows them folded


class ChartNode(NamedTuple):
    row: TeamRow
    children: list[ChartNode]
    also_under: list[str]  # the other higher teams' names, by name: the team shows once, under the first
    folded: bool  # its children show folded, as "+N teams"
    also_ids: tuple[int, ...] = ()  # the same other higher teams' ids, for the chart's dotted lines


def chart(rows: list[TeamRow]) -> list[ChartNode]:
    """The top-level teams, each with the teams below it. A team under several teams sits under its main team
    (``layout.main_parent_ids``) and names the others in ``also_under`` (their ids in ``also_ids``), by name."""
    by_id = {row.id: row for row in rows}
    main = main_parent_ids(rows)
    placed_under: dict[int | None, list[TeamRow]] = {}
    also: dict[int, list[TeamRow]] = {}
    for row in rows:
        parents = sorted_by_name(by_id[parent_id] for parent_id in row.parent_ids if parent_id in by_id)
        placed_under.setdefault(main.get(row.id), []).append(row)
        also[row.id] = [parent for parent in parents if parent.id != main.get(row.id)]

    def build(parent_id: int | None, depth: int, path: frozenset[int]) -> list[ChartNode]:
        nodes = []
        for row in sorted_by_name(placed_under.get(parent_id, [])):
            if row.id in path:  # a cycle in corrupted data: stop here
                continue
            children = build(row.id, depth + 1, path | {row.id})
            folded = depth >= FOLD_FROM_DEPTH and len(children) > FOLD_OVER
            others = also[row.id]
            nodes.append(ChartNode(row, children, [o.name for o in others], folded, tuple(o.id for o in others)))
        return nodes

    return build(None, 1, frozenset())


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
