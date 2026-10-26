"""Tracker settings layout in a real browser (database)."""

from __future__ import annotations

import pytest
from conftest import browser_sign_in

pytestmark = pytest.mark.browser


@pytest.fixture
def owner_page(page, live_server, tracker_factory, user_factory, grant):
    tracker = tracker_factory(name="Settings tracker")
    owner = user_factory()
    grant(owner, tracker, "owner")
    browser_sign_in(page, live_server, owner)
    return lambda: page.goto(f"{live_server}/trackers/{tracker.id}/settings")


def box(page, heading_id):
    return page.locator(f"section[aria-labelledby='{heading_id}']").bounding_box()


def test_sections_sit_in_two_columns_on_a_wide_screen(page, owner_page):
    page.set_viewport_size({"width": 1600, "height": 1000})
    owner_page()
    general, period = box(page, "section-general"), box(page, "section-period")
    forecast, schedule = box(page, "section-forecast"), box(page, "section-schedule")
    assert general["y"] == period["y"] and period["x"] > general["x"] + general["width"]
    assert forecast["y"] == schedule["y"] and forecast["y"] > general["y"] + general["height"]


def test_sections_stack_on_a_narrow_screen(page, owner_page):
    page.set_viewport_size({"width": 900, "height": 1000})
    owner_page()
    general, period = box(page, "section-general"), box(page, "section-period")
    assert period["y"] >= general["y"] + general["height"]


def test_actions_and_archive_span_the_full_width(page, owner_page):
    page.set_viewport_size({"width": 1600, "height": 1000})
    owner_page()
    general, period = box(page, "section-general"), box(page, "section-period")
    actions = page.locator(".settings-actions").bounding_box()
    assert actions["x"] <= general["x"] + 1
    assert actions["x"] + actions["width"] >= period["x"] + period["width"] - 1


def test_descriptions_use_a_small_font(page, owner_page):
    owner_page()
    sizes = page.evaluate(
        "['.settings-section-head p', '.setting-help', '.setting-label label']"
        ".map(s => parseFloat(getComputedStyle(document.querySelector(s)).fontSize))"
    )
    section_text, field_help, label = sizes
    assert section_text <= 12.5 and field_help <= 12.5
    assert label - field_help >= 2


SECTION_LINKS = [
    ("General", "general"),
    ("Reporting period", "reporting-period"),
    ("Progress and forecast", "progress-forecast"),
    ("Scheduled sending", "schedule"),
]


def test_section_links_point_at_the_four_sections(page, owner_page):
    owner_page()
    links = page.locator("nav[aria-label='Settings sections'] a")
    assert links.all_inner_texts() == [label for label, _ in SECTION_LINKS]
    for (_, anchor), href in zip(SECTION_LINKS, [a.get_attribute("href") for a in links.all()], strict=True):
        assert href == f"#{anchor}"
        assert page.locator(f"section.settings-section#{anchor}").count() == 1


def test_section_link_scrolls_the_section_clear_of_the_top_bar(page, owner_page):
    page.set_viewport_size({"width": 900, "height": 700})
    owner_page()
    page.click("nav[aria-label='Settings sections'] a[href='#schedule']")
    page.wait_for_function("location.hash === '#schedule'")
    page.wait_for_timeout(800)
    top = page.evaluate("document.getElementById('schedule').getBoundingClientRect().top")
    topbar = page.evaluate("document.querySelector('.topbar').getBoundingClientRect().bottom")
    assert topbar <= top < 700


def test_new_tracker_page_has_no_section_links(page, live_server, user_factory):
    browser_sign_in(page, live_server, user_factory(is_admin=True))
    page.goto(f"{live_server}/trackers/new")
    assert page.locator("nav[aria-label='Settings sections']").count() == 0
