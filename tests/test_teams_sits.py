"""The Where it sits draft (spec 2026-11-26-teams-simple-redesign-design.md 4.6): add, take out and make main before
one Save, and the preview's names (no database)."""

from __future__ import annotations

from types import SimpleNamespace

from werkzeug.datastructures import MultiDict

from tracker.teams.impact import AccessChange, MoveImpact
from tracker.teams.sits import Draft, Preview, add_reason, draft_errors, preview, read_draft
from tracker.teams.tree import TEAM_CHOICE_ERROR, TeamRow
from tracker.teams.views import CYCLE_MESSAGE

A, B, T, K, C = 1, 2, 3, 4, 5
ROWS = [
    TeamRow(A, "Alpha", ()),
    TeamRow(B, "Beta", (A,), A),
    TeamRow(T, "Team", (A, B), B),
    TeamRow(K, "Kid", (T,), T),
    TeamRow(C, "Gamma", ()),
]


def args(**values) -> MultiDict:
    return MultiDict(
        [(key, str(v)) for key, value in values.items() for v in (value if isinstance(value, list) else [value])]
    )


def test_without_draft_starts_from_what_is_saved():
    assert read_draft(ROWS, T, MultiDict()) == Draft((A, B), B)


def test_add_drop_and_make_main_apply_in_order():
    values = args(draft=1, above=[A, B], main=B, add=C, drop=A, make_main=C)
    assert read_draft(ROWS, T, values) == Draft((B, C), C)  # by name: Beta, Gamma


def test_add_ignores_itself_teams_below_and_teams_already_above():
    for team_id in (K, T, A):
        assert read_draft(ROWS, T, args(draft=1, above=[A, B], main=B, add=team_id)) == Draft((A, B), B)


def test_dropping_the_main_passes_it_on_and_dropping_all_leaves_top_level():
    assert read_draft(ROWS, T, args(draft=1, above=[A, B], main=B, drop=B)) == Draft((A,), A)
    assert read_draft(ROWS, T, args(draft=1, above=[A], main=A, drop=A)) == Draft((), None)


def test_unknown_ids_are_dropped_quietly():
    assert read_draft(ROWS, T, args(draft=1, above=[A, 999, "x"], main=999)) == Draft((A,), A)


def test_draft_errors_refuse_unknown_and_loops():
    assert draft_errors(ROWS, T, ["999"], "999")[1] == [TEAM_CHOICE_ERROR]
    assert draft_errors(ROWS, T, [str(K)], str(K))[1] == [CYCLE_MESSAGE]
    assert draft_errors(ROWS, T, [str(T)], str(T))[1] == [CYCLE_MESSAGE]
    assert draft_errors(ROWS, T, [str(A)], str(C))[1] == [TEAM_CHOICE_ERROR]
    assert draft_errors(ROWS, T, [str(A), str(A)], str(A)) == (Draft((A,), A), [])
    assert draft_errors(ROWS, T, [], "") == (Draft((), None), [])


def test_add_reasons():
    reason = add_reason(ROWS, T, Draft((A, B), B))
    assert [reason(i) for i in (T, K, A, C)] == [
        "this team",
        "below this team, would make a loop",
        "already above",
        None,
    ]


def test_preview_names_people_once():
    ana, ben = SimpleNamespace(full_name="Ana"), SimpleNamespace(full_name="Ben")
    t1, t2 = SimpleNamespace(name="One"), SimpleNamespace(name="Two")
    impact = MoveImpact(
        losses=[AccessChange(ben, t1, "viewer", None)],
        gains=[AccessChange(ana, t1, None, "viewer"), AccessChange(ana, t2, None, "editor")],
        changes=[],
        trackers=[t1, t2],
    )
    assert preview(impact) == Preview(["Ana"], ["Ben"], [])


def test_a_posted_draft_leaves_out_the_team_itself_and_teams_below():
    assert read_draft(ROWS, T, args(draft=1, above=[T, K, A], main=T)) == Draft((A,), A)
