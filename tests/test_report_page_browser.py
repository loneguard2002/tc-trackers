"""Interactive report charts in a real browser, under the application's Content Security Policy (database)."""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
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
    page.goto(f"{base_url}/trackers/{seeded.tracker.id}/report?view=classic")
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
    expect(page.locator(".chart-host-remaining")).to_have_attribute("data-chart-theme", other)
    page.click("[data-theme-toggle]")
    expect(page.locator(".chart-host-remaining")).to_have_attribute("data-chart-theme", start)


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
        page.goto(f"{live_server}/trackers/{seeded.tracker.id}/report?view=classic")
        expect(page.locator("img[data-chart]")).to_have_count(3)
    finally:
        context.close()


def test_preview_switch_shows_the_pdf_and_png_widths(page, live_server, seeded):
    page.set_viewport_size({"width": 1600, "height": 1000})
    open_report(page, live_server, seeded)
    report = page.locator(".report-live")
    switch = page.locator("[data-report-view]")
    expect(switch).to_be_visible()
    screen_width = report.bounding_box()["width"]

    switch.get_by_role("button", name="PDF").click()
    expect(report).to_have_class("report-live is-pdf is-paper")
    expect(switch.get_by_role("button", name="PDF")).to_have_attribute("aria-pressed", "true")
    assert round(report.bounding_box()["width"]) == 794  # an A4 page at 96 dpi
    # At A4 width the two charts stack, as in the PDF.
    weekly, cumulative = page.locator(".chart-host-weekly"), page.locator(".chart-host-cumulative")
    expect(cumulative).to_be_visible()
    assert cumulative.bounding_box()["y"] > weekly.bounding_box()["y"]

    switch.get_by_role("button", name="PNG").click()
    assert round(report.bounding_box()["width"]) == 1100

    switch.get_by_role("button", name="Screen").click()
    expect(report).to_have_class("report-live")
    assert report.bounding_box()["width"] == screen_width
    assert page.evaluate("window.__csp") == [] and page.evaluate("window.__errors") == []


def test_preview_is_light_in_the_dark_theme(page, live_server, seeded):
    page.add_init_script("localStorage.setItem('tracker-theme', 'dark')")
    open_report(page, live_server, seeded)
    page.locator("[data-report-view]").get_by_role("button", name="PDF").click()
    background = page.locator(".report-live").evaluate("e => getComputedStyle(e).backgroundColor")
    assert background == "rgb(255, 255, 255)"
    weekly = page.locator(".chart-host-weekly")
    expect(weekly).to_have_attribute("data-chart-theme", "light")
    assert weekly.evaluate("e => getComputedStyle(e).backgroundColor") == "rgb(255, 255, 255)"
    assert weekly.locator("svg > rect").first.get_attribute("fill") == "#fff"


def _hold_chart_data(page):
    held = []
    page.route("**/report/data.json*", lambda route: held.append(route))
    return held


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_no_white_picture_or_jump_before_the_charts_draw(page, live_server, seeded, theme):
    # The server-drawn pictures are light and sized by their own shape; with JavaScript they stay hidden in a box the
    # size of the chart, so nothing flashes white in dark mode and nothing jumps when the chart replaces them.
    page.add_init_script(f"localStorage.setItem('tracker-theme', '{theme}')")
    held = _hold_chart_data(page)
    open_report(page, live_server, seeded, wait=False)
    page.wait_for_selector("img[data-chart='remaining']", state="attached")
    sizes = {}
    for name in ("remaining", "weekly", "cumulative"):
        img = page.locator(f"img[data-chart='{name}']")
        assert img.evaluate("e => getComputedStyle(e).visibility") == "hidden"
        sizes[name] = round(img.bounding_box()["height"])
    assert sizes == {"remaining": 340, "weekly": 280, "cumulative": 280}
    held[0].continue_()
    page.wait_for_selector(".chart-host-cumulative :is(svg, canvas)")
    for name, height in sizes.items():
        assert round(page.locator(f".chart-host-{name}").bounding_box()["height"]) == height
    assert page.evaluate("window.__csp") == []
    assert page.evaluate("window.__errors") == []


