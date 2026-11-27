"""Activity › Overview in a real browser: no sideways page scroll, and choosing a day on the heatmap (database)."""

from __future__ import annotations

import os
import random
from datetime import datetime, timedelta, timezone

import pytest
from conftest import browser_sign_in
from playwright.sync_api import expect

from tracker.models import AuditLog

pytestmark = pytest.mark.browser

ACTIONS = ("entry_created", "entry_updated", "inputs_saved", "risk_updated", "group_updated", "settings_updated")


def seed(db, user_factory, tracker_factory) -> None:
    """A year of made-up use: most changes on Thursdays, fewer at the start of the week, none at weekends."""
    rng = random.Random(20261127)
    people = [user_factory(full_name=name) for name in ("Priya Shah", "Tom Becker", "Aiko Tanaka", "Omar Haddad")]
    trackers = [
        tracker_factory(name=name, created_at=datetime(2026, 8, 1, tzinfo=timezone.utc))
        for name in ("Windows 11 Rollout", "Server Patching", "Branch Wi-Fi Refresh")
    ]
    today = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
    rows = []
    for back in range(300):
        day = today - timedelta(days=back)
        if day.weekday() >= 5:
            continue
        for _ in range(rng.randint(0, [2, 3, 4, 9, 3][day.weekday()])):
            rows.append(
                AuditLog(
                    at=day - timedelta(hours=rng.randint(0, 6)),
                    user_id=rng.choice(people).id,
                    tracker_id=rng.choice(trackers).id,
                    action=rng.choice(ACTIONS),
                    entity="entry",
                    entity_id="1",
                )
            )
        rows.append(AuditLog(at=day, user_id=rng.choice(people).id, action="login", entity="user", entity_id="1"))
    db.add_all(rows)
    db.commit()


@pytest.mark.parametrize("width", [1280, 390])
def test_the_overview_fits_the_screen_and_a_day_shows_below_the_heatmap(
    page, live_server, db, user_factory, tracker_factory, width
):
    admin = user_factory(is_admin=True, full_name="Sam Taylor")
    seed(db, user_factory, tracker_factory)
    page.set_viewport_size({"width": width, "height": 900})
    browser_sign_in(page, live_server, admin)
    page.goto(f"{live_server}/admin/activity/overview")
    expect(page.get_by_role("heading", name="Changes per day, last 12 months")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    shots = os.environ.get("ACTIVITY_SHOTS")  # a folder: save screenshots for a visual check
    if shots:
        page.screenshot(path=f"{shots}/overview-{width}.png", full_page=True)
    strip = page.locator("[data-heat-detail]")
    expect(strip).to_have_text("Select a day to see it here.")
    day = page.locator(".heat-day").filter(has=page.locator("rect.heat-4")).first
    day.scroll_into_view_if_needed()
    day.click()
    expect(strip).to_contain_text("changes, ")
    link = page.get_by_role("link", name="Open this day in the log")
    expect(link).to_be_visible()
    assert "from=" in link.get_attribute("href")
    if shots:
        page.emulate_media(color_scheme="dark")
        page.evaluate("document.documentElement.dataset.theme = 'dark'")
        page.locator("#heatmap").screenshot(path=f"{shots}/heatmap-dark-{width}.png")
    day.click()
    expect(strip).to_have_text("Select a day to see it here.")
    expect(link).to_be_hidden()
