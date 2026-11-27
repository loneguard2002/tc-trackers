"""The Teams person view (spec 2026-11-26-teams-simple-redesign-design.md 4.8): one person's teams, the trackers they
can see and why, "Can … see", and their rights (database)."""

from __future__ import annotations

import pytest
from test_teams_new_view import swaps  # noqa: F401  (the fixture)
from tracker.teams.person import check_answer, person_rights, person_teams, person_trackers

from tracker.auth.roles import tracker_access_routes
from tracker.models import RegionGrant, Tracker, TrackerRegion
from tracker.teams.tree import load_team_rows


@pytest.fixture
def tom(swaps):  # noqa: F811
    """Viewer of London Swaps and Editor of EMEA Rates above it."""
    return swaps["people"]["Tom Becker"]


def test_routes_carry_their_kind_and_subject(db, swaps, tom, grant, region_factory, tracker_factory):  # noqa: F811
    region = region_factory("EMEA")
    extra = tracker_factory(name="Regional tracker")
    db.add(TrackerRegion(tracker_id=extra.id, region_id=region.id))
    db.commit()
    db.add(RegionGrant(region_id=region.id, user_id=tom.id, role="viewer"))
    db.commit()
    grant(tom, extra, "owner")
    access = {a.tracker.name: a for a in tracker_access_routes(db, tom)}
    kinds = [(r.kind, r.subject, r.role) for r in access["Regional tracker"].routes]
    assert kinds == [("direct", "", "owner"), ("region", "EMEA", "viewer")]
    swaps_routes = [(r.kind, r.subject) for r in access["Swaps desk rollout"].routes]
    assert swaps_routes == [("team", str(swaps["rates"].id)), ("team", str(swaps["team"].id))]
    assert access["Swaps desk rollout"].routes[0].text == "Team EMEA Rates: Editor"  # Users › Access is unchanged


def test_teams_lists_memberships_then_the_teams_reached(db, swaps, team_factory, user_factory, add_member):  # noqa: F811
    team_factory("Desk", parent=swaps["team"])
    sam = swaps["people"]["Sam Ortiz"]  # Viewer of Global Markets, the top
    lines = person_teams(db, load_team_rows(db), sam)
    assert [(line.team.name, line.how, line.role, line.member) for line in lines] == [
        ("Global Markets", "Member", "viewer", True),
        ("Desk", "Through Global Markets", "viewer", False),
        ("EMEA Rates", "Through Global Markets", "viewer", False),
        ("London Swaps", "Through Global Markets", "viewer", False),
    ]


def test_a_reached_team_takes_the_highest_role_from_above(db, swaps, tom):  # noqa: F811
    lines = {line.team.name: line for line in person_teams(db, load_team_rows(db), tom)}
    assert (lines["London Swaps"].how, lines["London Swaps"].role, lines["London Swaps"].member) == (
        "Member",
        "viewer",
        True,
    )
    assert lines["EMEA Rates"].member and lines["EMEA Rates"].role == "editor"


def test_trackers_are_worded_plainly(db, swaps, tom, grant, tracker_factory, user_factory, give_set):  # noqa: F811
    lines = {line.tracker.name: line for line in person_trackers(db, load_team_rows(db), tom)}
    assert lines["Swaps desk rollout"].role == "editor"
    assert lines["Swaps desk rollout"].routes == [
        ("Member of Global Markets › EMEA Rates", "editor"),
        ("Member of Global Markets › EMEA Rates › London Swaps", "viewer"),
    ]
    viewer_all = user_factory(full_name="Vera All")
    give_set(["view_all_trackers"], user=viewer_all)
    lines = {line.tracker.name: line for line in person_trackers(db, load_team_rows(db), viewer_all)}
    assert lines["Swaps desk rollout"].routes == [("View all trackers", "viewer")]
    admin = user_factory(full_name="Ada Admin", is_admin=True)
    lines = person_trackers(db, load_team_rows(db), admin)
    assert all(line.routes == [("Administrator", "owner")] for line in lines)


def test_the_check_answers_yes_with_every_route(db, swaps, tom):  # noqa: F811
    rows = load_team_rows(db)
    tracker = next(t.tracker for t in person_trackers(db, rows, tom) if t.tracker.name == "Swaps desk rollout")
    answer = check_answer(db, rows, tom, tracker)
    assert answer.text == "Yes, as Editor."
    assert len(answer.routes) == 2 and answer.highest_wins


def test_the_check_answers_no_with_the_trackers_team(db, swaps, tracker_factory, team_factory):  # noqa: F811
    rows = load_team_rows(db)
    ana = swaps["people"]["Ana Silva"]  # Editor of London Swaps only
    rates = db.query(Tracker).filter_by(name="Rates laptop refresh").one()
    answer = check_answer(db, rows, ana, rates)
    assert answer.text == (
        "Rates laptop refresh belongs to EMEA Rates. Ana is not in that team or any team above it, and has no other "
        "access to it."
    )
    lone = tracker_factory(name="Loose tracker")
    assert check_answer(db, rows, ana, lone).text == "Loose tracker is in no team. Ana has no access to it."


def test_an_inactive_person_has_no_access(db, swaps):  # noqa: F811
    lee = swaps["people"]["Lee Chen"]
    lee.status = "disabled"
    db.commit()
    rows = load_team_rows(db)
    assert person_trackers(db, rows, lee) == []
    tracker = db.query(Tracker).filter_by(name="Swaps desk rollout").one()
    assert check_answer(db, rows, lee, tracker).text == "No. Lee is inactive, so has no access to any tracker."


def test_rights_list_each_set_with_what_it_allows(db, user_factory, give_set, team_factory, add_member):
    pat = user_factory(full_name="Pat Lead")
    give_set(["manage_teams", "view_activity"], user=pat, name="Leads")
    office = team_factory("PMO Office")
    add_member(office, pat, "viewer")
    give_set(["create_trackers"], team=office, name="PMO")
    rights = person_rights(db, pat)
    assert [(r.source, r.permissions) for r in rights] == [
        ("Set Leads, held directly", ["Manage teams", "View activity"]),
        ("Set PMO, held by team PMO Office", ["Create trackers"]),
    ]
    assert person_rights(db, user_factory(full_name="No One")) == []
