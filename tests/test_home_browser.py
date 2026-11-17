"""The home page's Business line and Region filters in a real browser, under the Content Security Policy (database)."""

from __future__ import annotations

import re
from datetime import date

import pytest
from conftest import browser_sign_in
from playwright.sync_api import expect
from test_report_page_browser import RECORDER

from tracker.lists.catalogue import set_tracker_regions
from tracker.models import ReportInput

pytestmark = pytest.mark.browser


def test_region_filter_shows_only_trackers_covering_it(
    page, live_server, db, tracker_factory, region_factory, business_line_factory, user_factory
):
    emea, apac = region_factory("EMEA"), region_factory("APAC")
    line = business_line_factory()
    europe = tracker_factory(name="Europe only", business_line_id=line.id)
    both = tracker_factory(name="Europe and Asia", business_line_id=line.id)
    tracker_factory(name="Bare tracker")
    set_tracker_regions(db, europe.id, [emea.id])
    set_tracker_regions(db, both.id, [emea.id, apac.id])
    db.add(ReportInput(tracker_id=europe.id, week_ending=date(2026, 9, 4), status="Red"))
    db.commit()

    page.add_init_script(RECORDER)
    browser_sign_in(page, live_server, user_factory(is_admin=True))
    page.goto(live_server + "/")
    cards = page.locator("[data-home-cards] [data-card]:visible")
    region = page.get_by_label("Region", exact=True)
    business_line = page.get_by_label("Business line", exact=True)
    expect(region).to_be_visible()
    expect(cards).to_have_count(3)

    region.select_option(label="APAC")
    expect(cards).to_have_count(1)
    expect(cards.first).to_contain_text("Europe and Asia")

    region.select_option(label="EMEA")
    expect(cards).to_have_count(2)

    region.select_option(label="Not set")
    expect(cards).to_have_count(1)
    expect(cards.first).to_contain_text("Bare tracker")

    region.select_option(value="all")
    business_line.select_option(label="Not set")
    page.locator("[data-filter=all]").click()
    expect(cards).to_have_count(1)
    expect(cards.first).to_contain_text("Bare tracker")

    # A chip and a select together: nothing matches, so the empty-state note shows.
    business_line.select_option(value="all")
    region.select_option(label="APAC")
    page.locator("[data-filter=red]").click()
    expect(cards).to_have_count(0)
    expect(page.locator("[data-home-empty]")).to_be_visible()
    expect(page.locator("[data-home-empty]")).to_have_text("No trackers match this filter.")

    # The list layout filters the same way.
    page.locator("[data-filter=all]").click()
    page.locator("[data-layout=list]").click()
    rows = page.locator("[data-home-list] [data-card]:visible")
    expect(rows).to_have_count(1)
    expect(rows.first).to_contain_text("Europe and Asia")

    assert page.evaluate("window.__csp") == []
    assert page.evaluate("window.__errors") == []


def test_home_toolbar_fits_a_phone_screen(page, live_server, db, tracker_factory, region_factory, user_factory):
    region = region_factory("EMEA")
    tracker = tracker_factory(name="Phone tracker")
    set_tracker_regions(db, tracker.id, [region.id])
    db.commit()
    page.set_viewport_size({"width": 390, "height": 844})
    browser_sign_in(page, live_server, user_factory(is_admin=True))
    page.goto(live_server + "/")
    expect(page.get_by_label("Region", exact=True)).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


def test_cards_scroll_sideways_with_a_third_of_the_next_showing(page, live_server, tracker_factory, user_factory):
    for k in range(5):
        tracker_factory(name=f"Tracker {k + 1}", unit_label="Thin Clients")
    page.add_init_script(RECORDER)
    page.set_viewport_size({"width": 1835, "height": 1000})
    browser_sign_in(page, live_server, user_factory(is_admin=True))
    page.goto(live_server + "/")
    row = page.locator("[data-home-cards]")
    cards = row.locator("[data-card]")
    expect(cards).to_have_count(5)
    boxes = [cards.nth(k).bounding_box() for k in range(5)]
    assert len({round(box["y"]) for box in boxes}) == 1  # one row
    assert min(box["width"] for box in boxes) >= 480
    view = row.bounding_box()
    # Whole cards, then about a third of the next one.
    right = view["x"] + view["width"]
    shown = [max(0.0, min(box["x"] + box["width"], right) - box["x"]) / box["width"] for box in boxes]
    partial = [part for part in shown if 0 < part < 0.99]
    assert len(partial) == 1 and 0.25 <= partial[0] <= 0.4
    expect(row).to_have_class(re.compile(r"\bmore-after\b"))
    expect(row).not_to_have_class(re.compile(r"\bmore-before\b"))
    # Nothing on a card is cut off with an ellipsis.
    clipped = page.evaluate(
        "[...document.querySelectorAll('[data-card] .fact-line')]"
        ".filter(el => el.scrollWidth > el.clientWidth + 1).length"
    )
    assert clipped == 0
    row.evaluate("el => el.scrollTo({left: el.scrollWidth})")
    expect(row).to_have_class(re.compile(r"\bmore-before\b"))
    expect(row).not_to_have_class(re.compile(r"\bmore-after\b"))
    # A filter that leaves fewer cards starts the row again from the left.
    page.locator("[data-filter=none]").click()
    expect(row).not_to_have_class(re.compile(r"\bmore-before\b"))
    assert page.evaluate("window.__csp") == [] and page.evaluate("window.__errors") == []


def test_cards_stack_on_a_phone(page, live_server, tracker_factory, user_factory):
    for k in range(3):
        tracker_factory(name=f"Tracker {k + 1}")
    page.set_viewport_size({"width": 390, "height": 844})
    browser_sign_in(page, live_server, user_factory(is_admin=True))
    page.goto(live_server + "/")
    first, second = (page.locator("[data-home-cards] [data-card]").nth(k).bounding_box() for k in (0, 1))
    assert second["y"] >= first["y"] + first["height"]  # one under the other
    assert second["y"] - (first["y"] + first["height"]) <= 17  # the usual gap, no empty fade rows between
    assert first["width"] > 300
