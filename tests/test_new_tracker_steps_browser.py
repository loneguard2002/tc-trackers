"""New tracker in five steps, in a browser: Next checks the step it leaves, the review shows what was entered, and
Create tracker saves it."""

from __future__ import annotations

import pytest
from conftest import browser_sign_in
from playwright.sync_api import expect

pytestmark = pytest.mark.browser


def _next(page):
    page.get_by_role("button", name="Next").click()


def test_new_tracker_goes_step_by_step_and_creates_the_tracker(
    page, live_server, user_factory, region_factory, business_line_factory
):
    region_factory("EMEA", "Europe")
    business_line_factory()
    browser_sign_in(page, live_server, user_factory(is_admin=True))
    page.goto(f"{live_server}/trackers/new")
    caption = page.locator("[data-step-caption]")
    expect(caption).to_have_text("Step 1 of 5: name it and say what it counts")
    expect(page.get_by_role("button", name="Create tracker")).to_be_hidden()

    _next(page)  # nothing entered: the step stays, and says why
    expect(page.get_by_text("Enter a name to go on.")).to_be_visible()
    expect(page.locator("#name")).to_have_attribute("aria-invalid", "true")
    expect(page.locator("#name")).to_be_focused()
    page.fill("#name", "Laptop refresh")
    page.fill("#unit_label", "laptops")
    _next(page)

    expect(caption).to_have_text("Step 2 of 5: choose who sees it")
    expect(page.locator("#name")).to_be_hidden()
    _next(page)
    expect(page.get_by_text("Choose a business line to go on.")).to_be_visible()
    page.select_option("#business_line_id", label="Tradition brokerage")
    _next(page)
    expect(page.get_by_text("Tick at least one region to go on.")).to_be_visible()
    page.get_by_label("EMEA – Europe").check()
    _next(page)

    expect(caption).to_have_text("Step 3 of 5: set the weeks it covers")
    page.fill("#start_date", "2026-09-04")
    page.fill("#last_week_ending", "2026-12-24")  # a Thursday
    _next(page)
    expect(page.locator("[data-wizard-step='3'] [data-step-error]")).to_have_text(
        "The last week-ending must fall on a Friday."
    )
    page.fill("#last_week_ending", "2026-12-25")
    page.fill("#target_completion", "2026-11-27")
    expect(page.locator("[data-weeks-sum]")).to_have_text("17 weeks, 4 Sep 2026 to 25 Dec 2026.")
    expect(page.locator("[data-weeks-bar] .wizard-week")).to_have_count(17)
    expect(page.locator("[data-weeks-bar] .is-target")).to_have_count(1)
    _next(page)

    expect(caption).to_have_text("Step 4 of 5: tune the forecast (optional)")
    page.get_by_role("button", name="One week more").click()
    expect(page.locator("#moving_average_weeks")).to_have_value("4")
    _next(page)

    expect(caption).to_have_text("Step 5 of 5: check and create")
    review = page.locator("[data-review]")
    for text in (
        "Laptop refresh",
        "laptops",
        "Tradition brokerage",
        "EMEA – Europe",
        "Friday",
        "17 weeks, 4 Sep 2026 to 25 Dec 2026",
        "27 Nov 2026",
        "4 weeks",
        "No team",
        "No description",
    ):
        expect(review).to_contain_text(text)

    page.get_by_role("button", name="Edit details").click()  # back to a step, then on again
    expect(caption).to_have_text("Step 1 of 5: name it and say what it counts")
    page.fill("#name", "Laptop refresh EMEA")
    for _ in range(4):
        _next(page)
    expect(review).to_contain_text("Laptop refresh EMEA")
    page.locator("[data-step-dot='2']").click()  # a finished step opens again from the step bar
    expect(caption).to_have_text("Step 2 of 5: choose who sees it")
    page.locator("[data-step-dot='5']").click()  # a step not yet reached again does nothing
    expect(caption).to_have_text("Step 2 of 5: choose who sees it")
    for _ in range(3):
        _next(page)
    page.get_by_role("button", name="Create tracker").click()
    expect(page.get_by_text("Tracker created.")).to_be_visible()
    expect(page.locator("#name")).to_have_value("Laptop refresh EMEA")
    expect(page.locator("#moving_average_weeks")).to_have_value("4")


def test_new_tracker_steps_fit_a_phone(page, live_server, user_factory, region_factory, business_line_factory):
    region_factory("EMEA", "Europe")
    business_line_factory()
    browser_sign_in(page, live_server, user_factory(is_admin=True))
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{live_server}/trackers/new")
    page.fill("#name", "Phone")
    _next(page)
    page.select_option("#business_line_id", label="Tradition brokerage")
    page.get_by_label("EMEA – Europe").check()
    _next(page)
    page.fill("#start_date", "2026-11-27")
    page.fill("#last_week_ending", "2027-01-01")
    _next(page)
    page.get_by_role("button", name="Skip for now").click()
    expect(page.locator("[data-step-caption]")).to_have_text("Step 5 of 5: check and create")
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
