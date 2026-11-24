"""The calendar reminder history side panel in a real browser, with and without JavaScript (database)."""

from __future__ import annotations

import pytest
from conftest import browser_sign_in
from playwright.sync_api import expect

from tracker.calendar_invites.service import record_event
from tracker.mail import smtp
from tracker.models import CalendarReminder

pytestmark = pytest.mark.browser

RECORDER = (
    "window.__csp = []; window.__errors = [];"
    "document.addEventListener('securitypolicyviolation',"
    " e => window.__csp.push(e.violatedDirective + ' ' + e.blockedURI));"
    "window.addEventListener('error', e => window.__errors.push(String(e.message)));"
)
CONFIRM = "Switch the calendar reminder off? A cancellation is sent to Outlook."


@pytest.fixture(autouse=True)
def email_set_up(monkeypatch):
    monkeypatch.setattr(
        smtp, "get_smtp_config", lambda session=None: {"host": "smtp.example.com", "from_": "reports@example.com"}
    )


@pytest.fixture
def mail(monkeypatch):
    sent: list = []
    monkeypatch.setattr(smtp, "send_message", sent.append)
    return sent


@pytest.fixture
def editor(page, live_server, db, tracker_factory, user_factory, grant):
    tracker = tracker_factory(name="Fit-out")
    user = user_factory(email="person@example.com")
    grant(user, tracker, "editor")
    db.add(CalendarReminder(user_id=user.id, tracker_id=tracker.id, enabled=True, sequence=0, sent_state="none"))
    record_event(db, user.id, tracker.id, "switched_on", "By you")
    record_event(db, user.id, tracker.id, "sent", "Fridays, 08:45 to 09:00 (London time), 4 Sep – 25 Dec 2026")
    record_event(db, user.id, tracker.id, "failed", "Mail host refused the message")
    record_event(db, user.id, tracker.id, "downloaded", "Fit-out reminder.ics")
    db.commit()
    browser_sign_in(page, live_server, user)
    return tracker, user


def open_panel(page, live_server, tracker):
    page.add_init_script(RECORDER)
    page.goto(f"{live_server}/trackers/{tracker.id}/inputs")
    page.click("[data-history-url]")
    panel = page.locator("dialog.perm-drawer")
    expect(panel.locator("#history-table[data-table-ready]")).to_be_attached()
    return panel


def first_what(panel) -> str:
    return panel.locator("#history-table tbody tr:visible td").nth(1).inner_text()


def test_the_panel_opens_filters_sorts_and_closes(page, live_server, editor):
    tracker, _ = editor
    panel = open_panel(page, live_server, tracker)
    address = page.url
    expect(panel.locator("h2")).to_have_text("Calendar reminder")
    expect(panel.locator(".drawer-head p")).to_have_text("Fit-out · sent to person@example.com")
    expect(panel.locator(".pager-count")).to_have_text("Showing 4 of 4 events")
    assert first_what(panel) == "Downloaded"

    panel.get_by_role("button", name="Failed").click()
    expect(panel.locator(".pager-count")).to_have_text("Showing 1 of 4 events")
    panel.get_by_role("button", name="All", exact=False).first.click()
    panel.get_by_placeholder("Search history").fill("ics")
    expect(panel.locator(".pager-count")).to_have_text("Showing 1 of 4 events")
    panel.get_by_placeholder("Search history").fill("nothing like this")
    expect(panel.get_by_text("No events match.")).to_be_visible()
    panel.locator("[data-no-match] [data-clear-for]").click()
    expect(panel.locator(".pager-count")).to_have_text("Showing 4 of 4 events")

    panel.get_by_role("button", name="When").click()
    assert first_what(panel) == "Switched on"
    panel.get_by_role("button", name="When").click()
    assert first_what(panel) == "Downloaded"
    assert page.url == address

    page.keyboard.press("Escape")
    expect(panel).to_be_hidden()
    expect(page.locator("[data-history-url]")).to_be_focused()
    page.click("[data-history-url]")
    expect(panel.locator("#history-table[data-table-ready]")).to_be_attached()
    panel.get_by_role("button", name="Close").click()
    expect(panel).to_be_hidden()
    expect(page.locator("[data-history-url]")).to_be_focused()
    page.click("[data-history-url]")
    expect(panel.locator("#history-table[data-table-ready]")).to_be_attached()
    page.mouse.click(10, 300)
    expect(panel).to_be_hidden()
    expect(page.locator("[data-history-url]")).to_be_focused()
    assert page.url == address
    assert page.evaluate("window.__csp") == []
    assert page.evaluate("window.__errors") == []


