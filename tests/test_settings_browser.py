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
