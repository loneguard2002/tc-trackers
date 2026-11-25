"""Weekly update and targets pages in a real browser (database)."""

from __future__ import annotations

import re
from datetime import date, timedelta

import pytest
from conftest import browser_sign_in
from playwright.sync_api import expect

from tracker.engine.weeks import week_ending_for
from tracker.models import CompletionEntry, Group, ReportInput, Week

pytestmark = pytest.mark.browser

RECORDER = (
    "window.__csp = []; window.__errors = [];"
    "document.addEventListener('securitypolicyviolation',"
    " e => window.__csp.push(e.violatedDirective + ' ' + e.blockedURI));"
    "window.addEventListener('error', e => window.__errors.push(String(e.message)));"
)

# Three weeks in the past and five to come, so some weeks have actuals and some are still blank and upcoming.
FIRST = week_ending_for(date.today() - timedelta(days=21), 4)
WEEKS = [FIRST + timedelta(weeks=k) for k in range(8)]


@pytest.fixture
def editor(page, live_server, tracker_factory, user_factory, grant, db):
    tracker = tracker_factory(name="Plan tracker", first_week_ending=WEEKS[0], last_week_ending=WEEKS[-1])
    group = Group(tracker_id=tracker.id, name="Site A", baseline=100)
    db.add(group)
    db.flush()
    db.add(Week(tracker_id=tracker.id, week_ending=WEEKS[0], target=10))
    db.add(
        CompletionEntry(
            tracker_id=tracker.id,
            group_id=group.id,
            quantity=8,
            entry_date=WEEKS[0] - timedelta(days=1),
            week_ending=WEEKS[0],
        )
    )
    db.add(
        ReportInput(
            tracker_id=tracker.id, week_ending=WEEKS[0], status="Amber", headline="Slow start", decisions="More staff"
        )
    )
    db.commit()
    user = user_factory()
    grant(user, tracker, "editor")
    browser_sign_in(page, live_server, user)
    return tracker


def test_targets_summary_follows_the_inputs(page, live_server, editor):
    page.goto(f"{live_server}/trackers/{editor.id}/targets")
    expect(page.locator('[data-stat="planned"]')).to_have_text("10")
    expect(page.locator('[data-stat="planned-sub"]')).to_have_text("90 devices not yet planned")
    page.fill(f"#target-{WEEKS[1].isoformat()}", "30")
    expect(page.locator('[data-stat="planned"]')).to_have_text("40")
    expect(page.locator("[data-dirty-note]")).to_have_text("1 week changed, not saved yet")
    expect(page.locator("[data-targets-charts] rect.plot-target")).to_have_count(2)


def test_targets_spread_fills_blank_upcoming_weeks_and_reset_undoes_it(page, live_server, editor):
    page.goto(f"{live_server}/trackers/{editor.id}/targets")
    page.click("[data-spread]")
    values = [page.input_value(f"#target-{w.isoformat()}") for w in WEEKS]
    assert values[0] == "10" and sum(int(v) for v in values if v) == 100
    expect(page.locator('[data-stat="planned-sub"]')).to_have_text("The plan covers the full scope")
    page.click("button[type=reset]")
    expect(page.locator('[data-stat="planned"]')).to_have_text("10")


def test_a_target_note_folds_out_counts_as_a_change_and_saves(page, live_server, editor, db):
    page.add_init_script(RECORDER)
    page.goto(f"{live_server}/trackers/{editor.id}/targets")
    week = WEEKS[2].isoformat()
    button = page.locator(f'[aria-controls="note-row-{week}"]')
    field = page.locator(f"#note-{week}")
    expect(field).to_be_hidden()
    expect(button).to_have_attribute("aria-expanded", "false")
    button.click()
    expect(field).to_be_focused()
    expect(button).to_have_attribute("aria-expanded", "true")
    field.fill("Bank holiday on Monday")
    expect(page.locator("[data-dirty-note]")).to_have_text("1 week changed, not saved yet")
    page.locator(f"#note-row-{week} [data-note-done]").click()
    expect(field).to_be_hidden()
    expect(button).to_be_focused()
    expect(button).to_have_class("note-toggle has-note")
    expect(button).to_have_attribute("aria-label", re.compile("^Edit the note"))
    preview = page.locator("tr", has=button).locator("[data-note-preview]")
    expect(preview).to_have_text("Bank holiday on Monday")
    # Escape closes an open note too.
    button.click()
    expect(preview).to_be_hidden()
    field.press("Escape")
    expect(field).to_be_hidden()
    page.get_by_role("button", name="Save targets").click()
    expect(page.get_by_text("Targets saved.")).to_be_visible()
    db.expire_all()
    assert db.get(Week, (editor.id, WEEKS[2])).note == "Bank holiday on Monday"
    assert page.evaluate("window.__csp") == [] and page.evaluate("window.__errors") == []