def test_the_pictures_come_back_when_the_chart_data_fails(page, live_server, seeded):
    page.route("**/report/data.json*", lambda route: route.abort())
    open_report(page, live_server, seeded, wait=False)
    picture = page.locator("img[data-chart='remaining']")
    expect(picture).to_be_visible()
    expect(page.locator(".report-live")).to_have_class(re.compile(r"\bcharts-failed\b"))
    assert picture.evaluate("e => getComputedStyle(e).visibility") == "visible"
    assert picture.evaluate("e => e.naturalWidth") > 0
    assert page.evaluate("window.__csp") == []


# --- The Status at a glance view's Remaining chart -------------------------------------------------------------


def open_glance(page, base_url, seeded, week="2026-09-11"):
    page.add_init_script(RECORDER)
    browser_sign_in(page, base_url, seeded.viewer)
    page.goto(f"{base_url}/trackers/{seeded.tracker.id}/report?view=new&week={week}")
    page.wait_for_selector(".chart-host-remaining-glance :is(svg, canvas)")


def add_targets(db, tracker):
    from datetime import datetime, timezone

    from report_helpers import add_target_change

    first, second, third = date(2026, 12, 4), date(2026, 12, 11), date(2026, 12, 18)
    add_target_change(db, tracker, None, first, datetime(2026, 9, 1, 9, tzinfo=timezone.utc))
    add_target_change(db, tracker, first, second, datetime(2026, 9, 3, 9, tzinfo=timezone.utc), "Kit delayed")
    add_target_change(db, tracker, second, third, datetime(2026, 9, 9, 9, tzinfo=timezone.utc))


def glance_option(page):
    return page.evaluate("echarts.getInstanceByDom(document.querySelector('.chart-host-remaining-glance')).getOption()")


def test_glance_chart_draws_with_direct_labels(page, live_server, seeded):
    open_glance(page, live_server, seeded)
    host = page.locator(".chart-host-remaining-glance")
    expect(page.locator("img[data-chart]")).to_have_count(0)
    for text in ("Actual: 80 left", "Plan: 80 left"):
        expect(host.locator("svg text", has_text=text).first).to_be_visible()
    expect(host.locator("svg text", has_text=re.compile(r"Forecast: none left on \d+ \w{3}")).first).to_be_visible()
    # The key sits under the chart, in the page, not inside the chart.
    expect(page.locator(".glance-legend li")).to_have_text(["Actual", "Plan", "Forecast"])
    expect(page.locator(".glance-legend")).to_be_visible()
    expect(host.locator("svg text", has_text=re.compile(r"^Plan$"))).to_have_count(0)
    assert page.evaluate("window.__csp") == []
    assert page.evaluate("window.__errors") == []


def test_glance_chart_marks_the_report_week_and_every_week(page, live_server, seeded):
    open_glance(page, live_server, seeded)
    host = page.locator(".chart-host-remaining-glance")
    expect(host.locator("svg text", has_text=re.compile(r"^Week ending 11 Sep$")).first).to_be_visible()
    series = {s["id"]: s for s in glance_option(page)["series"]}
    assert len(series["actual"]["data"]) == 2  # the weeks drawn so far; a dot each
    assert len(series["plan"]["data"]) == len(WEEKS)
    assert series["actual"]["lineStyle"]["type"] == "solid"
    assert series["plan"]["lineStyle"]["type"] == "dashed"
    assert series["forecast"]["lineStyle"]["type"] == "dotted"
    # Every week ending is a tick, with the month named under the first week of each month.
    expect(host.locator("svg text", has_text="Sep").first).to_be_visible()
    expect(host.locator("svg text", has_text=re.compile(r"^25$")).first).to_be_visible()


