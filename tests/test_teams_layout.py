"""The Teams layout functions (spec 2026-11-26-teams-simple-redesign-design.md 4.4 and 4.7): the main higher team,
the Where it sits ladder and the indented team options (no database)."""

from __future__ import annotations

from tracker.teams.layout import TreeOption, ladder, main_parent_ids, tree_options
from tracker.teams.tree import TeamRow

ROWS = [
    TeamRow(1, "Group", ()),
    TeamRow(2, "EMEA", (1,)),
    TeamRow(3, "Data Products", (1,)),
    TeamRow(4, "Shared Analytics", (2, 3)),
    TeamRow(5, "London Desk", (2,)),
    TeamRow(6, "London Rates", (5,)),
]
NB = " "


def test_main_parent_is_first_by_name():
    assert main_parent_ids(ROWS)[4] == 3  # Data Products before EMEA
    assert 1 not in main_parent_ids(ROWS)


def test_ladder_of_a_shared_team():
    lad = ladder(ROWS, 4)
    assert [r.name for r in lad.path] == ["Group", "Data Products"]
    assert lad.below == []
    assert [[r.name for r in p] for p in lad.also] == [["Group", "EMEA"]]


def test_ladder_below_counts_deeper_and_marks_shared():
    lad = ladder(ROWS, 2)  # EMEA
    assert [(b.row.name, b.deeper, b.mainly_under) for b in lad.below] == [
        ("London Desk", 1, None),
        ("Shared Analytics", 0, "Data Products"),
    ]


def test_top_level_ladder_has_empty_path():
    assert ladder(ROWS, 1).path == []


def test_tree_options_indent_by_tier_and_disable_with_reason():
    opts = tree_options(ROWS, lambda i: "this team" if i == 5 else None)
    assert [o.label for o in opts][:2] == ["Group", f"{NB}└{NB}Data Products"]
    rates = next(o for o in opts if o.id == 6)
    assert rates.label == NB * 7 + f"└{NB}London Rates" and not rates.disabled
    assert next(o for o in opts if o.id == 5) == TreeOption(5, NB * 4 + f"└{NB}London Desk (this team)", True)
    assert [o.id for o in opts].count(4) == 1  # the shared team appears once, under Data Products


def test_cycles_end():
    rows = [TeamRow(1, "A", ()), TeamRow(2, "B", (3,)), TeamRow(3, "C", (2,))]
    assert ladder(rows, 2).path == [rows[2]]  # stops at C, which points back at B
    assert [o.id for o in tree_options(rows)] == [1]  # B and C cannot be reached from the top


def test_main_parent_follows_the_stored_main():
    rows = [*ROWS[:3], TeamRow(4, "Shared Analytics", (2, 3), main_id=2)]
    assert main_parent_ids(rows)[4] == 2  # EMEA, although Data Products sorts first


def test_a_main_that_is_not_a_parent_falls_back_to_first_by_name():
    rows = [*ROWS[:3], TeamRow(4, "Shared Analytics", (2, 3), main_id=99)]
    assert main_parent_ids(rows)[4] == 3
