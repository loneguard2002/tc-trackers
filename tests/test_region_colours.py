"""Each region's code shows in one of eight set colours, chosen on its Add and Edit forms (database)."""

from __future__ import annotations

import re

import pytest
from conftest import browser_sign_in, post
from playwright.sync_api import expect
from sqlalchemy import select
from test_report_page_browser import RECORDER

from tracker.lists.region_colours import REGION_COLOURS, next_colour
from tracker.lists.views import REGION_COLOUR_REQUIRED
from tracker.models import AuditLog, Region, TrackerRegion


def page_of(client, url: str) -> str:
    response = client.get(url)
    assert response.status_code == 200
    return response.get_data(as_text=True)


def test_a_new_region_takes_the_colour_fewest_regions_use(db, region_factory):
    assert next_colour(db) == 1
    region_factory("EMEA").colour = 1
    region_factory("APAC").colour = 2
    db.commit()
    assert next_colour(db) == 3
    for index, code in enumerate(("A3", "A4", "A5", "A6", "A7", "A8"), start=3):
        region_factory(code).colour = index
    db.commit()
    assert next_colour(db) == 1  # each used once: back to the first


def test_adding_a_region_saves_its_colour_and_logs_it_by_name(client, logged_in_admin, db):
    assert post(client, "/admin/regions", {"code": "EMEA", "name": "Europe", "colour": "5"}).status_code == 302
    region = db.scalars(select(Region)).one()
    assert region.colour == 5
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "region_created")).one()
    assert entry.detail == {"region": "EMEA", "colour": "Pink"}


def test_without_a_colour_a_new_region_takes_the_next_and_an_edit_keeps_its_own(
    client, logged_in_admin, db, region_factory
):
    region_factory("EMEA").colour = 1
    db.commit()
    assert post(client, "/admin/regions", {"code": "APAC", "name": "Asia"}).status_code == 302
    apac = db.scalars(select(Region).where(Region.code == "APAC")).one()
    assert apac.colour == 2
    assert (
        post(
            client, f"/admin/regions/{apac.id}", {"action": "save", "code": "APAC", "name": "Asia Pacific"}
        ).status_code
        == 302
    )
    db.refresh(apac)
    assert (apac.name, apac.colour) == ("Asia Pacific", 2)


@pytest.mark.parametrize("colour", ["0", "9", "blue", ""])
def test_a_colour_outside_the_set_is_refused(client, logged_in_admin, db, colour):
    response = post(client, "/admin/regions", {"code": "EMEA", "name": "Europe", "colour": colour})
    assert response.status_code == 400
    html = response.get_data(as_text=True)
    assert REGION_COLOUR_REQUIRED in html
    assert re.findall(r'value="\d" checked', html) == []  # no colour looks chosen beside "Choose a colour."
    assert db.scalars(select(Region)).all() == []


def test_changing_the_colour_is_saved_and_logged_by_name(client, logged_in_admin, db, region_factory):
    region = region_factory("EMEA")
    response = post(
        client, f"/admin/regions/{region.id}", {"action": "save", "code": "EMEA", "name": region.name, "colour": "3"}
    )
    assert response.status_code == 302
    db.refresh(region)
    assert region.colour == 3
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "region_changed")).one()
    assert (entry.detail["before"], entry.detail["after"]) == ({"colour": "Blue"}, {"colour": "Aqua"})


def test_the_regions_page_offers_the_swatches_and_shows_each_code_in_its_colour(
    client, logged_in_admin, db, region_factory
):
    region = region_factory("EMEA")
    region.colour = 4
    db.commit()
    html = page_of(client, "/admin/regions")
    assert (
        '<span class="code-badge region-c4"><span class="code-badge-mark" aria-hidden="true"></span>EMEA</span>' in html
    )
    add = re.search(r'id="add-dialog".*?</dialog>', html, re.S).group(0)
    names = re.findall(r'<span class="sr-only">(\w+)</span></label>', add)
    assert names == list(REGION_COLOURS)
    assert re.findall(r'value="(\d)" checked', add) == ["1"]  # the next colour, chosen to start with
    assert '"colour": 4' in html  # the row's data-edit, for the Edit dialog


def test_the_colour_follows_the_code_to_the_home_cards_and_the_team_page(
    client, logged_in_admin, db, region_factory, location_factory, team_factory, tracker_factory
):
    region = region_factory("EMEA")
    region.colour = 7
    tracker = tracker_factory(name="Rollout")
    db.add(TrackerRegion(tracker_id=tracker.id, region_id=region.id))
    london = location_factory(region, "London", "GB", code="LON")
    team = team_factory("London desk", location_id=london.id)
    db.commit()
    assert '<li class="region-pill region-c7">EMEA</li>' in page_of(client, "/")
    assert '<span class="region-mark region-c7" aria-hidden="true"></span><strong>EMEA</strong>' in page_of(
        client, f"/admin/teams/{team.id}"
    )
    assert '<span class="region-mark region-c7" aria-hidden="true"></span>EMEA' in page_of(client, "/admin/teams")


@pytest.mark.browser
def test_the_dialogs_choose_a_colour(page, live_server, db, user_factory, region_factory):
    emea = region_factory("EMEA")
    emea.colour = 6
    db.commit()
    page.add_init_script(RECORDER)
    browser_sign_in(page, live_server, user_factory(is_admin=True))
    page.goto(f"{live_server}/admin/regions")
    page.locator(f"#region-{emea.id} a.row-edit").click()
    dialog = page.locator("#edit-dialog")
    expect(dialog.get_by_role("radio", name="Green")).to_be_checked()
    dialog.get_by_role("radio", name="Violet").check(force=True)
    dialog.get_by_role("button", name="Save").click()
    expect(page.locator(f"#region-{emea.id} .code-badge.region-c7")).to_be_visible()
    db.refresh(emea)
    assert emea.colour == 7

    page.get_by_role("link", name="Add region").click()
    add = page.locator("#add-dialog")
    expect(add.get_by_role("radio", name="Blue")).to_be_checked()  # the colour no region uses yet
    expect(add.get_by_role("radio", name="Orange")).to_be_visible()
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert page.evaluate("window.__csp") == [] and page.evaluate("window.__errors") == []