def test_glance_chart_draws_every_target(page, live_server, seeded, db):
    add_targets(db, seeded.tracker)
    open_glance(page, live_server, seeded, week="2026-09-11")
    host = page.locator(".chart-host-remaining-glance")
    expect(host.locator("svg text", has_text="Target 18 Dec").first).to_be_visible()
    lines = [s for s in glance_option(page)["series"] if s["id"] == "targets"][0]["markLine"]["data"]
    assert len(lines) == 3
    current, earlier = lines[-1], lines[:-1]
    assert current["lineStyle"]["opacity"] > max(e["lineStyle"]["opacity"] for e in earlier)
    assert all(line["lineStyle"]["type"] == "dashed" for line in lines)
    for number in ("1", "2", "3"):
        expect(host.locator("svg text", has_text=re.compile(rf"^{number}$")).first).to_be_visible()
    # The x-axis reaches the furthest target (18 Dec) even though the weeks end on 25 Sep.
    axis = glance_option(page)["xAxis"][0]
    assert axis["max"] >= (date(2026, 12, 18) - date(1970, 1, 1)).days


def test_glance_chart_without_a_target_draws_no_target_lines(page, live_server, seeded):
    open_glance(page, live_server, seeded)  # the seeded tracker has no target date
    assert [s for s in glance_option(page)["series"] if s["id"] == "targets"] == []


def test_glance_chart_draws_a_target_set_before_changes_were_recorded(page, live_server, seeded, db):
    seeded.tracker.target_completion = date(2026, 12, 18)
    db.commit()
    open_glance(page, live_server, seeded)
    host = page.locator(".chart-host-remaining-glance")
    expect(host.locator("svg text", has_text="Target 18 Dec").first).to_be_visible()
    lines = [s for s in glance_option(page)["series"] if s["id"] == "targets"][0]["markLine"]["data"]
    assert len(lines) == 1 and lines[0]["label"]["show"] is False  # unnumbered
    expect(host.locator("svg text", has_text=re.compile(r"^1$"))).to_have_count(0)
    assert glance_option(page)["xAxis"][0]["max"] >= (date(2026, 12, 18) - date(1970, 1, 1)).days
    assert page.evaluate("window.__csp") == [] and page.evaluate("window.__errors") == []


ACTUAL_LABEL_IS = (
    "expected => { const c = echarts.getInstanceByDom(document.querySelector('.chart-host-remaining-glance'));"
    " const d = c.getOption().series.find(s => s.id === 'actual').data;"
    " return d[d.length - 1].label.formatter === expected; }"
)


def test_glance_labels_reflow_when_the_chart_crosses_the_narrow_width(page, live_server, seeded):
    page.set_viewport_size({"width": 1440, "height": 900})
    open_glance(page, live_server, seeded)
    assert page.evaluate(ACTUAL_LABEL_IS, "Actual: 80 left")
    page.set_viewport_size({"width": 420, "height": 900})
    page.wait_for_function(ACTUAL_LABEL_IS, arg="Actual:\n80 left", timeout=5000)
    page.set_viewport_size({"width": 1440, "height": 900})
    page.wait_for_function(ACTUAL_LABEL_IS, arg="Actual: 80 left", timeout=5000)
    expect(page.locator(".chart-host-remaining-glance svg text", has_text="Actual: 80 left").first).to_be_visible()
    assert page.evaluate("window.__csp") == [] and page.evaluate("window.__errors") == []


def glance_tip_at(page, iso):
    """The tooltip shown with the pointer on ``iso`` (a day on the x-axis), at the foot of the plot."""
    day = (date.fromisoformat(iso) - date(1970, 1, 1)).days
    return page.evaluate(
        "day => { const c = echarts.getInstanceByDom(document.querySelector('.chart-host-remaining-glance'));"
        " const at = c.convertToPixel({ xAxisIndex: 0, yAxisIndex: 0 }, [day, 0]);"
        " c.dispatchAction({ type: 'showTip', x: at[0], y: at[1] - 2 });"
        " const tip = document.querySelector('.chart-host-remaining-glance .chart-tooltip');"
        " return tip ? tip.innerText : ''; }",
        day,
    )


