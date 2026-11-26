"""The Teams New view in a browser: the chart search, the New team panel, the role switch, the Add a member preview,
and phone width, each without a Content Security Policy violation or a script error (database)."""

from __future__ import annotations

import pytest
from conftest import browser_sign_in
from playwright.sync_api import expect
from test_report_page_browser import RECORDER
from test_teams_new_view import swaps  # noqa: F401  (the fixture)

from tracker.models import Team, TeamMember
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


def test_the_chart_search_marks_a_matching_team(admin_page, live_server, swaps):  # noqa: F811
    admin_page.goto(f"{live_server}/admin/teams")
    admin_page.get_by_label("Find a team or person").fill("swaps")
    expect(admin_page.locator("li.is-match > .org-node")).to_have_count(1)
    expect(admin_page.locator("li.is-match > .org-node")).to_contain_text("London Swaps")
    admin_page.get_by_label("Find a team or person").fill("priya")  # a member's name finds their team
    expect(admin_page.locator("li.is-match > .org-node")).to_contain_text("EMEA Rates")
    clean(admin_page)


def test_the_new_team_panel_fills_in_and_creates(admin_page, live_server, db, swaps, region_factory, location_factory):  # noqa: F811
    region = region_factory("EMEA")
    london = location_factory(region, "London", "GB", code="LON")
    rates = swaps["rates"]
    rates.region_id, rates.location_id = region.id, london.id
    db.commit()
    admin_page.goto(f"{live_server}/admin/teams")
    panel = admin_page.locator("#new-team-panel")
    expect(panel).to_be_hidden()
    admin_page.get_by_role("link", name="New team").click()
    expect(panel).to_be_visible()
    assert admin_page.url.endswith("/admin/teams")  # opened in place
    admin_page.locator("#name").fill("Rates Ops")
    panel.get_by_label("EMEA Rates").check()
    expect(admin_page.locator("#region_id")).to_have_value(str(region.id))
    expect(admin_page.locator("#location_id")).to_have_value(str(london.id))
    expect(panel.get_by_text("Filled from EMEA Rates.")).to_be_visible()
    expect(panel.locator(f'[data-reach-for="{rates.id}"]')).to_contain_text("Priya Nair · Owner · EMEA Rates")
    button = panel.get_by_role("button", name="Create Rates Ops under EMEA Rates")
    expect(button).to_be_visible()
    button.click()
    expect(admin_page.get_by_role("heading", name="Members of Rates Ops")).to_be_visible()  # its page
    created = db.query(Team).filter_by(name="Rates Ops").one()
    assert next(r for r in load_team_rows(db) if r.id == created.id).parent_ids == (rates.id,)
    clean(admin_page)


def test_a_role_saves_when_chosen(admin_page, live_server, db, swaps):  # noqa: F811
    team, ana = swaps["team"], swaps["people"]["Ana Silva"]
    admin_page.goto(f"{live_server}/admin/teams/{team.id}")
    switch = admin_page.locator(f'form.role-switch[action$="/members/{ana.id}"]')
    expect(switch.get_by_role("button", name="Set role")).to_be_hidden()
    with admin_page.expect_navigation():
        switch.get_by_text("Owner", exact=True).click()
    db.expire_all()
    assert db.get(TeamMember, (team.id, ana.id)).role == "owner"
    clean(admin_page)


def test_the_add_preview_follows_the_person_and_role(admin_page, live_server, swaps, user_factory):  # noqa: F811
    user_factory(full_name="Kim Patel")
    admin_page.goto(f"{live_server}/admin/teams/{swaps['rates'].id}")
    panel = admin_page.locator("#add-member")
    panel.locator("#user_id").select_option(
        label=next(o for o in panel.locator("#user_id option").all_inner_texts() if o.startswith("Kim Patel"))
    )
    panel.locator(".role-card", has_text="Editor").click()
    expect(panel.locator(".add-preview")).to_contain_text("Kim Patel will be an Editor on 2 trackers")
    clean(admin_page)


def test_no_page_scrolls_sideways_at_phone_width(admin_page, live_server, swaps):  # noqa: F811
    admin_page.set_viewport_size({"width": 390, "height": 844})
    team = swaps["team"]
    for url in (
        "/admin/teams?new=1",
        f"/admin/teams/{team.id}",
        f"/admin/teams/{team.id}/parents?to={swaps['top'].id}&how=move",
    ):
        admin_page.goto(f"{live_server}{url}")
        assert admin_page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), url
    clean(admin_page)
