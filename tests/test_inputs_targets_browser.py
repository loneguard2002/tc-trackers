"""Weekly inputs and targets pages in a real browser (database)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from conftest import browser_sign_in
from playwright.sync_api import expect

from tracker.engine.weeks import week_ending_for
from tracker.models import CompletionEntry, Group, ReportInput, Week

pytestmark = pytest.mark.browser

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
