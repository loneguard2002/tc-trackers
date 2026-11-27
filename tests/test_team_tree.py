"""Team tree helpers. The tree functions are pure; the loaders and the form parser need the database."""

import pytest

from tracker.ids import MAX_ID, in_range, parse_id
from tracker.teams.tree import (
    TeamRow,
    ancestors,
    children_map,
    descendants,
    load_team_rows,
    parse_team_id,
    set_team_parents,
    team_choices,
    team_labels,
)

ROWS = [
    TeamRow(1, "Infrastructure", ()),
    TeamRow(2, "Windows", (1,)),
    TeamRow(3, "network", (1,)),
    TeamRow(4, "Desktops", (2, 5)),
    TeamRow(5, "Applications", ()),
]

TEAM_CHOICE_ERROR = "Choose a team from the list."


def test_children_map_lists_a_team_under_each_higher_team():
    children = children_map(ROWS)
    assert [r.id for r in children[None]] == [5, 1]
    assert [r.id for r in children[1]] == [3, 2]
    assert [r.id for r in children[2]] == [4] and [r.id for r in children[5]] == [4]
    assert 3 not in children


def test_descendants_follow_every_path():
    assert descendants(ROWS, 5) == {5, 4} and descendants(ROWS, 1) == {1, 2, 3, 4}
    assert descendants(ROWS, 4) == {4}


def test_ancestors_every_path_nearest_first_without_repeats():
    assert ancestors(ROWS, 4) == [5, 2, 1]  # 5 and 2 at distance 1, Applications before Windows by name
    assert ancestors(ROWS, 1) == []


def test_ancestors_list_a_team_reached_by_two_paths_once():
    rows = [
        TeamRow(1, "Top", ()),
        TeamRow(2, "Left", (1,)),
        TeamRow(3, "right", (1,)),
        TeamRow(4, "Bottom", (2, 3)),
    ]
    assert ancestors(rows, 4) == [2, 3, 1]


def test_tree_functions_terminate_on_a_cycle():
    rows = [TeamRow(1, "A", (2,)), TeamRow(2, "B", (1,)), TeamRow(3, "C", ())]
    assert descendants(rows, 1) == {1, 2} and ancestors(rows, 1) == [2]
    assert [r.id for r in children_map(rows)[None]] == [3]


def test_team_labels_are_names():
    assert team_labels(ROWS)[4] == "Desktops"
    assert team_labels(ROWS) == {1: "Infrastructure", 2: "Windows", 3: "network", 4: "Desktops", 5: "Applications"}


def test_load_team_rows_reads_links(db, team_factory):
    infrastructure = team_factory("Infrastructure")
    applications = team_factory("applications")
    windows = team_factory("Windows", parent=infrastructure)
    desktops = team_factory("Desktops", parents=(windows, applications))
    assert load_team_rows(db) == [
        TeamRow(infrastructure.id, "Infrastructure", ()),
        TeamRow(applications.id, "applications", ()),
        TeamRow(windows.id, "Windows", (infrastructure.id,), infrastructure.id),
        TeamRow(desktops.id, "Desktops", (applications.id, windows.id), applications.id),  # main: first by name
    ]
    assert load_team_rows(db, lock=True) == load_team_rows(db)
    assert team_choices(db) == [
        (applications.id, "applications"),
        (desktops.id, "Desktops"),
        (infrastructure.id, "Infrastructure"),
        (windows.id, "Windows"),
    ]


def test_set_team_parents_replaces_the_links(db, team_factory):
    infrastructure, applications = team_factory("Infrastructure"), team_factory("Applications")
    windows = team_factory("Windows", parent=infrastructure)
    set_team_parents(db, windows.id, [applications.id, infrastructure.id, applications.id])
    db.commit()
    assert load_team_rows(db)[-1].parent_ids == (infrastructure.id, applications.id)
    set_team_parents(db, windows.id, frozenset())
    db.commit()
    assert load_team_rows(db)[-1].parent_ids == ()


def test_parse_team_id(db, team_factory):
    team = team_factory("Windows")
    assert parse_team_id(db, None) == (None, None)
    assert parse_team_id(db, "  ") == (None, None)
    assert parse_team_id(db, f" {team.id} ") == (team, None)
    for value in ("abc", "-1", "0", "1.5", "²", str(team.id + 1), "99999999999999999999"):
        assert parse_team_id(db, value) == (None, TEAM_CHOICE_ERROR), value


@pytest.mark.parametrize("text,expected", [("1", 1), (" 42 ", 42), (str(MAX_ID), MAX_ID), ("0007", 7)])
def test_parse_id_accepts_positive_ids(text, expected):
    assert parse_id(text) == expected


@pytest.mark.parametrize(
    "text", [None, "", "0", "-1", "+1", "1.0", "abc", "١٢", str(MAX_ID + 1), "9" * 11, "9" * 5000, "00000000001"]
)
def test_parse_id_refuses_anything_else(text):
    assert parse_id(text) is None


def test_in_range_bounds_ids_from_urls():
    assert in_range(1) and in_range(MAX_ID) and not in_range(0) and not in_range(MAX_ID + 1)


# --- The main higher team (spec 2026-11-26-teams-simple-redesign-design.md 4.6) -------------------------------------


def _main(db, team):
    from sqlalchemy import select

    from tracker.models import TeamParent

    return db.scalars(select(TeamParent.parent_id).where(TeamParent.team_id == team.id, TeamParent.is_main)).all()


def test_set_team_parents_keeps_the_current_main(db, team_factory):
    a, b, c = team_factory("A"), team_factory("B"), team_factory("C")
    t = team_factory("T", parents=(a, b), main=b)
    set_team_parents(db, t.id, [b.id, c.id])
    db.commit()
    assert _main(db, t) == [b.id]


def test_set_team_parents_moves_the_main_to_the_next_by_name(db, team_factory):
    a, b, c = team_factory("A"), team_factory("B"), team_factory("C")
    t = team_factory("T", parents=(a, b, c), main=b)
    set_team_parents(db, t.id, [a.id, c.id])
    db.commit()
    assert _main(db, t) == [a.id]


def test_set_team_parents_takes_the_given_main(db, team_factory):
    a, b = team_factory("A"), team_factory("B")
    t = team_factory("T", parents=(a,))
    set_team_parents(db, t.id, [a.id, b.id], main_id=b.id)
    db.commit()
    assert _main(db, t) == [b.id]


def test_top_level_has_no_main(db, team_factory):
    a = team_factory("A")
    t = team_factory("T", parent=a)
    set_team_parents(db, t.id, [])
    db.commit()
    assert _main(db, t) == []


def test_load_team_rows_reads_the_main(db, team_factory):
    a, b = team_factory("A"), team_factory("B")
    t = team_factory("T", parents=(a, b), main=b)
    assert next(r for r in load_team_rows(db) if r.id == t.id).main_id == b.id
    assert next(r for r in load_team_rows(db) if r.id == a.id).main_id is None
