"""Interactive report charts in a real browser, under the application's Content Security Policy (database)."""

from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

import pytest
from conftest import browser_sign_in
from playwright.sync_api import expect

from tracker.models import CompletionEntry, Group, Week

pytestmark = pytest.mark.browser

WEEKS = [date(2026, 9, 4), date(2026, 9, 11), date(2026, 9, 18), date(2026, 9, 25)]
# Records every policy violation and script error the page raises, so tests can assert there were none.
RECORDER = (
    "window.__csp = []; window.__errors = [];"
    "document.addEventListener('securitypolicyviolation',"
    " e => window.__csp.push(e.violatedDirective + ' ' + e.blockedURI));"
    "window.addEventListener('error', e => window.__errors.push(String(e.message)));"
)


def _tracker_and_viewer(tracker_factory, user_factory, grant):
    tracker = tracker_factory(name="Browser tracker", first_week_ending=WEEKS[0], last_week_ending=WEEKS[-1])
    viewer = user_factory()
    grant(viewer, tracker, "viewer")
    return tracker, viewer


@pytest.fixture
def seeded(db, tracker_factory, user_factory, grant):
    tracker, viewer = _tracker_and_viewer(tracker_factory, user_factory, grant)
    group = Group(tracker_id=tracker.id, name="LD5", baseline=100, sort_order=1)
    db.add(group)
    db.flush()
    for week in WEEKS:
        db.add(Week(tracker_id=tracker.id, week_ending=week, target=10))
    for quantity, day, week in ((8, date(2026, 9, 3), WEEKS[0]), (12, date(2026, 9, 10), WEEKS[1])):
        db.add(
            CompletionEntry(
                tracker_id=tracker.id, group_id=group.id, quantity=quantity, entry_date=day, week_ending=week
            )
        )
    db.commit()
    return SimpleNamespace(tracker=tracker, viewer=viewer)


@pytest.fixture
def seeded_empty(db, tracker_factory, user_factory, grant):
    tracker, viewer = _tracker_and_viewer(tracker_factory, user_factory, grant)
    return SimpleNamespace(tracker=tracker, viewer=viewer)


def open_report(page, base_url, seeded, wait=True):
    page.add_init_script(RECORDER)
    browser_sign_in(page, base_url, seeded.viewer)
    page.goto(f"{base_url}/trackers/{seeded.tracker.id}/report")
    if wait:
        page.wait_for_selector(".chart-host-cumulative :is(svg, canvas)")


def test_charts_render_without_policy_errors(page, live_server, seeded):
    open_report(page, live_server, seeded)
    expect(page.locator(".chart-host")).to_have_count(3)
    expect(page.locator("img[data-chart]")).to_have_count(0)
    assert page.evaluate("window.__csp") == []
    assert page.evaluate("window.__errors") == []


def test_tooltip_on_hover(page, live_server, seeded):
    open_report(page, live_server, seeded)
    page.locator(".chart-host-remaining").hover()
    tooltip = page.locator(".chart-host-remaining .chart-tooltip")
    expect(tooltip).to_be_visible()
    expect(tooltip).to_contain_text("Plan")
    assert page.evaluate("window.__csp") == []


def test_charts_follow_the_theme(page, live_server, seeded):
    open_report(page, live_server, seeded)
    start = page.evaluate("document.documentElement.getAttribute('data-theme')")
    other = "dark" if start == "light" else "light"
    page.click("[data-theme-toggle]")
    expect(page.locator(".chart-host-remaining")).to_have_attribute("data-theme", other)
    page.click("[data-theme-toggle]")
    expect(page.locator(".chart-host-remaining")).to_have_attribute("data-theme", start)


def test_empty_tracker_renders_cleanly(page, live_server, seeded_empty):
    open_report(page, live_server, seeded_empty)
    expect(page.locator(".chart-host")).to_have_count(3)
    assert page.evaluate("window.__csp") == []
    assert page.evaluate("window.__errors") == []


def test_chart_without_any_values_says_no_data_yet(page, live_server, seeded):
    empty = {
        "planned_remaining": [None] * 4,
        "actual_remaining": [None] * 4,
        "forecast_remaining": [None] * 4,
        "target": [None] * 4,
        "actual": [None] * 4,
        "cum_target": [None] * 4,
        "cum_actual": [None] * 4,
    }
    payload = {
        "unit_label": "devices",
        "palette": {"plan": "#888888", "actual": "#2c7be5", "forecast": "#d39e00"},
        "weeks": [w.isoformat() for w in WEEKS],
        "series": empty,
    }
    page.route(
        "**/report/data.json*", lambda route: route.fulfill(content_type="application/json", body=json.dumps(payload))
    )
    open_report(page, live_server, seeded)
    expect(page.locator(".chart-host-remaining")).to_have_attribute("data-empty", "true")


def test_failed_data_request_keeps_the_pictures(page, live_server, seeded):
    page.route("**/report/data.json*", lambda route: route.fulfill(status=500, body="error"))
    open_report(page, live_server, seeded, wait=False)
    page.wait_for_load_state("networkidle")
    expect(page.locator("img[data-chart]")).to_have_count(3)
    assert page.evaluate("window.__errors") == []


def test_page_without_javascript_keeps_the_pictures(browser, live_server, seeded):
    context = browser.new_context(java_script_enabled=False)
    try:
        page = context.new_page()
        browser_sign_in(page, live_server, seeded.viewer)
        page.goto(f"{live_server}/trackers/{seeded.tracker.id}/report")
        expect(page.locator("img[data-chart]")).to_have_count(3)
    finally:
        context.close()
