"""The email preview stays drawn when the preview week changes, in full Chromium (database).

email.js used to rebuild the preview frame as soon as the page loaded. With the page's files cached, as after a week
change, that rebuild landed while the server's frame was still loading, and Chrome and Edge then left the frame blank
for good (about one change in eight in a wide window). The other browser tests run Playwright's headless shell, which
never showed this, so this module runs the full Chromium build ("new headless").
"""

from __future__ import annotations

import io

import pytest
from PIL import Image
from playwright.sync_api import expect
from test_email_settings_browser import admin  # noqa: F401  (fixture)

pytestmark = pytest.mark.browser

CHANGES = 20  # before the fix, 2 to 7 changes in 20 to 40 left the frame blank


@pytest.fixture
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        chromium = playwright.chromium.launch(channel="chromium")
        try:
            yield chromium
        finally:
            chromium.close()


def drawn_pixels(page) -> int:
    """Pixels darker than the email's white page: the figures, text and chart once the frame is drawn."""
    png = page.locator("[data-preview-frame]").screenshot()
    image = Image.open(io.BytesIO(png)).convert("L")
    return sum(1 for value in image.getdata() if value < 200)


def test_preview_stays_drawn_when_the_week_changes(page, live_server, admin):
    page.set_viewport_size({"width": 1800, "height": 1100})  # wide: the preview sits in the sticky column
    page.goto(f"{live_server}/trackers/{admin.id}/mail")
    expect(page.frame_locator("[data-preview-frame]").locator(".mail-figures")).to_be_visible()
    weeks = page.locator("#week option").evaluate_all("options => options.map(o => o.value)")
    blank = []
    for change in range(CHANGES):
        week = weeks[change % len(weeks)]
        if week == page.locator("#week").input_value():
            week = weeks[(change + 1) % len(weeks)]
        with page.expect_navigation():
            page.select_option("#week", week)
        page.wait_for_timeout(1500)  # a drawn frame shows within this; a blank one stays blank
        if drawn_pixels(page) < 5000:
            blank.append(week)
    assert blank == [], f"preview frame left blank after changing to {blank}"
