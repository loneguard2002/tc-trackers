"""Team tree helpers. The tree functions are pure; the loaders and the form parser need the database."""

from tracker.teams.tree import (
    TeamRow,
    children_map,
    descendants,
    load_team_rows,
    order_tree,
    parse_team_id,
    paths,
    team_choices,
)

ROWS = [
    TeamRow(1, None, "Infrastructure"),
    TeamRow(2, 1, "Windows"),
    TeamRow(3, 1, "network"),
    TeamRow(4, 2, "Desktops"),
    TeamRow(5, None, "Applications"),
]

TEAM_CHOICE_ERROR = "Choose a team from the list."


def test_children_map_groups_siblings_sorted_ignoring_case():
    children = children_map(ROWS)
    assert [r.id for r in children[None]] == [5, 1]
    assert [r.id for r in children[1]] == [3, 2]
    assert 3 not in children


def test_order_tree_is_preorder_with_depth_and_sorted_ignoring_case():
    assert [(r.id, d) for r, d in order_tree(ROWS)] == [(5, 0), (1, 0), (3, 1), (2, 1), (4, 2)]


def test_descendants_include_the_team_itself():
    assert descendants(ROWS, 1) == {1, 2, 3, 4} and descendants(ROWS, 4) == {4}


def test_paths_join_names_from_the_top():
    assert paths(ROWS)[4] == "Infrastructure › Windows › Desktops" and paths(ROWS)[5] == "Applications"


def test_load_team_rows_and_team_choices_follow_the_tree(db, team_factory):
    infrastructure = team_factory("Infrastructure")
    windows = team_factory("Windows", parent=infrastructure)
    applications = team_factory("Applications")
    assert sorted(load_team_rows(db)) == sorted(
        [
            TeamRow(infrastructure.id, None, "Infrastructure"),
            TeamRow(windows.id, infrastructure.id, "Windows"),
            TeamRow(applications.id, None, "Applications"),
        ]
    )
    assert len(load_team_rows(db, lock=True)) == 3
    assert team_choices(db) == [
        (applications.id, "Applications"),
        (infrastructure.id, "Infrastructure"),
        (windows.id, "Infrastructure › Windows"),
    ]


def test_parse_team_id(db, team_factory):
    team = team_factory("Windows")
    assert parse_team_id(db, None) == (None, None)
    assert parse_team_id(db, "  ") == (None, None)
    assert parse_team_id(db, f" {team.id} ") == (team, None)
    for value in ("abc", "-1", "0", "1.5", "²", str(team.id + 1), "99999999999999999999"):
        assert parse_team_id(db, value) == (None, TEAM_CHOICE_ERROR), value
