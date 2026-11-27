"""The Teams person view in a browser: finding a person from the Structure card, and "Can … see" choosing a tracker,
without a Content Security Policy violation or a script error (database)."""

from __future__ import annotations

import pytest
from playwright.sync_api import expect
from test_teams_new_view import swaps  # noqa: F401  (the fixture)
from test_teams_structure_browser import admin_page, clean  # noqa: F401  (the fixture)

pytestmark = pytest.mark.browser


def test_the_search_finds_a_person_and_opens_their_view(admin_page, live_server, swaps):  # noqa: F811
    admin_page.goto(f"{live_server}/admin/teams/{swaps['team'].id}")
    admin_page.get_by_label("Find a team or person").fill("priya")
    results = admin_page.locator("[data-people-results]")
    expect(results).to_be_visible()
    expect(results.get_by_role("link")).to_have_count(1)
    results.get_by_role("link", name="Priya Nair").click()
    expect(admin_page.get_by_role("heading", name="Priya Nair")).to_be_visible()
    expect(admin_page.locator(".person-mark.is-member")).to_have_text("Member · Owner")
    admin_page.get_by_label("Find a team or person").fill("")
    expect(results).to_be_hidden()
    clean(admin_page)


def test_choosing_a_tracker_answers_at_once(admin_page, live_server, swaps):  # noqa: F811
    tom = swaps["people"]["Tom Becker"]
    admin_page.goto(f"{live_server}/admin/teams/people/{tom.id}")
    expect(admin_page.get_by_role("button", name="Check")).to_be_hidden()
    with admin_page.expect_navigation():
        admin_page.get_by_label("Can Tom see…").select_option(label="Swaps desk rollout")
    answer = admin_page.locator(".person-answer")
    expect(answer).to_contain_text("Yes, as Editor.")
    expect(answer).to_contain_text("The highest role wins.")
    clean(admin_page)


def test_the_person_view_fits_a_phone(admin_page, live_server, swaps):  # noqa: F811
    admin_page.set_viewport_size({"width": 390, "height": 844})
    admin_page.goto(f"{live_server}/admin/teams/people/{swaps['people']['Tom Becker'].id}")
    assert admin_page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    clean(admin_page)


def test_the_reasons_wrap_inside_the_table(admin_page, live_server, swaps):  # noqa: F811
    admin_page.goto(f"{live_server}/admin/teams/people/{swaps['people']['Tom Becker'].id}")
    table = admin_page.locator("#person-trackers ~ .section-table").bounding_box()
    for item in admin_page.locator(".person-routes li").all():
        rect = item.bounding_box()
        assert rect["x"] + rect["width"] <= table["x"] + table["width"] + 1
    clean(admin_page)
