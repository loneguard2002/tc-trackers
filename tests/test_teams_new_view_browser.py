"""The Teams New view in a browser: the chart search, the New team panel, the role switch, the Add a member preview,
and phone width, each without a Content Security Policy violation or a script error (database)."""

from __future__ import annotations

import re

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
    admin_page.goto(f"{live_server}/admin/teams/structure")
    admin_page.get_by_label("Find a team or person").fill("swaps")
    expect(admin_page.locator("li.is-match > .org-node")).to_have_count(1)
    expect(admin_page.locator("li.is-match > .org-node")).to_contain_text("London Swaps")
    admin_page.get_by_label("Find a team or person").fill("priya")  # a member's name finds their team
    expect(admin_page.locator("li.is-match > .org-node")).to_contain_text("EMEA Rates")
    clean(admin_page)


def test_new_team_form_opens_in_place_and_fills_the_place(admin_page, live_server, db, swaps, region_factory, location_factory):  # noqa: F811
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

def test_the_chart_draws_a_dotted_line_from_the_other_higher_team(admin_page, live_server, team_factory):
    alpha, beta = team_factory("Alpha"), team_factory("Beta")
    shared = team_factory("Shared", parents=(alpha, beta))
    team_factory("Solo", parent=alpha)
    admin_page.goto(f"{live_server}/admin/teams/structure")
    lines = admin_page.locator("[data-chart-links] path")
    expect(lines).to_have_count(1)
    assert lines.get_attribute("data-from") == str(beta.id) and lines.get_attribute("data-to") == str(shared.id)
    # The line starts at Beta's box and ends at Shared's, below it.
    beta_box = admin_page.locator(f'.org-node[data-team-id="{beta.id}"]').bounding_box()
    shared_box = admin_page.locator(f'.org-node[data-team-id="{shared.id}"]').bounding_box()
    end = admin_page.locator("[data-chart-links] circle").bounding_box()
    assert abs(end["y"] + end["height"] / 2 - shared_box["y"]) < 3
    assert shared_box["y"] > beta_box["y"] + beta_box["height"]
    # Pointing at Shared lights its line and marks Beta.
    admin_page.locator(f'.org-node[data-team-id="{shared.id}"]').hover()
    expect(lines).to_have_class("is-lit")
    expect(admin_page.locator(f'.org-node[data-team-id="{beta.id}"]')).to_have_class(re.compile("is-linked"))
    # The switch hides the lines, and the choice is kept.
    toggle = admin_page.get_by_label("Show “also under” lines")
    expect(toggle).to_be_checked()
    toggle.uncheck()
    expect(lines).to_be_hidden()
    admin_page.reload()
    expect(admin_page.get_by_label("Show “also under” lines")).not_to_be_checked()
    expect(admin_page.locator("[data-chart-links] path")).to_be_hidden()
    clean(admin_page)


def test_no_switch_without_a_team_under_two_teams(admin_page, live_server, swaps):  # noqa: F811
    admin_page.goto(f"{live_server}/admin/teams/structure")
    expect(admin_page.locator(".org-node").first).to_be_visible()
    expect(admin_page.locator("[data-links-toggle]")).to_be_hidden()
    expect(admin_page.locator("[data-chart-links] path")).to_have_count(0)
    clean(admin_page)


def test_the_dotted_lines_are_left_out_at_phone_width(admin_page, live_server, team_factory):
    alpha, beta = team_factory("Alpha"), team_factory("Beta")
    team_factory("Shared", parents=(alpha, beta))
    admin_page.set_viewport_size({"width": 390, "height": 844})
    admin_page.goto(f"{live_server}/admin/teams/structure")
    expect(admin_page.get_by_text("Also under Beta")).to_be_visible()
    expect(admin_page.locator("[data-chart-links]")).to_be_hidden()
    expect(admin_page.locator("[data-links-toggle]")).to_be_hidden()
    clean(admin_page)


def test_no_page_scrolls_sideways_at_phone_width(admin_page, live_server, swaps):  # noqa: F811
    admin_page.set_viewport_size({"width": 390, "height": 844})
    team = swaps["team"]
    for url in (
        f"/admin/teams/{team.id}?new=1",
        f"/admin/teams/{team.id}",
        "/admin/teams/structure",
        f"/admin/teams/{team.id}/parents?to={swaps['top'].id}&how=move",
    ):
        admin_page.goto(f"{live_server}{url}")
        assert admin_page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), url
    clean(admin_page)