def test_removing_a_target_note_and_reset_brings_it_back(page, live_server, editor, db):
    db.get(Week, (editor.id, WEEKS[0])).note = "Slow start"
    db.commit()
    page.goto(f"{live_server}/trackers/{editor.id}/targets")
    week = WEEKS[0].isoformat()
    preview = page.locator(f"#target-{week}").locator("xpath=ancestor::tr").locator("[data-note-preview]")
    expect(preview).to_have_text("Slow start")
    page.click(f'[aria-controls="note-row-{week}"]')
    page.locator(f"#note-row-{week} [data-note-clear]").click()
    expect(preview).to_be_hidden()
    expect(page.locator("[data-dirty-note]")).to_have_text("1 week changed, not saved yet")
    page.click("button[type=reset]")
    expect(preview).to_have_text("Slow start")


def test_inputs_preview_follows_the_form(page, live_server, editor):
    page.goto(f"{live_server}/trackers/{editor.id}/inputs?week={WEEKS[1].isoformat()}")
    band = page.locator("[data-band]")
    expect(band).to_have_class("report-band report-band-none")
    page.check("input[name=status][value=Red]")
    page.fill("#headline", "Supplier delay")
    expect(band).to_have_class("report-band report-band-red")
    expect(page.locator("[data-band-word]")).to_have_text("Red")
    expect(page.locator("[data-band-headline]")).to_have_text("Supplier delay")
    expect(page.locator("[data-dirty-note]")).to_have_text("Unsaved changes")


def test_inputs_copy_last_week(page, live_server, editor):
    page.goto(f"{live_server}/trackers/{editor.id}/inputs?week={WEEKS[1].isoformat()}")
    page.click("[data-copy-button]")
    assert page.input_value("#headline") == "Slow start" and page.input_value("#decisions") == "More staff"
    expect(page.locator("input[name=status][value=Amber]")).to_be_checked()
    expect(page.locator("[data-band-decisions]")).to_have_text("More staff")


def test_inputs_week_strip_marks_written_weeks(page, live_server, editor):
    page.goto(f"{live_server}/trackers/{editor.id}/inputs?week={WEEKS[1].isoformat()}")
    chips = page.locator("[data-week-strip] .week-chip")
    expect(chips).to_have_count(len(WEEKS))
    expect(chips.nth(0).locator(".rag-dot")).to_have_class("rag-dot rag-dot-amber")
    expect(chips.nth(1)).to_have_attribute("aria-current", "page")


def inputs_url(live_server, tracker, week=None):
    return f"{live_server}/trackers/{tracker.id}/inputs?week={(week or WEEKS[0]).isoformat()}"


def test_the_week_strip_starts_closed_and_the_week_button_opens_it(page, live_server, editor):
    page.add_init_script(RECORDER)
    page.goto(inputs_url(live_server, editor, WEEKS[1]))
    button = page.locator("[data-week-toggle]")
    strip = page.locator("[data-week-strip]")
    expect(button).to_have_attribute("aria-expanded", "false")
    expect(button).to_contain_text("Week ending")
    expect(strip).to_be_hidden()
    button.click()
    expect(button).to_have_attribute("aria-expanded", "true")
    expect(strip).to_be_visible()
    expect(strip.locator(".week-chip")).to_have_count(len(WEEKS))
    page.keyboard.press("Tab")
    button.focus()
    page.keyboard.press("Enter")
    expect(strip).to_be_hidden()
    assert page.evaluate("window.__csp") == []
    assert page.evaluate("window.__errors") == []


def test_the_week_strip_shows_without_javascript(browser, live_server, editor, page):
    context = browser.new_context(java_script_enabled=False)
    try:
        bare = context.new_page()
        cookies = page.context.cookies()
        context.add_cookies(cookies)
        bare.goto(inputs_url(live_server, editor))
        expect(bare.locator("[data-week-strip]")).to_be_visible()
    finally:
        context.close()


def test_the_week_bar_and_tiles_show_the_weeks_figures(page, live_server, editor):
    page.goto(inputs_url(live_server, editor))
    bar = page.locator(".week-bar")
    expect(bar.locator(".week-state")).to_have_text("Written \u00b7 Amber")
    expect(bar.locator(".week-deadline")).to_have_text("Automatic sending is off")
    expect(bar.get_by_role("link", name="Latest week")).to_be_visible()
    tiles = page.locator(".access-tiles .access-tile")
    expect(tiles).to_have_count(6)
    expect(tiles.nth(0).locator(".access-tile-label")).to_have_text("Done this week")
    expect(tiles.nth(0).locator(".access-tile-count")).to_have_text("8")
    expect(tiles.nth(0).locator(".figure-sub")).to_have_text("of 10 \u00b7 \u22122 against target")
    expect(tiles.nth(0).locator(".figure-sub")).to_have_class("figure-sub tone-danger")
    expect(tiles.nth(1).locator(".figure-sub")).to_contain_text("left")
    expect(tiles.nth(5).locator(".access-tile-label")).to_have_text("Red risks")
    expect(page.get_by_text("This week's figures")).to_have_count(0)


