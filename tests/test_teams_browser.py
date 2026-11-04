"""The team move preview and confirmation in a real browser, under the Content Security Policy (database)."""

from __future__ import annotations

import pytest
from conftest import browser_sign_in
from playwright.sync_api import expect
from test_report_page_browser import RECORDER

pytestmark = pytest.mark.browser


def test_move_preview_then_confirm(page, live_server, team_factory, user_factory, tracker_factory, add_member):
    infra = team_factory(name="Infrastructure")
    apps = team_factory(name="Applications")
    windows = team_factory(name="Windows", parent=infra)
    tracker_factory(name="Laptop refresh", team_id=windows.id)
    add_member(infra, user_factory(full_name="Head of Infrastructure"), "owner")
    admin = user_factory(is_admin=True)
    page.add_init_script(RECORDER)
    browser_sign_in(page, live_server, admin)
    page.goto(f"{live_server}/admin/teams/{windows.id}")

    page.click("text=Move…")
    page.select_option("#parent_id", str(apps.id))
    page.click("text=Show what changes")
    expect(page.locator("main, body").first).to_contain_text("Head of Infrastructure loses Owner on Laptop refresh.")
    expect(page.locator("body")).to_contain_text("No one gains access.")
    page.get_by_role("button", name="Move Windows").click()
    page.wait_for_load_state("networkidle")

    expect(page.locator(".flash")).to_contain_text("Moved Windows to Applications.")
    expect(page.locator(".teams-crumb")).to_contain_text("Applications › Windows")
    assert page.evaluate("window.__csp") == []
    assert page.evaluate("window.__errors") == []


def _open(page, live_server, admin, url):
    page.add_init_script(RECORDER)
    browser_sign_in(page, live_server, admin)
    page.goto(f"{live_server}{url}")


def _clean(page):
    assert page.evaluate("window.__csp") == []
    assert page.evaluate("window.__errors") == []


def test_tree_filter_matches_team_and_person_names(page, live_server, team_factory, user_factory, add_member):
    infra = team_factory(name="Infrastructure")
    windows = team_factory(name="Windows", parent=infra)
    team_factory(name="Applications")
    add_member(windows, user_factory(full_name="Lena Lead"), "owner")
    _open(page, live_server, user_factory(is_admin=True), f"/admin/teams/{windows.id}")

    tree = page.locator("[data-tree]")
    box = page.locator("input[data-tree-filter]")
    expect(box).to_be_visible()
    box.fill("lead")
    expect(tree.get_by_role("link", name="Infrastructure")).to_be_visible()
    expect(tree.get_by_role("link", name="Windows")).to_be_visible()
    expect(tree.get_by_role("link", name="Applications")).to_be_hidden()
    box.fill("")
    expect(tree.get_by_role("link", name="Applications")).to_be_visible()
    _clean(page)


def test_role_change_saves_on_select(page, live_server, team_factory, user_factory, add_member):
    windows = team_factory(name="Windows")
    mia = user_factory(full_name="Mia Member")
    add_member(windows, mia, "viewer")
    _open(page, live_server, user_factory(is_admin=True), f"/admin/teams/{windows.id}")

    expect(page.get_by_role("button", name="Set role")).to_be_hidden()
    page.select_option(f"#role-{mia.id}", "owner")
    page.wait_for_load_state("networkidle")
    expect(page.locator(".flash")).to_contain_text("Mia Member is now owner in Windows.")
    _clean(page)


def test_people_filter_buttons(page, live_server, team_factory, user_factory, add_member):
    infra = team_factory(name="Infrastructure")
    windows = team_factory(name="Windows", parent=infra)
    add_member(infra, user_factory(full_name="Hana Head"), "owner")
    add_member(windows, user_factory(full_name="Mia Member"), "viewer")
    _open(page, live_server, user_factory(is_admin=True), f"/admin/teams/{windows.id}")

    rows = page.locator("table[data-row-filter-target] tr[data-route]")
    expect(rows).to_have_count(2)
    page.get_by_role("button", name="From teams above").click()
    expect(page.get_by_role("row", name="Mia Member")).to_be_hidden()
    expect(page.get_by_role("row", name="Hana Head")).to_be_visible()
    expect(page.get_by_role("button", name="From teams above")).to_have_attribute("aria-pressed", "true")
    page.get_by_role("button", name="All (2)").click()
    expect(page.get_by_role("row", name="Mia Member")).to_be_visible()
    _clean(page)


def test_add_member_person_filter(page, live_server, team_factory, user_factory):
    windows = team_factory(name="Windows")
    user_factory(full_name="Alice Aardvark")
    user_factory(full_name="Zed Zebra")
    _open(page, live_server, user_factory(is_admin=True), f"/admin/teams/{windows.id}")

    page.locator("input[data-select-filter=user_id]").fill("zebra")
    assert "Zed Zebra" in page.eval_on_selector("#user_id", "s => s.selectedOptions[0].text")
    _clean(page)