def test_glance_tooltip_past_the_last_week_shows_the_forecast_or_nothing(page, live_server, seeded, db):
    seeded.tracker.target_completion = date(2026, 12, 18)
    db.commit()
    open_glance(page, live_server, seeded)
    end = glance_option(page)["series"][2]["data"][-1]["value"][0]  # the forecast end, after the last week (25 Sep)
    end_iso = (date(1970, 1, 1) + timedelta(days=end)).isoformat()
    assert end_iso > "2026-09-25"
    tip = glance_tip_at(page, end_iso)
    assert "Forecast" in tip and "Week ending" in tip
    for iso in ("2026-10-16", "2026-12-18"):  # between the last week and the forecast end; the target
        tip = glance_tip_at(page, iso)
        assert tip.strip() == "" or "Forecast" in tip or "Plan" in tip or "Actual" in tip, tip
    assert page.evaluate("window.__csp") == [] and page.evaluate("window.__errors") == []


def test_glance_chart_tooltip_on_hover(page, live_server, seeded):
    open_glance(page, live_server, seeded)
    page.locator(".chart-host-remaining-glance").hover()
    tooltip = page.locator(".chart-host-remaining-glance .chart-tooltip")
    expect(tooltip).to_be_visible()
    expect(tooltip).to_contain_text("Week ending")
    expect(tooltip).to_contain_text("Plan")
    assert page.evaluate("window.__csp") == [] and page.evaluate("window.__errors") == []


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_glance_chart_uses_the_agreed_colours(page, live_server, seeded, theme):
    page.add_init_script(f"localStorage.setItem('tracker-theme', '{theme}')")
    open_glance(page, live_server, seeded)
    expect(page.locator(".chart-host-remaining-glance")).to_have_attribute("data-chart-theme", theme)
    colours = {"light": ("#1260d0", "#008f82", "#c27a00"), "dark": ("#5b8ff0", "#22a596", "#b8801c")}[theme]
    series = {s["id"]: s for s in glance_option(page)["series"]}
    assert (
        series["actual"]["lineStyle"]["color"],
        series["plan"]["lineStyle"]["color"],
        series["forecast"]["lineStyle"]["color"],
    ) == colours


def test_glance_chart_follows_the_theme_toggle(page, live_server, seeded):
    open_glance(page, live_server, seeded)
    start = page.evaluate("document.documentElement.getAttribute('data-theme')")
    other = "dark" if start == "light" else "light"
    page.click("[data-theme-toggle]")
    expect(page.locator(".chart-host-remaining-glance")).to_have_attribute("data-chart-theme", other)


def test_glance_picture_stays_when_the_chart_data_fails(page, live_server, seeded):
    page.route("**/report/data.json*", lambda route: route.fulfill(status=500, body="error"))
    page.add_init_script(RECORDER)
    browser_sign_in(page, live_server, seeded.viewer)
    page.goto(f"{live_server}/trackers/{seeded.tracker.id}/report?view=new&week=2026-09-11")
    page.wait_for_load_state("networkidle")
    expect(page.locator("img[data-chart='remaining-glance']")).to_be_visible()
    assert page.evaluate("window.__errors") == []


def patch_chart_data(page, **changes):
    def handle(route):
        data = route.fetch().json()
        data.update(changes)
        route.fulfill(content_type="application/json", body=json.dumps(data))

    page.route("**/report/data.json*", handle)


def test_glance_chart_names_the_week_in_progress(page, live_server, seeded):
    patch_chart_data(page, report_week_in_progress=True)
    open_glance(page, live_server, seeded)
    host = page.locator(".chart-host-remaining-glance")
    expect(host.locator("svg text", has_text=re.compile(r"^This week, ending 11 Sep$")).first).to_be_visible()
    expect(host.locator("svg text", has_text=re.compile(r"^Week ending 11 Sep$"))).to_have_count(0)


def test_glance_chart_draws_no_forecast_backwards(page, live_server, seeded):
    patch_chart_data(page, forecast_end="2026-09-04")
    open_glance(page, live_server, seeded)
    series = {s["id"]: s for s in glance_option(page)["series"]}
    assert series["forecast"]["data"] == []


def test_glance_chart_steps_the_y_axis_to_the_size_of_the_tracker(page, live_server, seeded):
    open_glance(page, live_server, seeded)
    axis = glance_option(page)["yAxis"][0]
    assert axis["interval"] == 20 and axis["max"] == 100  # five steps, not drawn flat in 0 to 100 by hundreds


