"""What the Teams New view lays out (spec 2026-11-26-teams-simple-redesign-design.md 4.4 and 4.7): each team's main
higher team, the Where it sits ladder, and team dropdown options in structure order, indented by tier.

Like ``tree.py`` these take every team as ``TeamRow`` tuples and touch no database. Every walk stops on a team already
seen, so corrupted data holding a cycle cannot hang a page.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import NamedTuple

from .tree import TeamRow, descendants, sorted_by_name

NB = " "  # a no-break space: a select keeps it, where it would collapse ordinary spaces


def main_parent_ids(rows: list[TeamRow]) -> dict[int, int]:
    """Team id to its main higher team: the first by name among its higher teams. Top-level teams are absent."""
    by_id = {row.id: row for row in rows}
    found: dict[int, int] = {}
    for row in rows:
        parents = sorted_by_name(by_id[parent_id] for parent_id in row.parent_ids if parent_id in by_id)
        if parents:
            found[row.id] = parents[0].id
    return found


class BelowTeam(NamedTuple):
    row: TeamRow
    deeper: int  # the teams below it by any path, without itself
    mainly_under: str | None  # its main team's name when that is not the team being viewed


class Ladder(NamedTuple):
    path: list[TeamRow]  # from the top down to the main higher team; empty for a top-level team
    below: list[BelowTeam]  # the teams directly below, by name
    also: list[list[TeamRow]]  # for each other higher team, by name: its main path, then the team itself


def _main_path(by_id: dict[int, TeamRow], main: dict[int, int], team_id: int) -> list[TeamRow]:
    """The teams above ``team_id`` along main teams, top first, stopping on a team already seen."""
    path: list[TeamRow] = []
    seen = {team_id}
    current = main.get(team_id)
    while current is not None and current not in seen and current in by_id:
        seen.add(current)
        path.append(by_id[current])
        current = main.get(current)
    return path[::-1]


def ladder(rows: list[TeamRow], team_id: int) -> Ladder:
    by_id = {row.id: row for row in rows}
    main = main_parent_ids(rows)
    below = [
        BelowTeam(
            row,
            len(descendants(rows, row.id)) - 1,
            by_id[main[row.id]].name if main.get(row.id) not in (None, team_id) else None,
        )
        for row in sorted_by_name(row for row in rows if team_id in row.parent_ids and row.id != team_id)
    ]
    others = sorted_by_name(
        by_id[parent_id]
        for parent_id in (by_id[team_id].parent_ids if team_id in by_id else ())
        if parent_id in by_id and parent_id != main.get(team_id)
    )
    also = [[*_main_path(by_id, main, other.id), other] for other in others]
    return Ladder(_main_path(by_id, main, team_id), below, also)


class TreeOption(NamedTuple):
    id: int
    label: str
    disabled: bool


def tree_options(rows: list[TeamRow], reason: Callable[[int], str | None] = lambda _id: None) -> list[TreeOption]:
    """Every team reachable from the top, once, depth first under its main team, children by name. A team
    ``reason`` names stays in the list, disabled, with the reason after its name."""
    main = main_parent_ids(rows)
    under: dict[int | None, list[TeamRow]] = {}
    for row in rows:
        under.setdefault(main.get(row.id), []).append(row)
    options: list[TreeOption] = []
    seen: set[int] = set()

    def walk(parent_id: int | None, depth: int) -> None:
        for row in sorted_by_name(under.get(parent_id, [])):
            if row.id in seen:
                continue
            seen.add(row.id)
            why = reason(row.id)
            indent = NB * (3 * depth - 2) + "└" + NB if depth else ""
            options.append(TreeOption(row.id, f"{indent}{row.name}{f' ({why})' if why else ''}", bool(why)))
            walk(row.id, depth + 1)

    walk(None, 0)
    return options