def test_team_page_does_not_scroll_sideways(page, live_server, team_factory, user_factory, add_member):
    infra = team_factory(name="Infrastructure")
    windows = team_factory(name="Windows", parent=infra)
    add_member(infra, user_factory(full_name="Hana Head", email="a.very.long.address@example.com"), "owner")
    add_member(windows, user_factory(full_name="Mia Member"), "viewer")
    _open(page, live_server, user_factory(is_admin=True), f"/admin/teams/{windows.id}")
    for width in (390, 1440):
        page.set_viewport_size({"width": width, "height": 900})
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth"), width


def test_tracker_access_filters_and_gives_a_role(
    page, live_server, db, team_factory, user_factory, tracker_factory, add_member
):
    from tracker.models import TrackerRole

    windows = team_factory(name="Windows")
    t = tracker_factory(name="Patching", team_id=windows.id)
    add_member(windows, user_factory(full_name="Tara Team"), "viewer")
    dina = user_factory(full_name="Dina Direct")
    db.add(TrackerRole(user_id=dina.id, tracker_id=t.id, role="editor"))
    db.commit()
    user_factory(full_name="Alice Aardvark")
    zed = user_factory(full_name="Zed Zebra")
    _open(page, live_server, user_factory(is_admin=True), f"/trackers/{t.id}/roles")

    page.get_by_role("button", name="Teams (").click()
    expect(page.get_by_role("row", name="Dina Direct")).to_be_hidden()
    expect(page.get_by_role("row", name="Tara Team")).to_be_visible()
    page.get_by_role("button", name="All (").click()
    expect(page.get_by_role("row", name="Dina Direct")).to_be_visible()

    page.locator("input[data-select-filter=user_id]").fill("zebra")
    assert "Zed Zebra" in page.eval_on_selector("#user_id", "s => s.selectedOptions[0].text")
    page.select_option("#user_id", str(zed.id))
    page.select_option("#role", "viewer")
    page.get_by_role("button", name="Give access").click()
    page.wait_for_load_state("networkidle")
    expect(page.locator(".flash")).to_contain_text("Updated access for Zed Zebra.")
    _clean(page)


def test_add_member_form_labels_and_button_line_up(page, live_server, team_factory, user_factory, tracker_factory):
    team = team_factory(name="Windows")
    tracker = tracker_factory(name="Laptop refresh", team_id=team.id)
    user_factory(full_name="Candidate One")
    admin = user_factory(is_admin=True)
    page.add_init_script(RECORDER)
    browser_sign_in(page, live_server, admin)
    for url, form in (
        (f"/admin/teams/{team.id}", "form.team-add"),
        (f"/trackers/{tracker.id}/roles", "form.team-add"),
    ):
        page.goto(live_server + url)
        top = lambda selector: page.locator(f"{form} {selector}").first.bounding_box()["y"]  # noqa: E731
        assert abs(top("label[for=user_id]") - top("label[for=role]")) < 1
        assert abs(top("select#user_id") - top("select#role")) < 1
        assert abs(top("select#user_id") - top("button[type=submit]")) < 3
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_new_team_location_narrows_to_the_chosen_region(
    page, live_server, user_factory, region_factory, location_factory
):
    emea, apac = region_factory("EMEA"), region_factory("APAC")
    geneva = location_factory(emea)
    singapore = location_factory(apac, city="Singapore", country_code="SG")
    _open(page, live_server, user_factory(is_admin=True), "/admin/teams")

    def shown_groups():
        return page.eval_on_selector_all(
            "#location_id optgroup", "groups => groups.filter(g => !g.hidden).map(g => g.dataset.region)"
        )

    assert shown_groups() == []
    page.select_option("#region_id", str(emea.id))
    assert shown_groups() == [str(emea.id)]
    page.select_option("#location_id", str(geneva.id))
    page.select_option("#region_id", str(apac.id))
    assert shown_groups() == [str(apac.id)]
    assert page.eval_on_selector("#location_id", "s => s.value") == ""
    page.select_option("#location_id", str(singapore.id))
    page.fill("#name", "Desktop")
    page.get_by_role("button", name="Create team").click()
    page.wait_for_load_state("networkidle")
    expect(page.locator(".flash")).to_contain_text("Created the team Desktop.")
    expect(page.locator(".team-header")).to_contain_text("APAC · Singapore, Singapore")
    expect(page.locator("[data-tree] .team-place").first).to_have_text("APAC · Singapore")
    page.set_viewport_size({"width": 390, "height": 900})
    page.goto(page.url.split("#")[0] + "#details")
    expect(page.locator("#location_id")).to_be_visible()
    assert page.eval_on_selector("#location_id", "s => s.value") == str(singapore.id)
    for url in (page.url, f"{live_server}/admin/teams"):
        page.goto(url)
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth"), url
    _clean(page)