def test_glance_chart_with_a_lone_target_has_no_number_badge(page, live_server, seeded, db):
    from datetime import datetime, timezone

    from report_helpers import add_target_change

    add_target_change(db, seeded.tracker, None, date(2026, 12, 18), datetime(2026, 9, 1, 9, tzinfo=timezone.utc))
    open_glance(page, live_server, seeded)
    host = page.locator(".chart-host-remaining-glance")
    expect(host.locator("svg text", has_text="Target 18 Dec").first).to_be_visible()
    lines = [s for s in glance_option(page)["series"] if s["id"] == "targets"][0]["markLine"]["data"]
    assert len(lines) == 1 and lines[0]["label"]["show"] is False
    expect(host.locator("svg text", has_text=re.compile(r"^1$"))).to_have_count(0)
    assert page.evaluate("window.__csp") == [] and page.evaluate("window.__errors") == []


def test_glance_direct_labels_sit_clear_of_the_lines(page, live_server, seeded):
    open_glance(page, live_server, seeded)
    series = {s["id"]: s for s in glance_option(page)["series"]}
    plan = [d for d in series["plan"]["data"] if isinstance(d, dict) and "label" in d][0]["label"]
    assert plan["align"] == "right" and plan["distance"] >= 12  # below the ring, to the side the line has left
    forecast = [d for d in series["forecast"]["data"] if isinstance(d, dict) and "label" in d][0]["label"]
    assert forecast["position"] == "top" and forecast["distance"] > 10


def test_glance_dots_appear_along_the_line_and_match_the_classic_size(page, live_server, seeded):
    open_glance(page, live_server, seeded)
    series = {s["id"]: s for s in glance_option(page)["series"]}
    for name in ("actual", "plan", "forecast"):
        # Clipped lines are revealed left to right, each dot showing as the line reaches it, as on the classic charts.
        assert series[name]["clip"] is True
        assert series[name]["symbolSize"] == 6
    forecast_end = [d for d in series["forecast"]["data"] if isinstance(d, dict) and "label" in d][0]
    assert forecast_end["symbolSize"] == 6


def test_glance_lines_reach_their_last_point_in_two_seconds(page, live_server, seeded, db):
    add_targets(db, seeded.tracker)  # the axis runs on to 18 Dec, well past the last point
    db.commit()
    open_glance(page, live_server, seeded)
    option = glance_option(page)
    low, high = option["xAxis"][0]["min"], option["xAxis"][0]["max"]
    lines = [s for s in option["series"] if s["id"] in ("actual", "plan", "forecast")]
    last = max((d["value"] if isinstance(d, dict) else d)[0] for s in lines for d in s["data"])
    for s in lines:
        # The reveal is steady (linear) across the plot, so the last point shows at this share of the duration.
        assert abs(s["animationDuration"] * (last - low) / (high - low) - 2000) <= 1


def test_glance_status_and_risks_sit_side_by_side_under_the_chart(page, live_server, seeded):
    page.set_viewport_size({"width": 1440, "height": 1200})
    open_glance(page, live_server, seeded)
    chart = page.locator("#glance-chart").bounding_box()
    status, risks = (
        page.locator(f"section[aria-labelledby='{n}']").bounding_box()
        for n in ("glance-status-title", "glance-risks-title")
    )
    tiles = page.locator(".glance-tile").all()
    first, second, third, fourth = (t.bounding_box() for t in tiles)
    assert chart["width"] == pytest.approx(fourth["x"] + fourth["width"] - first["x"], abs=1)  # full width
    assert status["y"] > chart["y"] + chart["height"] and risks["y"] == pytest.approx(status["y"], abs=1)
    # Each two tile columns wide.
    assert status["x"] == pytest.approx(first["x"], abs=1)
    assert status["x"] + status["width"] == pytest.approx(second["x"] + second["width"], abs=1)
    assert risks["x"] == pytest.approx(third["x"], abs=1)
    assert risks["x"] + risks["width"] == pytest.approx(fourth["x"] + fourth["width"], abs=1)
    page.set_viewport_size({"width": 390, "height": 900})
    status, risks = (
        page.locator(f"section[aria-labelledby='{n}']").bounding_box()
        for n in ("glance-status-title", "glance-risks-title")
    )
    assert risks["y"] > status["y"] + status["height"]  # stacked on a phone
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_glance_key_sits_to_the_right_of_the_target_date_changes(page, live_server, seeded, db):
    add_targets(db, seeded.tracker)
    db.commit()
    page.set_viewport_size({"width": 1440, "height": 1200})
    open_glance(page, live_server, seeded)
    targets = page.locator(".glance-targets").bounding_box()
    key = page.locator(".glance-legend").bounding_box()
    card = page.locator("#glance-chart").bounding_box()
    assert key["x"] >= targets["x"] + targets["width"]  # beside the list, not under it
    assert key["y"] == pytest.approx(targets["y"], abs=4)  # level with its heading
    assert key["x"] + key["width"] == pytest.approx(card["x"] + card["width"] - 18, abs=2)  # against the right edge
    assert page.evaluate("window.__csp") == []


