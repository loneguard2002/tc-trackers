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


def card_row(page):
    """The card row, the cards' boxes, and how much of each card shows inside the row (1 = all of it)."""
    row = page.locator("[data-home-cards]")
    cards = row.locator("[data-card]")
    boxes = [cards.nth(k).bounding_box() for k in range(cards.count())]
    view = row.bounding_box()
    right = view["x"] + view["width"]
    shown = [max(0.0, min(box["x"] + box["width"], right) - box["x"]) / box["width"] for box in boxes]
    return row, boxes, shown


def test_cards_scroll_sideways_with_a_third_of_the_next_showing(page, live_server, tracker_factory, user_factory):
    for k in range(5):
        tracker_factory(name=f"Tracker {k + 1}", unit_label="Thin Clients")
    page.add_init_script(RECORDER)
    page.set_viewport_size({"width": 1500, "height": 1000})
    browser_sign_in(page, live_server, user_factory(is_admin=True))
    page.goto(live_server + "/")
    expect(page.locator("[data-home-cards] [data-card]")).to_have_count(5)
    row, boxes, shown = card_row(page)
    assert len({round(box["y"]) for box in boxes}) == 1  # one row
    assert all(480 <= box["width"] <= 560 for box in boxes)
    # Whole cards, then about a third of the next one.
    partial = [part for part in shown if 0 < part < 0.99]
    assert len(partial) == 1 and 0.25 <= partial[0] <= 0.4
    # On a wider window the cards stop growing at 560px, so more of the next one shows.
    page.set_viewport_size({"width": 1835, "height": 1000})
    page.wait_for_function("document.querySelector('[data-card]').getBoundingClientRect().width > 555")
    row, boxes, shown = card_row(page)
    assert all(box["width"] <= 560.5 for box in boxes)
    partial = [part for part in shown if 0 < part < 0.99]
    assert len(partial) == 1 and partial[0] > 0.4
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


def open_home(page, live_server, user_factory, query=""):
    page.add_init_script(RECORDER)
    browser_sign_in(page, live_server, user_factory(is_admin=True))
    page.goto(live_server + "/" + query)
    expect(page.locator("[data-home-tools]")).to_be_visible()


def names(page, container):
    return page.locator(f"[data-home-{container}] [data-card]:visible").evaluate_all(
        "els => els.map(el => el.dataset.name)"
    )


def clean(page):
    assert page.evaluate("window.__csp") == [] and page.evaluate("window.__errors") == []


def test_search_filters_cards_and_list_with_footer_and_clear(page, live_server, db, tracker_factory, user_factory):
    for name in ("Alpha rollout", "Beta rollout"):
        tracker_factory(name=name)
    red = tracker_factory(name="Gamma patching")
    db.add(ReportInput(tracker_id=red.id, week_ending=date(2026, 9, 4), status="Red"))
    db.commit()
    open_home(page, live_server, user_factory)
    footer = page.locator("[data-home-count]")
    clear = page.locator("[data-clear-for=home]")
    expect(footer).to_have_text("Showing 3 of 3 trackers")
    expect(clear).to_be_hidden()
    page.get_by_role("searchbox").fill("  ROLLOUT ")
    expect(page.locator("[data-home-cards] [data-card]:visible")).to_have_count(2)
    expect(footer).to_have_text("Showing 2 of 3 trackers")
    assert "q=ROLLOUT" in page.url
    page.locator("[data-layout=list]").click()
    expect(page.locator("[data-home-list] [data-card]:visible")).to_have_count(2)
    expect(footer).to_be_visible()
    page.locator("[data-filter=red]").click()
    expect(footer).to_have_text("Showing 0 of 3 trackers")
    expect(clear).to_be_visible()
    clear.click()
    expect(footer).to_have_text("Showing 3 of 3 trackers")
    expect(page.get_by_role("searchbox")).to_have_value("")
    expect(page.locator("[data-filter=all]")).to_have_attribute("aria-pressed", "true")
    expect(clear).to_be_hidden()
    expect(page.get_by_role("searchbox")).to_be_focused()  # the button hid, so the focus moved to the search box
    assert "q=" not in page.url and "filter=" not in page.url and "layout=list" in page.url
    clean(page)


def test_footer_uses_the_singular_and_counts_archived_only_when_shown(
    page, live_server, db, tracker_factory, user_factory
):
    tracker_factory(name="Only one")
    tracker_factory(name="Old one", status="archived")
    open_home(page, live_server, user_factory)
    expect(page.locator("[data-home-count]")).to_have_text("Showing 1 of 1 tracker")
    page.goto(live_server + "/?archived=1")
    expect(page.locator("[data-home-count]")).to_have_text("Showing 2 of 2 trackers")


