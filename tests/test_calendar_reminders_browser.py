"""The calendar reminder switch in a real browser, with and without JavaScript (database)."""

from __future__ import annotations

import pytest
from conftest import browser_sign_in
from playwright.sync_api import expect

from tracker.mail import smtp
from tracker.models import CalendarReminder

pytestmark = pytest.mark.browser

RECORDER = (
    "window.__csp = []; window.__errors = [];"
    "document.addEventListener('securitypolicyviolation',"
    " e => window.__csp.push(e.violatedDirective + ' ' + e.blockedURI));"
    "window.addEventListener('error', e => window.__errors.push(String(e.message)));"
)


@pytest.fixture
def mail(monkeypatch):
    sent: list = []
    monkeypatch.setattr(smtp, "send_message", sent.append)
    return sent


@pytest.fixture
def editor(page, live_server, tracker_factory, user_factory, grant):
    tracker = tracker_factory(name="Fit-out")
    user = user_factory(email="person@example.com")
    grant(user, tracker, "editor")
    browser_sign_in(page, live_server, user)
    return tracker, user


def test_the_switch_posts_on_change_and_the_panel_follows(page, live_server, editor, mail):
    tracker, _ = editor
    page.add_init_script(RECORDER)
    page.goto(f"{live_server}/trackers/{tracker.id}/inputs")
    expect(page.locator("[data-reminder-save]")).to_be_hidden()
    page.check("#calendar-reminder")
    expect(page.locator("#reminder-status")).to_contain_text("Sent to person@example.com on")
    expect(page.locator(".flash")).to_have_text("Calendar reminder sent to person@example.com.")
    assert len(mail) == 1
    page.uncheck("#calendar-reminder")
    expect(page.locator("#reminder-status")).to_have_text("Off.")
    assert len(mail) == 2
    assert page.evaluate("window.__csp") == []
    assert page.evaluate("window.__errors") == []


def test_the_switch_works_without_javascript(browser, live_server, editor, mail, db):
    tracker, user = editor
    context = browser.new_context(java_script_enabled=False)
    try:
        page = context.new_page()
        browser_sign_in(page, live_server, user)
        page.goto(f"{live_server}/trackers/{tracker.id}/inputs")
        expect(page.locator("[data-reminder-save]")).to_be_visible()
        page.locator("label[for=calendar-reminder]").click()
        page.click("[data-reminder-save]")
        expect(page.locator("#reminder-status")).to_contain_text("Sent to person@example.com on")
        page.click("text=Send it again")
        expect(page.locator(".flash")).to_have_text("Calendar reminder sent again to person@example.com.")
        assert len(mail) == 2
    finally:
        context.close()
    db.expire_all()
    assert db.get(CalendarReminder, (user.id, tracker.id)).enabled is True


def test_the_panel_is_reachable_by_keyboard(page, live_server, editor, mail):
    tracker, _ = editor
    page.goto(f"{live_server}/trackers/{tracker.id}/inputs")
    for _ in range(80):
        page.keyboard.press("Tab")
        if page.evaluate("document.activeElement.id") == "calendar-reminder":
            break
    else:
        pytest.fail("the switch never received focus")
    page.keyboard.press("Space")
    expect(page.locator("#reminder-status")).to_contain_text("Sent to person@example.com on")
    assert len(mail) == 1


def test_unsaved_update_text_blocks_the_switch_and_send_it_again(page, live_server, editor, mail):
    tracker, _ = editor
    url = f"{live_server}/trackers/{tracker.id}/inputs"
    page.goto(url)
    page.fill("#headline", "Work in progress")
    page.locator("label[for=calendar-reminder]").click()
    guard = page.locator("[data-reminder-guard]")
    expect(guard).to_have_text("Save your weekly update first.")
    assert page.url == url
    assert page.input_value("#headline") == "Work in progress"
    assert not page.is_checked("#calendar-reminder")
    assert mail == []
    # Save the update, switch on, then type again and try "Send it again".
    page.fill("#headline", "")
    page.locator("label[for=calendar-reminder]").click()
    expect(page.locator("#reminder-status")).to_contain_text("Sent to person@example.com on")
    assert len(mail) == 1
    page.fill("#headline", "More text")
    page.click("text=Send it again")
    expect(guard).to_have_text("Save your weekly update first.")
    assert page.input_value("#headline") == "More text"
    assert len(mail) == 1
