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


def empty_payload():
    series = {
        key: [None] * len(WEEKS)
        for key in (
            "planned_remaining",
            "actual_remaining",
            "forecast_remaining",
            "target",
            "actual",
            "cum_target",
            "cum_actual",
        )
    }
    return {
        "unit_label": "devices",
        "palette": {"plan": "#888888", "actual": "#2c7be5", "forecast": "#d39e00"},
        "weeks": [w.isoformat() for w in WEEKS],
        "series": series,
    }


def route_empty_payload(page):
    page.route(
        "**/report/data.json*",
        lambda route: route.fulfill(content_type="application/json", body=json.dumps(empty_payload())),
    )


def test_chart_without_any_values_says_no_data_yet(page, live_server, seeded):
    route_empty_payload(page)
    open_report(page, live_server, seeded)
    expect(page.locator(".chart-host-remaining")).to_have_attribute("data-empty", "true")


@pytest.mark.parametrize(
    ("name", "title"),
    [("remaining", "Remaining"), ("weekly", "Weekly actual against target"), ("cumulative", "Cumulative completed")],
)
def test_each_chart_has_its_title(page, live_server, seeded, name, title):
    open_report(page, live_server, seeded)
    expect(page.locator(f".chart-host-{name} svg text", has_text=title).first).to_be_visible()


def test_empty_chart_keeps_its_title(page, live_server, seeded):
    route_empty_payload(page)
    open_report(page, live_server, seeded)
    host = page.locator(".chart-host-remaining")
    expect(host.locator("svg text", has_text="No data yet").first).to_be_visible()
    expect(host.locator("svg text", has_text="Remaining").first).to_be_visible()


def test_wheel_over_a_chart_scrolls_the_page(page, live_server, seeded):
    page.set_viewport_size({"width": 1300, "height": 600})
    open_report(page, live_server, seeded)
    page.locator(".chart-host-remaining").scroll_into_view_if_needed()
    before = page.evaluate("window.scrollY")
    page.locator(".chart-host-remaining").hover()
    page.mouse.wheel(0, 300)
    page.wait_for_timeout(400)
    assert page.evaluate("window.scrollY") > before


def test_every_week_has_a_dot(page, live_server, seeded):
    open_report(page, live_server, seeded)
    assert page.evaluate(
        "['remaining', 'weekly', 'cumulative'].every(name => echarts.getInstanceByDom("
        "document.querySelector('.chart-host-' + name)).getOption().series"
        ".every(s => s.type !== 'line' || s.showAllSymbol === true))"
    )


def test_save_as_image_downloads_that_chart_only(page, live_server, seeded):
    open_report(page, live_server, seeded)
    # The toolbox icon is the small path in the chart's top-right corner.
    icon = page.evaluate(
        """(() => { const h = document.querySelector('.chart-host-remaining'); const hb = h.getBoundingClientRect();
        const r = [...h.querySelectorAll('svg path')].map(p => p.getBoundingClientRect())
          .find(r => r.right > hb.right - 60 && r.top < hb.top + 60 && r.width < 24 && r.height < 24);
        return [r.left + r.width / 2, r.top + r.height / 2]; })()"""
    )
    with page.expect_download() as info:
        page.mouse.click(icon[0], icon[1])
    assert info.value.suggested_filename == "remaining.svg"
    content = open(info.value.path(), encoding="utf-8").read()
    assert "Remaining" in content and "Cumulative completed" not in content
    assert 'fill="transparent"' not in content


def test_charts_resize_when_the_sidebar_collapses(page, live_server, seeded):
    page.set_viewport_size({"width": 1200, "height": 900})
    open_report(page, live_server, seeded)
    page.evaluate("localStorage.removeItem('tracker-sidebar')")
    host = page.locator(".chart-host-remaining")
    page.click("[data-sidebar-toggle]")
    page.wait_for_timeout(700)
    host_width = host.evaluate("el => el.clientWidth")
    svg_width = host.locator("svg").first.evaluate("el => el.getBoundingClientRect().width")
    assert abs(host_width - svg_width) <= 2


def test_markup_in_the_unit_label_stays_text(page, live_server, seeded, db):
    seeded.tracker.unit_label = "<b>devs</b>"
    db.commit()
    open_report(page, live_server, seeded)
    host = page.locator(".chart-host-remaining")
    assert host.locator("b").count() == 0
    expect(host.locator("svg text", has_text="<b>devs</b>").first).to_be_visible()


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
