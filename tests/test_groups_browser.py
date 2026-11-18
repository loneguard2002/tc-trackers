"""The tracker's Locations tab in a real browser, under the Content Security Policy (database): search, status chips,
sorting, the order buttons that show only in the owner's own order, and cards on a phone."""

from __future__ import annotations

from datetime import date

import pytest
from conftest import browser_sign_in
from playwright.sync_api import expect
from sqlalchemy import select
from test_report_page_browser import RECORDER

from tracker.models import Group

pytestmark = pytest.mark.browser

ROWS = "#groups-table tbody tr:visible"
NOTE = "Clear the sort and filters to change the order."


def _clean(page):
    assert page.evaluate("window.__csp") == []
    assert page.evaluate("window.__errors") == []


def _names(page):
    return page.locator(f"{ROWS} .cell-title").all_inner_texts()


def _foot(page):
    return " ".join(page.locator("[data-pager-count]").inner_text().split())


def _chip(page, status):
    return page.locator(f'[data-status-for] button[data-status="{status}"] [data-count]')


def _moves(page):
    return page.locator(f'{ROWS} button[aria-label^="Move"]:visible')


@pytest.fixture
def board(page, live_server, tracker_factory, user_factory, db):
    """Harbour (30 done, 25 ready... in owner order 1), Bridge, Castle (retired) and Dock, with progress to sort by."""
    tracker = tracker_factory(name="Rollout")
    rows = (
        ("Harbour", 40, 10, 5, date(2026, 12, 1), 1, False),
        ("Bridge", 100, 90, 0, None, 2, False),
        ("Castle", 20, 20, 0, date(2026, 10, 1), 3, True),
        ("Dock", 10, 2, 1, date(2026, 11, 1), 4, False),
    )
    for name, baseline, done, ready, planned, order, retired in rows:
        db.add(
            Group(
                tracker_id=tracker.id,
                name=name,
                baseline=baseline,
                starting_completed=done,
                ready_not_complete=ready,
                planned_completion=planned,
                sort_order=order,
                retired=retired,
            )
        )
    db.commit()
    page.add_init_script(RECORDER)
    browser_sign_in(page, live_server, user_factory(is_admin=True))
    page.goto(f"{live_server}/trackers/{tracker.id}/groups")
    return tracker


def test_one_table_in_the_owners_order_with_chips_and_footer(page, board):
    assert _names(page) == ["Harbour", "Bridge", "Castle", "Dock"]
    assert page.locator("#groups-table").count() == 1
    assert page.locator("details.closed-block").count() == 0
    for status, count in (("all", "4"), ("active", "3"), ("retired", "1")):
        expect(_chip(page, status)).to_have_text(count)
    assert _foot(page) == "Showing 4 of 4 locations · 3 active"
    page.locator('button[data-status="retired"]').click()
    assert _names(page) == ["Castle"]
    assert _foot(page) == "Showing 1 of 4 locations · 3 active"
    page.locator('button[data-status="active"]').click()
    assert _names(page) == ["Harbour", "Bridge", "Dock"]
    _clean(page)


def test_search_by_name_follows_the_chip_counts(page, board):
    search = page.get_by_role("searchbox", name="Search locations")
    search.fill("dock")
    assert _names(page) == ["Dock"]
    expect(_chip(page, "all")).to_have_text("1")
    expect(_chip(page, "retired")).to_have_text("0")
    search.fill("zzz")
    expect(page.locator("[data-no-match]")).to_be_visible()
    page.locator("[data-no-match] [data-clear-for]").click()
    assert _names(page) == ["Harbour", "Bridge", "Castle", "Dock"]
    _clean(page)


