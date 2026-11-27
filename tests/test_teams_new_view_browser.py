"""The Teams New view in a browser: the New team panel, the role switch, the Add a member preview,
and phone width, each without a Content Security Policy violation or a script error (database)."""

from __future__ import annotations

import pytest
from conftest import browser_sign_in
from playwright.sync_api import expect
from test_report_page_browser import RECORDER
from test_teams_new_view import swaps  # noqa: F401  (the fixture)

from tracker.models import Team
from tracker.teams.tree import load_team_rows

pytestmark = pytest.mark.browser


@pytest.fixture
def admin_page(page, live_server, user_factory):
    page.add_init_script(RECORDER)
    browser_sign_in(page, live_server, user_factory(is_admin=True, full_name="Admin Person"))
    page.goto(f"{live_server}/admin/teams?view=new")  # the New view is kept for the rest of the test
    return page


def clean(page):
    assert page.evaluate("window.__csp") == [] and page.evaluate("window.__errors") == []


def test_new_team_form_opens_in_place_and_fills_the_place(
    admin_page,
    live_server,
    db,
    swaps,  # noqa: F811
    region_factory,
    location_factory,
):
    region = region_factory("EMEA")
    london = location_factory(region, "London", "GB", code="LON")
    rates = swaps["rates"]
    rates.region_id, rates.location_id = region.id, london.id
    db.commit()
    admin_page.goto(f"{live_server}/admin/teams/{swaps['top'].id}")
    form = admin_page.locator("#new-team-form")
    expect(form).to_be_hidden()
    admin_page.get_by_role("link", name="New team").click()
    expect(form).to_be_visible()
    assert admin_page.url.endswith(f"/admin/teams/{swaps['top'].id}")  # opened in place
    expect(admin_page.locator("#name")).to_be_focused()
    admin_page.locator("#name").fill("Rates Ops")
    admin_page.locator("#parent_id").select_option(str(rates.id))
    expect(admin_page.locator("#region_id")).to_have_value(str(region.id))
    expect(admin_page.locator("#location_id")).to_have_value(str(london.id))
    expect(form.get_by_text("Filled from EMEA Rates.")).to_be_visible()
    form.get_by_role("button", name="Create team").click()
    expect(admin_page.locator("h2.team-simple-name")).to_have_text("Rates Ops")  # its page
    created = db.query(Team).filter_by(name="Rates Ops").one()
    assert next(r for r in load_team_rows(db) if r.id == created.id).parent_ids == (rates.id,)
    clean(admin_page)


def test_cancel_hides_the_new_team_form(admin_page, live_server, swaps):  # noqa: F811
    admin_page.goto(f"{live_server}/admin/teams/{swaps['top'].id}")
    admin_page.get_by_role("link", name="New team").click()
    admin_page.locator("#new-team-form").get_by_role("link", name="Cancel").click()
    expect(admin_page.locator("#new-team-form")).to_be_hidden()
    clean(admin_page)


def test_structure_search_filters_teams(admin_page, live_server, swaps, team_factory):  # noqa: F811
    team_factory("Other Desk")
    admin_page.goto(f"{live_server}/admin/teams/{swaps['top'].id}")
    admin_page.get_by_label("Find a team or person").fill("swaps")
    card = admin_page.locator(".structure-card")
    expect(card.locator(".structure-node", has_text="London Swaps")).to_be_visible()
    expect(card.locator(".structure-node", has_text="Global Markets")).to_be_visible()  # its parents stay
    expect(card.locator(".structure-node", has_text="Other Desk")).to_be_hidden()
    clean(admin_page)


def test_no_page_scrolls_sideways_at_phone_width(admin_page, live_server, swaps):  # noqa: F811
    admin_page.set_viewport_size({"width": 390, "height": 844})
    team = swaps["team"]
    for url in (
        f"/admin/teams/{team.id}?new=1",
        f"/admin/teams/{team.id}",
        "/admin/teams/structure",
        f"/admin/teams/{team.id}/sits",
        f"/admin/teams/{team.id}#whole-structure",  # the Whole structure layer open
    ):
        admin_page.goto(f"{live_server}{url}")
        assert admin_page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), url
    clean(admin_page)


def test_where_it_sits_editor_end_to_end(admin_page, live_server, db, team_factory):
    a, b = team_factory("A"), team_factory("B")
    t = team_factory("T", parent=a)
    admin_page.goto(f"{live_server}/admin/teams/{t.id}")
    admin_page.get_by_role("link", name="Change where it sits").click()
    editor = admin_page.locator(".sits-editor")
    expect(editor.get_by_role("heading", name="Where T sits")).to_be_visible()
    editor.get_by_label("Add a team above").select_option(str(b.id))
    editor.get_by_role("button", name="Add", exact=True).click()
    expect(editor.locator(".sits-row")).to_have_count(2)
    editor.locator(".sits-row", has_text="B").get_by_role("button", name="Make main").click()
    expect(editor.locator(".sits-row.is-main")).to_contain_text("B")
    expect(editor).to_contain_text("No change in who can see its trackers.")
    editor.get_by_role("button", name="Save").click()
    expect(admin_page.get_by_text("Saved where T sits.")).to_be_visible()
    b_item = admin_page.locator(".structure-card li", has=admin_page.locator(".structure-node", has_text="B")).first
    expect(b_item.locator(".structure-node", has_text="T")).to_be_visible()
    clean(admin_page)


def test_a_wide_screen_keeps_the_standard_page_width(admin_page, live_server, swaps):  # noqa: F811
    admin_page.set_viewport_size({"width": 1920, "height": 1000})
    admin_page.goto(f"{live_server}/admin/teams/{swaps['team'].id}")
    for selector in (".teams-simple-head", ".teams-simple-layout"):
        assert admin_page.locator(selector).bounding_box()["width"] <= 1280, selector
    clean(admin_page)
