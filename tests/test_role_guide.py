"""What each role can do: the table in the app, and that it matches what the app enforces (database)."""

from __future__ import annotations

import re
from datetime import date
from html import unescape

import pytest
from conftest import browser_sign_in, post
from playwright.sync_api import expect
from test_report_page_browser import RECORDER

from tracker.auth.role_guide import NOT_IN_GUIDE, ROLE_GUIDE, role_guide_rows
from tracker.models import Group

ROW_TEXTS = [
    "Open the report and download it as PDF or PNG",
    "Record, edit and delete entries; download entries",
    "Write the weekly update; set a calendar reminder",
    "Add, edit and delete risks; set weekly targets",
    "Set a group's status, planned date, ready figure and comment",
    "Add, retire, delete and reorder groups; change a group's name, baseline and starting figure",
    "Change the tracker's settings",
    "Preview, test and send the report email",
]


@pytest.fixture
def tracker(tracker_factory):
    return tracker_factory(first_week_ending=date(2026, 9, 4), last_week_ending=date(2026, 12, 25))


def test_every_row_matches_the_role_its_routes_require(app):
    for row in ROLE_GUIDE:
        for endpoint in row.endpoints:
            view = app.view_functions[endpoint]
            assert getattr(view, "required_role", None) == row.role, f"{endpoint} does not require {row.role}"


def test_every_tracker_route_is_in_the_table_or_listed_with_a_reason(app):
    tracker_routes = {name for name, view in app.view_functions.items() if getattr(view, "required_role", None)}
    in_rows = {endpoint for row in ROLE_GUIDE for endpoint in row.endpoints}
    assert tracker_routes - in_rows - set(NOT_IN_GUIDE) == set(), "add the new route to a row or to NOT_IN_GUIDE"
    assert in_rows <= tracker_routes and set(NOT_IN_GUIDE) <= tracker_routes  # no stale names


@pytest.mark.parametrize("action", ["create", "delete", "retire", "up"])
def test_the_owner_only_location_actions_are_refused_to_editors(client, db, logged_in_user, grant, tracker, action):
    grant(logged_in_user, tracker, "editor")
    group = Group(tracker_id=tracker.id, name="Site A", baseline=0)
    db.add(group)
    db.commit()
    response = post(
        client, f"/trackers/{tracker.id}/groups", {"action": action, "group_id": group.id, "name": "B", "baseline": "1"}
    )
    assert response.status_code == 403


def test_the_rows_read_as_agreed_and_take_the_trackers_own_label():
    rows = role_guide_rows()
    assert [r["text"] for r in rows] == ROW_TEXTS
    assert [(r["viewer"], r["editor"], r["owner"]) for r in rows] == [(True, True, True)] + [
        (False, True, True)
    ] * 4 + [(False, False, True)] * 3
    sites = role_guide_rows("Site", "Sites")
    assert sites[4]["text"] == "Set a site's status, planned date, ready figure and comment"
    assert (
        sites[5]["text"] == "Add, retire, delete and reorder sites; change a site's name, baseline and starting figure"
    )


def _page(client, url):
    response = client.get(url)
    assert response.status_code == 200
    return response.get_data(as_text=True)


@pytest.mark.parametrize("role", ["viewer", "editor", "owner"])
def test_every_tracker_page_shows_your_role_and_the_table(client, logged_in_user, grant, tracker, role):
    grant(logged_in_user, tracker, role)
    html = _page(client, f"/trackers/{tracker.id}/report")
    assert f"Your role: <strong>{role.title()}</strong>" in html
    assert f'href="/trackers/{tracker.id}/role-guide" data-role-guide title="What each role can do">' in html
    assert '<span class="sr-only">What each role can do</span></a>' in html  # an information icon, named for readers
    dialog = unescape(re.search(r'<dialog id="role-guide-dialog".*?</dialog>', html, re.S).group(0))
    for text in ROW_TEXTS:  # in the tracker's own words: the test tracker calls its groups "Location"
        assert text.replace("group", "location") in dialog
    assert "Administrators can do everything on every tracker, including archiving it." in dialog
    assert "An archived tracker cannot be changed by anyone." in dialog


def test_an_administrator_sees_owner_administrator(client, logged_in_admin, tracker):
    assert "Your role: <strong>Owner (administrator)</strong>" in _page(client, f"/trackers/{tracker.id}/report")


def test_the_table_has_its_own_page_for_anyone_with_a_role(client, logged_in_user, grant, tracker, tracker_factory):
    grant(logged_in_user, tracker, "viewer")
    html = _page(client, f"/trackers/{tracker.id}/role-guide")
    assert '<h2 id="role-guide-heading">What each role can do</h2>' in html and ROW_TEXTS[-1] in html
    other = tracker_factory(first_week_ending=date(2026, 9, 4), last_week_ending=date(2026, 12, 25))
    assert client.get(f"/trackers/{other.id}/role-guide").status_code == 404


def test_where_roles_are_given_the_table_folds_out(client, logged_in_admin, tracker, team_factory, region_factory):
    for url in (f"/trackers/{tracker.id}/roles", f"/admin/teams/{team_factory().id}"):
        html = _page(client, url)
        assert '<details class="role-guide-foldout">' in html and ROW_TEXTS[0] in html, url
        assert "role-legend" not in html
    region = region_factory()
    assert '<details class="role-guide-foldout">' in _page(client, f"/admin/regions/{region.id}/access")


@pytest.mark.browser
def test_the_link_opens_the_table_in_a_pop_up(page, live_server, user_factory, grant, tracker):
    viewer = user_factory()
    grant(viewer, tracker, "viewer")
    page.add_init_script(RECORDER)
    browser_sign_in(page, live_server, viewer)
    page.goto(f"{live_server}/trackers/{tracker.id}/report")
    page.get_by_role("link", name="What each role can do").click()
    dialog = page.locator("#role-guide-dialog")
    expect(dialog).to_be_visible()
    expect(dialog.locator("tbody tr")).to_have_count(len(ROW_TEXTS))
    assert f"/trackers/{tracker.id}/report" in page.url  # stayed on the page
    dialog.get_by_role("button", name="Close").click()
    expect(dialog).to_be_hidden()
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert page.evaluate("window.__csp") == [] and page.evaluate("window.__errors") == []