def test_glance_key_without_target_changes_sits_on_the_right(page, live_server, seeded):
    page.set_viewport_size({"width": 1440, "height": 1200})
    open_glance(page, live_server, seeded)
    expect(page.locator(".glance-targets")).to_have_count(0)
    key = page.locator(".glance-legend").bounding_box()
    card = page.locator("#glance-chart").bounding_box()
    assert key["x"] > card["x"] + card["width"] / 2


def test_answer_card_in_progress_pill_lines_up_with_the_status(page, live_server, seeded):
    open_glance(page, live_server, seeded)
    # The fixture's week is finished, so add the pill the server draws for a week in progress.
    page.evaluate(
        """() => document.querySelector('.answer-badges').insertAdjacentHTML('beforeend',
        '<span class="status-badge status-badge-progress">In progress</span>')"""
    )
    status = page.locator(".answer-badges .status-badge").first.bounding_box()
    pill = page.locator(".status-badge-progress").bounding_box()
    assert pill["height"] == pytest.approx(status["height"], abs=1)
    assert pill["y"] == pytest.approx(status["y"], abs=1)
    assert pill["x"] - (status["x"] + status["width"]) == pytest.approx(8, abs=1)


def test_glance_locations_sit_three_to_a_row(page, live_server, seeded, db):
    for number in range(2, 5):
        db.add(Group(tracker_id=seeded.tracker.id, name=f"Site {number}", baseline=50, sort_order=number))
    db.commit()
    page.set_viewport_size({"width": 1440, "height": 1200})
    open_glance(page, live_server, seeded)
    boxes = [item.bounding_box() for item in page.locator(".glance-location").all()]
    assert len(boxes) == 4
    assert boxes[0]["y"] == boxes[1]["y"] == boxes[2]["y"] < boxes[3]["y"]
    assert boxes[3]["x"] == pytest.approx(boxes[0]["x"], abs=1)
    page.set_viewport_size({"width": 390, "height": 900})
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_glance_top_risks_table_sorts_by_its_headings(page, live_server, seeded, db):
    from tracker.models import Risk

    for ref, rag, due in (("R1", "Red", date(2026, 9, 30)), ("R2", "Amber", date(2026, 9, 1)), ("R3", "Green", None)):
        db.add(Risk(tracker_id=seeded.tracker.id, ref=ref, description=f"Risk {ref}", rag=rag, target_date=due))
    db.commit()
    open_glance(page, live_server, seeded)
    table = page.locator("#glance-risks-table")
    first_cells = table.locator("tbody tr td:nth-child(2) strong")
    expect(first_cells).to_have_text(["R1", "R2", "R3"])  # worst first, as the server orders them
    table.get_by_role("button", name="Due").click()
    expect(first_cells).to_have_text(["R2", "R1", "R3"])  # earliest first, no date last
    expect(table.locator("th").nth(2)).to_have_attribute("aria-sort", "ascending")
    table.get_by_role("button", name="Due").click()
    expect(first_cells).to_have_text(["R1", "R2", "R3"])  # latest first, no date still last
    assert "sort" not in page.url  # the address keeps only the week and the view
    assert page.evaluate("window.__csp") == [] and page.evaluate("window.__errors") == []