def test_opening_it_twice_sets_the_table_up_once(page, live_server, editor):
    tracker, _ = editor
    panel = open_panel(page, live_server, tracker)
    page.keyboard.press("Escape")
    page.click("[data-history-url]")
    expect(panel.locator("#history-table[data-table-ready]")).to_be_attached()
    assert page.locator("#history-table").count() == 1
    assert page.locator("[data-search-for=history-table]").count() == 1
    expect(panel.locator(".pager-count")).to_have_text("Showing 4 of 4 events")
    assert page.evaluate("window.__errors") == []


def test_the_menu_downloads_resends_and_switches_off(page, live_server, editor, mail, db):
    tracker, user = editor
    panel = open_panel(page, live_server, tracker)
    panel.get_by_role("button", name="More for the calendar reminder").click()
    items = panel.get_by_role("menuitem")
    expect(items).to_have_text(["Download invite (.ics)", "Email it again", "Switch the reminder off…"])
    expect(items.first).to_have_attribute("href", f"/trackers/{tracker.id}/calendar-reminder.ics")
    page.keyboard.press("ArrowDown")
    expect(items.nth(1)).to_be_focused()
    page.keyboard.press("Escape")
    expect(panel).to_be_visible()
    expect(panel.get_by_role("menuitem").first).to_be_hidden()

    panel.get_by_role("button", name="More for the calendar reminder").click()
    asked: list[str] = []
    page.once("dialog", lambda d: (asked.append(d.message), d.dismiss()))
    items.nth(2).click()
    assert asked == [CONFIRM]
    db.expire_all()
    assert db.get(CalendarReminder, (user.id, tracker.id)).enabled is True

    panel.get_by_role("button", name="More for the calendar reminder").click()
    page.once("dialog", lambda d: (asked.append(d.message), d.accept()))
    items.nth(2).click()
    expect(page.locator(".flash")).to_contain_text("Calendar reminder")
    db.expire_all()
    assert db.get(CalendarReminder, (user.id, tracker.id)).enabled is False


def test_the_menu_emails_it_again(page, live_server, editor, mail):
    tracker, _ = editor
    page.add_init_script(RECORDER)
    page.goto(f"{live_server}/trackers/{tracker.id}/inputs")
    page.click("[data-history-url]")
    panel = page.locator("dialog.perm-drawer")
    expect(panel.locator("#history-table[data-table-ready]")).to_be_attached()
    panel.get_by_role("button", name="More for the calendar reminder").click()
    panel.get_by_role("menuitem", name="Email it again").click()
    expect(page.locator(".flash")).to_have_text("Calendar reminder sent again to person@example.com.")
    assert len(mail) == 1


def test_the_link_goes_to_the_history_page_without_javascript(browser, live_server, editor):
    tracker, user = editor
    context = browser.new_context(java_script_enabled=False)
    try:
        page = context.new_page()
        browser_sign_in(page, live_server, user)
        page.goto(f"{live_server}/trackers/{tracker.id}/inputs")
        page.click("[data-history-url]")
        expect(page).to_have_url(f"{live_server}/trackers/{tracker.id}/calendar-reminder/history")
        expect(page.get_by_role("heading", name="Calendar reminder")).to_be_visible()
        expect(page.locator("#history-table tbody tr")).to_have_count(4)
    finally:
        context.close()