def test_the_cards_sit_side_by_side_from_1000_pixels_and_stack_below(page, live_server, editor):
    url = inputs_url(live_server, editor)
    page.set_viewport_size({"width": 1000, "height": 900})
    page.goto(url)
    commentary = page.locator("[data-inputs-form] section").first.bounding_box()
    reminder = page.locator(".reminder-card").bounding_box()
    assert reminder["x"] > commentary["x"] + commentary["width"] - 1
    assert abs(reminder["y"] - commentary["y"]) < 2
    assert commentary["width"] > reminder["width"]
    # The preview sits inside the Commentary card.
    inside = page.locator("[data-inputs-form] section").first.locator("[data-band]")
    expect(inside).to_have_count(1)
    page.set_viewport_size({"width": 999, "height": 900})
    commentary = page.locator("[data-inputs-form] section").first.bounding_box()
    reminder = page.locator(".reminder-card").bounding_box()
    assert reminder["y"] >= commentary["y"] + commentary["height"] - 1
    assert abs(reminder["x"] - commentary["x"]) < 2


def test_nothing_on_the_page_follows_the_scroll_except_the_save_bar(page, live_server, editor):
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(inputs_url(live_server, editor))
    sticky = page.evaluate(
        """() => Array.from(document.querySelectorAll('.inputs-page, .inputs-page *'))
            .filter(e => ['sticky', 'fixed'].includes(getComputedStyle(e).position))
            .map(e => e.className)"""
    )
    assert [c for c in sticky if "settings-actions" not in c] == []


def test_the_save_bar_stays_at_the_bottom_down_to_the_end_of_the_page(page, live_server, editor):
    page.add_init_script(RECORDER)
    page.set_viewport_size({"width": 1440, "height": 600})
    page.goto(inputs_url(live_server, editor, WEEKS[1]))
    bar = page.locator(".settings-actions")
    page.evaluate("window.scrollTo(0, 300)")
    box = bar.bounding_box()
    assert abs(box["y"] + box["height"] - (600 - 12)) < 2  # pinned 12px above the bottom of the window
    # At the end of the page it sits below the Past updates table, not above it.
    page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
    box = bar.bounding_box()
    past = page.locator(".past-updates").bounding_box()
    assert box["y"] >= past["y"] + past["height"] - 1
    # The button outside the form still saves it.
    page.fill("#headline", "Saved from the bar")
    expect(page.locator("[data-dirty-note]")).to_have_class("settings-actions-note is-dirty")
    bar.get_by_role("button", name="Save").click()
    expect(page.locator(".flash")).to_contain_text("Weekly update saved.")
    expect(page.locator("#headline")).to_have_value("Saved from the bar")
    assert page.evaluate("window.__csp") == []
    assert page.evaluate("window.__errors") == []


def test_headline_and_decisions_share_one_row_and_stack_when_narrow(page, live_server, editor):
    page.add_init_script(RECORDER)
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(inputs_url(live_server, editor))
    headline = page.locator("#headline").bounding_box()
    decisions = page.locator("#decisions").bounding_box()
    assert abs(headline["y"] - decisions["y"]) < 2  # the same row
    assert decisions["x"] > headline["x"] + headline["width"]  # decisions to the right
    assert abs(headline["height"] - decisions["height"]) < 2
    page.set_viewport_size({"width": 390, "height": 800})
    headline = page.locator("#headline").bounding_box()
    decisions = page.locator("#decisions").bounding_box()
    assert decisions["y"] > headline["y"] + headline["height"]  # stacked on a phone
    assert abs(headline["x"] - decisions["x"]) < 2
    assert page.evaluate("window.__csp") == []
    assert page.evaluate("window.__errors") == []


def test_the_page_does_not_scroll_sideways_on_a_phone(page, live_server, editor):
    page.set_viewport_size({"width": 390, "height": 800})
    page.goto(inputs_url(live_server, editor))
    page.click("[data-week-toggle]")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_the_past_updates_table_searches_filters_and_opens_a_week(page, live_server, editor):
    page.add_init_script(RECORDER)
    page.goto(inputs_url(live_server, editor, WEEKS[3]))
    rows = page.locator("#past-updates tbody tr")
    expect(rows).to_have_count(3)
    expect(page.locator("[data-pager-for='past-updates'] [data-pager-count]")).to_have_text("Showing 3 of 3 weeks")
    page.fill("[data-search-for='past-updates'] input", "slow")
    expect(page.locator("#past-updates tbody tr:not([hidden])")).to_have_count(1)
    expect(page.locator("[data-pager-for='past-updates'] [data-pager-count]")).to_have_text("Showing 1 of 3 weeks")
    page.click("[data-clear-for='past-updates']")
    expect(page.locator("[data-pager-for='past-updates'] [data-pager-count]")).to_have_text("Showing 3 of 3 weeks")
    page.click("[data-status-for='past-updates'] [data-status='unwritten']")
    expect(page.locator("[data-pager-for='past-updates'] [data-pager-count]")).to_have_text("Showing 2 of 3 weeks")
    assert "past-filter=unwritten" in page.url
    page.click("[data-clear-for='past-updates']")
    page.get_by_role("link", name="Open").last.click()
    expect(page).to_have_url(inputs_url(live_server, editor, WEEKS[0]))
    assert page.evaluate("window.__csp") == []
    assert page.evaluate("window.__errors") == []
