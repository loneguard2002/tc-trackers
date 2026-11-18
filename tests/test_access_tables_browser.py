"""The Access tables in a real browser: a tracker's Access list and a person's Access page (database)."""

from __future__ import annotations

import pytest
from conftest import browser_sign_in
from playwright.sync_api import expect
from test_report_page_browser import RECORDER

from tracker.models import TrackerRegion

pytestmark = pytest.mark.browser


def _clean(page):
    assert page.evaluate("window.__csp") == []
    assert page.evaluate("window.__errors") == []


def _foot(page, table_id):
    return " ".join(page.locator(f'[data-pager-for="{table_id}"] [data-pager-count]').inner_text().split())


def _chips(page):
    return [" ".join(t.split()) for t in page.locator("[data-status-for] .chip").all_inner_texts()]


def test_the_tracker_access_list_searches_filters_sorts_and_keeps_its_actions(
    page, live_server, user_factory, tracker_factory, grant
):
    tracker = tracker_factory()
    for name, role in (
        ("Ann Editor", "editor"),
        ("Bob Viewer", "viewer"),
        ("Cy Owner", "owner"),
        ("Dee Viewer", "viewer"),
    ):
        grant(user_factory(full_name=name, email=f"{name.split()[0].lower()}@example.com"), tracker, role)
    page.add_init_script(RECORDER)
    browser_sign_in(page, live_server, user_factory(is_admin=True, full_name="Ada Admin"))
    page.goto(f"{live_server}/trackers/{tracker.id}/roles")
    rows = page.locator("#access-table tbody tr:visible")
    expect(page.locator("[data-row-filter]")).to_have_count(0)
    expect(rows).to_have_count(5)
    assert _chips(page) == ["All 5", "Owner 2", "Editor 1", "Viewer 2"]  # the administrator counts as an owner
    assert _foot(page, "access-table") == "Showing 5 of 5 people"

    page.locator("#access-table-search").fill("dee@")  # the email counts as well as the name
    expect(rows).to_have_count(1)
    assert _chips(page) == ["All 1", "Owner 0", "Editor 0", "Viewer 1"]
    assert "q=dee" in page.url
    page.get_by_role("button", name="Clear filters").first.click()
    expect(rows).to_have_count(5)

    page.locator('[data-status-for] button[data-status="viewer"]').click()
    expect(rows).to_have_count(2)
    assert "filter=viewer" in page.url
    page.locator('[data-status-for] button[data-status="all"]').click()

    page.locator('#access-table button[data-sort="role"]').click()
    first = rows.first.locator(".member-name").inner_text()
    assert first in ("Bob Viewer", "Dee Viewer")  # viewers first, then editor, then owners
    page.locator('#access-table button[data-sort="role"]').click()
    assert rows.first.locator(".member-name").inner_text() in ("Ada Admin", "Cy Owner")
    page.locator('#access-table button[data-sort="person"]').click()
    assert rows.first.locator(".member-name").inner_text() == "Ada Admin"

    # The row's own actions are untouched.
    expect(page.get_by_label("Role for Ann Editor")).to_be_visible()
    expect(page.get_by_role("button", name="Remove access")).to_have_count(4)
    _clean(page)


def test_a_persons_access_page_has_two_sortable_tables_with_their_own_keys(
    page, live_server, user_factory, tracker_factory, grant, give_set
):
    person = user_factory(full_name="Priya Shah")
    grant(person, tracker_factory(name="Alpha tracker"), "viewer")
    grant(person, tracker_factory(name="Beta tracker"), "owner")
    give_set(["view_activity", "manage_users"], user=person, name="PMO")
    page.add_init_script(RECORDER)
    browser_sign_in(page, live_server, user_factory(is_admin=True))
    page.goto(f"{live_server}/admin/users/{person.id}/access")
    trackers = page.locator("#access-trackers-table")
    permissions = page.locator("#access-permissions-table")
    expect(page.locator("[data-search-for], [data-status-for]")).to_have_count(0)  # sorting and the count line only
    assert _foot(page, "access-trackers-table") == "Showing 2 of 2 trackers"
    assert _foot(page, "access-permissions-table") == "Showing 2 of 2 permissions"

    trackers.locator('button[data-sort="tracker"]').click()
    trackers.locator('button[data-sort="tracker"]').click()
    assert trackers.locator("tbody .cell-title").all_inner_texts() == ["Beta tracker", "Alpha tracker"]
    permissions.locator('button[data-sort="permission"]').click()
    labels = permissions.locator("tbody .cell-title").all_inner_texts()
    assert labels == sorted(labels, key=str.lower)
    query = page.url.split("?", 1)[1]
    assert "trackers-sort=-tracker" in query and "permissions-sort=permission" in query
    page.reload()
    assert trackers.locator("tbody .cell-title").all_inner_texts() == ["Beta tracker", "Alpha tracker"]
    _clean(page)


def test_the_access_search_finds_a_person_by_route_words(
    page, live_server, db, user_factory, tracker_factory, region_factory, region_grant, grant
):
    tracker = tracker_factory()
    region = region_factory("EMEA")
    db.add(TrackerRegion(tracker_id=tracker.id, region_id=region.id))
    db.commit()
    region_grant(region, user_factory(full_name="Reg Viewer", email="reg@example.com"), "viewer")
    grant(user_factory(full_name="Dan Direct", email="dan@example.com"), tracker, "editor")
    page.add_init_script(RECORDER)
    browser_sign_in(page, live_server, user_factory(is_admin=True, full_name="Ada Admin"))
    page.goto(f"{live_server}/trackers/{tracker.id}/roles")
    rows = page.locator("#access-table tbody tr:visible")
    page.locator("#access-table-search").fill("region")
    expect(rows).to_have_count(1)
    expect(rows.first).to_contain_text("Reg Viewer")
    page.locator("#access-table-search").fill("direct")
    expect(rows).to_have_count(1)
    expect(rows.first).to_contain_text("Dan Direct")
    page.locator("#access-table-search").fill("administrator")
    expect(rows).to_have_count(1)
    expect(rows.first).to_contain_text("Ada Admin")
    expect(page.locator("[data-no-match]")).to_be_hidden()
    page.locator("#access-table-search").fill("zzz")
    expect(page.locator("[data-no-match]")).to_contain_text("No one matches.")
    _clean(page)
