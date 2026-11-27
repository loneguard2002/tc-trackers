"""The Teams person view (spec 2026-11-26-teams-simple-redesign-design.md 4.8): one person's teams, the trackers they
can see and why, "Can … see", and their rights (database)."""

from __future__ import annotations

import html as html_lib
import json
import re

import pytest
from test_teams_new_view import swaps  # noqa: F401  (the fixture)

from tracker.auth.roles import tracker_access_routes
from tracker.models import RegionGrant, Tracker, TrackerRegion
from tracker.teams.person import check_answer, person_rights, person_teams, person_trackers
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


# --- The page -------------------------------------------------------------------------------------------------------


def person_page(client, user, query: str = "") -> str:
    response = client.get(f"/admin/teams/people/{user.id}{query}")
    assert response.status_code == 200
    return html_lib.unescape(response.get_data(as_text=True))


def test_the_page_shows_figures_teams_trackers_and_rights(client, logged_in_admin, swaps, tom):  # noqa: F811
    html = person_page(client, tom)
    assert '<h2 id="person-name">Tom Becker' in html
    assert re.search(r"<strong>2</strong> <span>teams they are in", html)
    assert re.search(r"<strong>0</strong> <span>more teams they reach", html)
    assert re.search(r"<strong>2</strong> <span>trackers they can see", html)
    assert "Member of Global Markets › EMEA Rates (Editor)" in html
    assert "Rights in the app" in html and "None. Tom can only work in the trackers above." in html
    assert f'href="/admin/users/{tom.id}/access"' in html  # Open in Users, for an administrator


def test_the_structure_marks_the_persons_teams(client, logged_in_admin, swaps):  # noqa: F811
    sam = swaps["people"]["Sam Ortiz"]
    html = person_page(client, sam)
    assert "Showing Sam Ortiz's teams" in html and "Back to teams" in html
    assert '<span class="person-mark is-member">Member · Viewer</span>' in html
    assert html.count('<span class="person-mark is-through">Through Global Markets</span>') == 2


def test_check_answers_without_javascript(client, logged_in_admin, db, swaps):  # noqa: F811
    ana = swaps["people"]["Ana Silva"]
    rates = db.query(Tracker).filter_by(name="Rates laptop refresh").one()
    html = person_page(client, ana, f"?check={rates.id}")
    assert "Rates laptop refresh belongs to EMEA Rates. Ana is not in that team" in html
    assert f'<option value="{rates.id}" selected>' in html


def test_rights_and_open_in_users_need_manage_users(client, logged_in_user, give_set, swaps, tom):  # noqa: F811
    give_set(["manage_teams"], user=logged_in_user)
    html = person_page(client, tom)
    assert "Rights in the app" not in html and "sets of rights" not in html and "Open in Users" not in html
    give_set(["manage_users"], user=logged_in_user)
    html = person_page(client, tom)
    assert "Rights in the app" in html and "Open in Users" in html


def test_the_page_is_guarded(client, logged_in_user, db, swaps, tom):  # noqa: F811
    assert client.get(f"/admin/teams/people/{tom.id}").status_code == 403
    db.get(type(tom), logged_in_user.id).is_admin = True
    db.commit()
    assert client.get("/admin/teams/people/999999").status_code == 404
    tom.status = "deleted"
    db.commit()
    assert client.get(f"/admin/teams/people/{tom.id}").status_code == 404


def test_an_inactive_person_says_so(client, logged_in_admin, db, swaps):  # noqa: F811
    lee = swaps["people"]["Lee Chen"]
    lee.status = "disabled"
    db.commit()
    html = person_page(client, lee)
    assert (
        "While it is, the teams and sets below give no access." in html
        and "None while the account is disabled." in html
    )


def test_the_structure_card_offers_every_active_person(client, logged_in_admin, db, swaps, user_factory):  # noqa: F811
    user_factory(full_name="Nobody Inteams")
    user_factory(full_name="Gone Away", status="disabled")
    raw = client.get(f"/admin/teams/{swaps['team'].id}?view=new").get_data(as_text=True)
    people = json.loads(html_lib.unescape(re.search(r'data-people="([^"]*)"', raw).group(1)))  # escaped, never run
    names = [p["name"] for p in people]
    assert "Nobody Inteams" in names and "Gone Away" not in names and "Tom Becker" in names
    tom = swaps["people"]["Tom Becker"]
    assert {"name": "Tom Becker", "email": tom.email, "url": f"/admin/teams/people/{tom.id}"} in people


def test_names_in_the_people_list_open_the_person_view(client, logged_in_admin, swaps):  # noqa: F811
    tom = swaps["people"]["Tom Becker"]
    html = page_html(client, f"/admin/teams/{swaps['team'].id}?view=new")
    assert f'<a href="/admin/teams/people/{tom.id}">Tom Becker</a>' in html


def page_html(client, url: str) -> str:
    response = client.get(url)
    assert response.status_code == 200
    return html_lib.unescape(response.get_data(as_text=True))


@pytest.mark.parametrize("status", ["pending", "declined"])
def test_sign_up_requests_are_not_shown(client, logged_in_admin, user_factory, status):
    # A pending or declined access request is for Manage users (Users › Access requests), not a person in teams.
    request_user = user_factory(full_name="Asking Person", status=status)
    assert client.get(f"/admin/teams/people/{request_user.id}").status_code == 404


def test_an_inactive_administrator_has_no_rights_while_inactive(client, logged_in_admin, db, user_factory):
    admin = user_factory(full_name="Old Admin", is_admin=True, status="disabled")
    html = person_page(client, admin)
    assert "Administrator: every permission." not in html and "None while the account is disabled." in html
