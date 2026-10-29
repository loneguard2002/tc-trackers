"""Settings and Email pages in a real browser, under the Content Security Policy (database)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from conftest import browser_sign_in
from playwright.sync_api import expect
from test_report_page_browser import RECORDER

from tracker.engine.weeks import week_ending_for
from tracker.models import CompletionEntry, Group, Recipient

pytestmark = pytest.mark.browser

FIRST = week_ending_for(date.today() - timedelta(days=28), 4)
LAST = FIRST + timedelta(weeks=9)


@pytest.fixture
def admin(page, live_server, tracker_factory, user_factory, grant, db):
    tracker = tracker_factory(name="Live tracker", first_week_ending=FIRST, last_week_ending=LAST)
    group = Group(tracker_id=tracker.id, name="Site A", baseline=200)
    db.add(group)
    db.flush()
    for k, quantity in enumerate((10, 20, 30)):
        week = FIRST + timedelta(weeks=k)
        db.add(
            CompletionEntry(
                tracker_id=tracker.id,
                group_id=group.id,
                quantity=quantity,
                entry_date=week - timedelta(days=1),
                week_ending=week,
            )
        )
    db.add(Recipient(tracker_id=tracker.id, email="a@example.com"))
    db.commit()
    user = user_factory(is_admin=True)
    grant(user, tracker, "owner")
    page.add_init_script(RECORDER)
    browser_sign_in(page, live_server, user)
    return tracker


def assert_clean(page):
    assert page.evaluate("window.__csp") == []
    assert page.evaluate("window.__errors") == []


def test_settings_lines_follow_the_fields(page, live_server, admin):
    page.goto(f"{live_server}/trackers/{admin.id}/settings")
    note = page.locator("[data-dirty-note]")
    expect(note).to_have_text("No unsaved changes")
    page.fill("#group_label", "Country")
    expect(page.locator("[data-live-groups]")).to_have_text("Countries")
    expect(note).to_have_text("1 setting changed, not saved yet")
    expect(page.locator("[data-timeline] rect")).to_have_count(10)
    expect(page.locator("[data-live='period']")).to_contain_text("10 weeks")
    forecast = page.locator("[data-live='forecast']")
    page.get_by_role("button", name="One week fewer").click()
    page.get_by_role("button", name="One week fewer").click()
    expect(page.locator("#moving_average_weeks")).to_have_value("1")
    expect(page.get_by_role("button", name="One week fewer")).to_be_disabled()
    expect(forecast).to_contain_text("the average of the last 1 week (")
    expect(note).to_have_text("2 settings changed, not saved yet")
    page.get_by_role("button", name="Discard changes").click()
    expect(note).to_have_text("No unsaved changes")
    expect(page.locator("[data-live-groups]")).to_have_text("Locations")
    assert_clean(page)


def test_schedule_line_says_what_saving_will_do(page, live_server, admin):
    page.goto(f"{live_server}/trackers/{admin.id}/settings")
    line = page.locator("[data-live='schedule']")
    expect(line).to_contain_text("Off.")
    page.locator("label.switch-row").click()
    page.fill("#send_time", "08:15")
    expect(line).to_have_text("Once saved: every Friday at 08:15 (Europe/London) to 1 recipient on the Email tab.")


def test_archive_asks_in_the_page(page, live_server, admin):
    page.goto(f"{live_server}/trackers/{admin.id}/settings")
    dialogs = []
    page.on("dialog", lambda dialog: (dialogs.append(dialog.message), dialog.dismiss()))
    page.get_by_role("button", name="Archive tracker…").click()
    box = page.locator("#archive [data-confirm-box]")
    expect(box).to_contain_text("Archive Live tracker?")
    box.get_by_role("button", name="Cancel").click()
    expect(box).to_be_hidden()
    page.get_by_role("button", name="Archive tracker…").click()
    box.get_by_role("button", name="Archive").click()
    expect(page.get_by_text("Tracker archived.")).to_be_visible()
    assert dialogs == []


def test_email_preview_follows_the_template(page, live_server, admin):
    page.goto(f"{live_server}/trackers/{admin.id}/mail")
    page.fill("#subject", "Weekly: {{tracker_name}}")
    expect(page.locator("[data-preview-subject]")).to_have_text("Subject: Weekly: Live tracker")
    page.fill("#body_html", "<p>Hello {{nope}}</p>")
    expect(page.locator("[data-unknown]")).to_have_text("Unknown placeholders will be sent as written: nope.")
    page.locator("#body_html").focus()
    page.locator("#body_html").press("End")
    page.get_by_role("button", name="status", exact=True).click()
    expect(page.locator("#body_html")).to_have_value("<p>Hello {{nope}}</p>{{status}}")
    frame = page.frame_locator("[data-preview-frame]")
    expect(frame.locator("body")).to_contain_text("Hello {{nope}}")
    expect(page.locator("[data-dirty-note]")).to_have_text("Unsaved changes; the preview shows them")
    assert_clean(page)


def test_send_to_everyone_asks_in_the_page(page, live_server, admin):
    page.goto(f"{live_server}/trackers/{admin.id}/mail")
    page.get_by_role("button", name="Send to 1 recipient…").click()
    box = page.locator("#sending [data-confirm-box]")
    expect(box).to_contain_text("to 1 recipient now. It cannot be recalled.")
    box.get_by_role("button", name="Cancel").click()
    expect(box).to_be_hidden()
    assert_clean(page)