def test_heading_sort_and_the_sort_select_agree_and_cards_follow(page, live_server, tracker_factory, user_factory):
    for name in ("Bravo", "Alpha", "Charlie"):
        tracker_factory(name=name)
    open_home(page, live_server, user_factory)
    page.locator("[data-layout=list]").click()
    select = page.locator("[data-home-sort]")
    heading = page.locator("[data-home-list] th", has=page.locator("[data-sort=name]"))
    heading.locator("button").click()
    expect(select).to_have_value("name")
    expect(heading).to_have_attribute("aria-sort", "ascending")
    assert names(page, "list") == ["alpha", "bravo", "charlie"]
    assert page.locator("[data-home-cards] [data-card]").evaluate_all("els => els.map(el => el.dataset.name)") == [
        "alpha",
        "bravo",
        "charlie",
    ]
    assert "sort=name" in page.url
    heading.locator("button").click()
    expect(select).to_have_value("-name")
    expect(heading).to_have_attribute("aria-sort", "descending")
    assert names(page, "list") == ["charlie", "bravo", "alpha"]
    assert "sort=-name" in page.url
    # The select drives the heading the other way round.
    select.select_option(value="name")
    expect(heading).to_have_attribute("aria-sort", "ascending")
    select.select_option(value="attention")
    assert "sort=" not in page.url
    expect(heading).to_have_attribute("aria-sort", "none")
    clean(page)


def test_the_view_is_kept_in_the_address_and_bad_values_are_ignored(
    page, live_server, db, tracker_factory, region_factory, user_factory
):
    emea = region_factory("EMEA")
    first = tracker_factory(name="Alpha one")
    tracker_factory(name="Beta two")
    set_tracker_regions(db, first.id, [emea.id])
    db.commit()
    open_home(
        page, live_server, user_factory, f"?filter=none&region={emea.id}&sort=-name&q=alpha&layout=list&archived=1"
    )
    expect(page.locator("[data-filter=none]")).to_have_attribute("aria-pressed", "true")
    expect(page.get_by_label("Region", exact=True)).to_have_value(str(emea.id))
    expect(page.locator("[data-home-sort]")).to_have_value("-name")
    expect(page.get_by_role("searchbox")).to_have_value("alpha")
    expect(page.locator("[data-layout=list]")).to_have_attribute("aria-pressed", "true")
    page.locator("[data-clear-for=home]").click()
    # Clear keeps the sort and the layout, and other keys of the address stay.
    assert "sort=-name" in page.url and "layout=list" in page.url and "archived=1" in page.url
    assert "filter=" not in page.url and "region=" not in page.url and "q=" not in page.url
    page.goto(live_server + "/?filter=bogus&line=999&region=zzz&sort=nope&layout=grid&q=")
    expect(page.locator("[data-filter=all]")).to_have_attribute("aria-pressed", "true")
    expect(page.locator("[data-home-sort]")).to_have_value("attention")
    expect(page.locator("[data-layout=cards]")).to_have_attribute("aria-pressed", "true")
    expect(page.locator("[data-home-cards] [data-card]:visible")).to_have_count(2)
    # The next change rewrites the address with defaults left out.
    page.locator("[data-filter=all]").click()
    assert page.url.endswith("/")
    clean(page)


def test_layout_in_the_address_wins_over_the_remembered_one(page, live_server, tracker_factory, user_factory):
    tracker_factory(name="Solo")
    open_home(page, live_server, user_factory)
    page.locator("[data-layout=list]").click()
    page.goto(live_server + "/")
    expect(page.locator("[data-layout=list]")).to_have_attribute("aria-pressed", "true")
    page.goto(live_server + "/?layout=cards")
    expect(page.locator("[data-layout=cards]")).to_have_attribute("aria-pressed", "true")
    expect(page.locator("[data-home-cards]")).to_be_visible()
    clean(page)


def test_a_filter_whose_chip_is_not_shown_is_ignored(page, live_server, tracker_factory, user_factory):
    tracker_factory(name="Plain")  # nothing disagrees with its forecast, so that chip is not drawn
    open_home(page, live_server, user_factory, "?filter=disagree")
    expect(page.locator("[data-filter=disagree]")).to_have_count(0)
    expect(page.locator("[data-filter=all]")).to_have_attribute("aria-pressed", "true")
    expect(page.locator("[data-home-cards] [data-card]:visible")).to_have_count(1)
    assert "filter=" not in page.url
    clean(page)


def test_names_sort_in_natural_order(page, live_server, tracker_factory, user_factory):
    for name in ("Tracker 10", "Tracker 5", "Tracker 1"):
        tracker_factory(name=name)
    open_home(page, live_server, user_factory, "?sort=name")
    assert names(page, "cards") == ["tracker 1", "tracker 5", "tracker 10"]
    sort = page.locator("[data-home-sort]")
    sort.select_option("-name")
    assert names(page, "cards") == ["tracker 10", "tracker 5", "tracker 1"]
    clean(page)