def test_columns_sort_by_their_own_types(page, board):
    def sort(label):
        page.locator("#groups-table th").filter(has_text=label).locator(".sort-button").click()

    sort("Location")
    assert _names(page) == ["Bridge", "Castle", "Dock", "Harbour"]
    sort("Progress")  # 10 / 40, 90 / 100, 20 / 20, 2 / 10 as shares: 25%, 90%, 100%, 20%
    assert _names(page) == ["Dock", "Harbour", "Bridge", "Castle"]
    sort("Remaining")  # 30, 10, 0, 8
    assert _names(page) == ["Castle", "Dock", "Bridge", "Harbour"]
    sort("Ready")  # 5, 0, 0, 1: equal values keep the owner's order
    assert _names(page) == ["Bridge", "Castle", "Dock", "Harbour"]
    sort("Planned")  # Castle 1 Oct, Dock 1 Nov, Harbour 1 Dec, Bridge not set last
    assert _names(page) == ["Castle", "Dock", "Harbour", "Bridge"]
    sort("Planned")
    assert _names(page) == ["Harbour", "Dock", "Castle", "Bridge"]  # not set stays last
    _clean(page)


def test_order_buttons_show_only_in_the_owners_order(page, board):
    moves, note = _moves(page), page.get_by_text(NOTE)
    expect(moves).to_have_count(6)  # Harbour, Bridge and Dock, Up and Down (Castle is retired)
    expect(note).to_be_hidden()
    search = page.get_by_role("searchbox", name="Search locations")
    search.fill("o")
    expect(moves).to_have_count(0)
    expect(note).to_be_visible()
    page.locator("[data-clear-for]").first.click()
    expect(moves).to_have_count(6)
    expect(note).to_be_hidden()
    page.locator('button[data-status="active"]').click()
    expect(moves).to_have_count(0)
    expect(note).to_be_visible()
    page.locator("[data-clear-for]").first.click()
    expect(moves).to_have_count(6)
    page.locator("#groups-table th").filter(has_text="Location").locator(".sort-button").click()
    expect(moves).to_have_count(0)
    expect(note).to_be_visible()
    page.locator("[data-clear-for]").first.click()  # Clear filters also clears the sort on this table
    assert _names(page) == ["Harbour", "Bridge", "Castle", "Dock"]
    expect(moves).to_have_count(6)
    expect(note).to_be_hidden()
    assert page.evaluate("location.search") == ""
    _clean(page)


def test_moving_a_location_still_works_and_keeps_the_view(page, live_server, board, db):
    page.locator("#groups-table-search").fill("")  # the search box exists
    page.get_by_role("button", name="Move down: Harbour").click()
    page.wait_for_load_state("networkidle")
    assert _names(page) == ["Bridge", "Harbour", "Castle", "Dock"]
    db.expire_all()
    order = [g.name for g in db.scalars(select(Group).order_by(Group.sort_order, Group.id))]
    assert order == ["Bridge", "Harbour", "Castle", "Dock"]
    page.get_by_role("button", name="Move up: Dock").click()
    page.wait_for_load_state("networkidle")
    assert _names(page) == ["Bridge", "Dock", "Castle", "Harbour"]
    _clean(page)


def test_a_row_action_returns_to_the_same_view(page, board):
    page.locator('button[data-status="retired"]').click()
    page.get_by_role("button", name="Reinstate: Castle").click()
    page.wait_for_load_state("networkidle")
    assert page.evaluate("location.search") == "?filter=retired"
    expect(page.locator('button[data-status="retired"]')).to_have_attribute("aria-pressed", "true")
    expect(_chip(page, "active")).to_have_text("4")
    expect(page.locator(ROWS)).to_have_count(0)  # nothing is retired now
    _clean(page)


def test_the_totals_row_stays_put_while_the_table_is_filtered(page, board):
    total = page.locator("#groups-table tfoot tr")
    expect(total).to_contain_text("All locations")
    before = total.inner_text()
    page.get_by_role("searchbox", name="Search locations").fill("dock")
    page.locator("#groups-table th").filter(has_text="Progress").locator(".sort-button").click()
    expect(total).to_be_visible()
    assert total.inner_text() == before
    assert page.locator("#groups-table tfoot").evaluate("el => el.parentElement.tFoot === el")
    _clean(page)


def test_phone_shows_cards_without_sideways_scroll(page, board):
    page.set_viewport_size({"width": 390, "height": 900})
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
    expect(page.locator("#groups-table thead")).to_be_hidden()
    assert page.locator("#groups-table tbody tr").first.evaluate("el => getComputedStyle(el).display") == "flex"
    _clean(page)
