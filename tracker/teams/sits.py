"""Where a team sits, as a draft (spec 2026-11-26-teams-simple-redesign-design.md 4.6): the higher teams and the main
one, changed by adding, taking out and making main before one Save, and the names the preview shows.

Like ``tree.py`` these take every team as ``TeamRow`` tuples and touch no database.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import NamedTuple, Protocol

from ..ids import parse_id
from .impact import MoveImpact
from .layout import main_parent_ids
from .tree import TEAM_CHOICE_ERROR, TeamRow, descendants, sorted_by_name

CYCLE_MESSAGE = "A team cannot be placed under itself or under a team below it."


class Values(Protocol):  # request.args, request.form, a MultiDict
    def get(self, key: str, default: str | None = None) -> str | None: ...
    def getlist(self, key: str) -> list[str]: ...


class Draft(NamedTuple):
    above: tuple[int, ...]  # the higher teams, by name
    main: int | None  # one of them; None at the top level


def _by_name(rows: list[TeamRow], ids) -> tuple[int, ...]:
    chosen = set(ids)
    return tuple(row.id for row in sorted_by_name(row for row in rows if row.id in chosen))


def _settle(rows: list[TeamRow], above, main: int | None) -> Draft:
    """The draft with ``above`` by name and a main among them: ``main`` when it is above, else the first by name."""
    ordered = _by_name(rows, above)
    return Draft(ordered, main if main in ordered else (ordered[0] if ordered else None))


def read_draft(rows: list[TeamRow], team_id: int, values: Values) -> Draft:
    """The draft the editor shows. Without ``draft=1``, what is saved; with it, ``above`` and ``main`` from the
    address, unknown teams left out. Then ``add``, ``drop`` and ``make_main`` apply, in that order."""
    known = {row.id for row in rows}
    if values.get("draft") == "1":
        above = [team for team in (parse_id(text) for text in values.getlist("above")) if team in known]
        main = parse_id(values.get("main"))
    else:
        row = next((row for row in rows if row.id == team_id), None)
        above = [team for team in (row.parent_ids if row else ()) if team in known]
        main = main_parent_ids(rows).get(team_id)
    draft = _settle(rows, above, main)
    add = parse_id(values.get("add"))
    if add in known and add not in descendants(rows, team_id) and add not in draft.above:
        draft = _settle(rows, [*draft.above, add], draft.main)
    drop = parse_id(values.get("drop"))
    if drop in draft.above:
        draft = _settle(
            rows, [team for team in draft.above if team != drop], draft.main if draft.main != drop else None
        )
    make_main = parse_id(values.get("make_main"))
    if make_main in draft.above:
        draft = Draft(draft.above, make_main)
    return draft


def draft_errors(rows: list[TeamRow], team_id: int, above: list[str], main: str) -> tuple[Draft | None, list[str]]:
    """A posted draft, checked for Save: ``(draft, [])``, or ``(None, [message])`` for a team that is not there (or a
    main that is not among the higher teams) or one that would make a loop."""
    known = {row.id for row in rows}
    ids = [parse_id(text) for text in above]
    if any(team not in known for team in ids):
        return None, [TEAM_CHOICE_ERROR]
    if set(ids) & descendants(rows, team_id):
        return None, [CYCLE_MESSAGE]
    main_id = parse_id(main) if main else None
    if ids and main_id not in ids or not ids and main_id is not None:
        return None, [TEAM_CHOICE_ERROR]
    return _settle(rows, ids, main_id), []


def add_reason(rows: list[TeamRow], team_id: int, draft: Draft) -> Callable[[int], str | None]:
    """Why a team cannot be added above, for ``tree_options``; None when it can."""
    below = descendants(rows, team_id)

    def reason(candidate: int) -> str | None:
        if candidate == team_id:
            return "this team"
        if candidate in below:
            return "below this team, would make a loop"
        if candidate in draft.above:
            return "already above"
        return None

    return reason


class Preview(NamedTuple):
    gain: list[str]  # people who would see trackers they cannot see now
    lose: list[str]  # people who would no longer see some of them
    other_role: list[str]  # people whose role on some of them would change


def preview(impact: MoveImpact) -> Preview:
    """The people a change affects, each named once, by name ignoring case."""

    def names(changes) -> list[str]:
        return sorted({change.user.full_name for change in changes}, key=lambda name: (name.casefold(), name))

    return Preview(names(impact.gains), names(impact.losses), names(impact.changes))
