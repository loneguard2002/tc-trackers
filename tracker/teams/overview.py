"""What the Teams New view shows of the whole hierarchy (spec 2026-11-26-teams-simple-redesign-design.md): the
Structure card's tree (``chart``) and the Whole structure layer's data (``structure_items``).

Like ``tree.py``, these take every team as ``TeamRow`` tuples and touch no database; every walk ends on a team already
on its path, so corrupted data holding a cycle cannot hang a page.
"""

from __future__ import annotations

from typing import NamedTuple

from ..lists.catalogue import Place
from .layout import main_parent_ids
from .tree import TeamRow, sorted_by_name


class ChartNode(NamedTuple):
    row: TeamRow
    children: list[ChartNode]
    also_under: list[str]  # the other higher teams' names, by name: the team shows once, under its main team


def chart(rows: list[TeamRow]) -> list[ChartNode]:
    """The top-level teams, each with the teams below it. A team under several teams sits under its main team
    (``layout.main_parent_ids``) and names the others in ``also_under``, by name."""
    by_id = {row.id: row for row in rows}
    main = main_parent_ids(rows)
    placed_under: dict[int | None, list[TeamRow]] = {}
    also: dict[int, list[TeamRow]] = {}
    for row in rows:
        parents = sorted_by_name(by_id[parent_id] for parent_id in row.parent_ids if parent_id in by_id)
        placed_under.setdefault(main.get(row.id), []).append(row)
        also[row.id] = [parent for parent in parents if parent.id != main.get(row.id)]

    def build(parent_id: int | None, path: frozenset[int]) -> list[ChartNode]:
        nodes = []
        for row in sorted_by_name(placed_under.get(parent_id, [])):
            if row.id in path:  # a cycle in corrupted data: stop here
                continue
            nodes.append(ChartNode(row, build(row.id, path | {row.id}), [other.name for other in also[row.id]]))
        return nodes

    return build(None, frozenset())


def structure_items(rows: list[TeamRow], places: dict[int, Place], reach: dict[int, int]) -> list[dict]:
    """The Whole structure's data (spec 4.9), one dict per team by name: its main higher team (where it sits), the
    other higher teams by name (its dotted lines), its place ("EMEA · London", "EMEA" or "") and how many people
    reach it through teams. The script lays it out; ``layout.main_parent_ids`` decides the main team."""
    by_id = {row.id: row for row in rows}
    main = main_parent_ids(rows)
    items = []
    for row in sorted_by_name(rows):
        place = places.get(row.id)
        parents = sorted_by_name(by_id[parent_id] for parent_id in row.parent_ids if parent_id in by_id)
        items.append(
            {
                "id": row.id,
                "name": row.name,
                "main": main.get(row.id),
                "others": [parent.id for parent in parents if parent.id != main.get(row.id)],
                "place": " · ".join(part for part in (place.region_code, place.city) if part) if place else "",
                "people": reach.get(row.id, 0),
            }
        )
    return items
