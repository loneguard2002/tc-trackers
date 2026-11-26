"""Settings and Email pages in a real browser, under the Content Security Policy (database)."""

from __future__ import annotations

import re
import threading
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from conftest import browser_sign_in
from playwright.sync_api import expect
from test_report_page_browser import RECORDER

from tracker.engine.weeks import week_ending_for
from tracker.mail import sending
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
    expect(page.locator(".subject-line")).to_contain_text("Live tracker | ")
    expect(page.locator("[data-preview-subject]")).to_contain_text("Subject: Live tracker | ")
    page.locator('[data-insert="tracker_name"]').click()  # the table's buttons only ever go into the body
    expect(page.locator("#body_html")).to_have_value(re.compile(r"\{\{tracker_name\}\}"))
    frame = page.frame_locator("[data-preview-frame]")
    expect(frame.locator(".mail-figures")).to_be_visible()  # the default message's parts render, not escaped
    expect(frame.locator("body")).not_to_contain_text("&lt;table")
    page.fill("#body_html", "<p>Hello {{nope}}</p>")
    expect(page.locator("[data-unknown]")).to_have_text("Unknown placeholders will be sent as written: nope.")
    page.locator("#body_html").focus()
    page.locator("#body_html").press("End")
    status = page.locator('[data-insert="status"]')
    expect(status).to_have_text("Insert", use_inner_text=True)  # the visible label only
    status.click()
    expect(page.locator("#body_html")).to_have_value("<p>Hello {{nope}}</p>{{status}}")
    expect(status).to_have_accessible_name("{{status}} is in the field. Insert it again")
    page.mouse.move(0, 0)  # not pointing at it, so it reads Inserted rather than Insert again
    expect(status).to_have_text("✓ Inserted", use_inner_text=True)
    status.click()  # in the body a placeholder may appear twice
    expect(page.locator("#body_html")).to_have_value("<p>Hello {{nope}}</p>{{status}}{{status}}")
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


@pytest.fixture
def slow_sends(monkeypatch):
    """Both sends wait until ``release`` is set, so the page can be seen while it waits; ``calls`` counts the posts."""
    state = SimpleNamespace(release=threading.Event(), calls=[])

    def slow(name, answer):
        def send(*args):
            state.calls.append(name)
            state.release.wait(10)
            return answer

        return send

    monkeypatch.setattr(sending, "send_report", slow("report", SimpleNamespace(status="sent")))
    monkeypatch.setattr(sending, "send_test", slow("test", None))
    yield state
    state.release.set()


# Playwright reads nothing in a page whose form post is still waiting for its answer, so the page reports its form's
# buttons as console messages instead, on every change: "[x]" marks a disabled button.
WATCH_BUTTONS = """form => new MutationObserver(() => console.log(Array.from(form.querySelectorAll("button"),
    button => (button.disabled ? "[x] " : "[ ] ") + button.textContent.trim()).join(" | ")))
  .observe(form, {attributes: true, childList: true, subtree: true, characterData: true})"""


def test_send_now_says_sending_and_sends_once(page, live_server, admin, slow_sends):
    page.goto(f"{live_server}/trackers/{admin.id}/mail")
    form = page.locator("#sending form.send-all")
    form.evaluate(WATCH_BUTTONS)
    page.get_by_role("button", name="Send to 1 recipient…").click()
    sending_now = "[x] Send to 1 recipient… | [x] Sending… | [x] Cancel"
    with page.expect_console_message(lambda message: message.text == sending_now):
        form.get_by_role("button", name="Send now").dblclick()
    slow_sends.release.set()
    expect(page.locator(".flash-success")).to_have_text(re.compile(r"The report for the week ending .* was sent\.$"))
    expect(page.get_by_role("button", name="Send to 1 recipient…")).to_be_enabled()
    assert slow_sends.calls == ["report"]
    assert_clean(page)


def test_send_a_test_says_sending_and_sends_once(page, live_server, admin, slow_sends):
    page.goto(f"{live_server}/trackers/{admin.id}/mail")
    form = page.locator("#sending .send-row form").first
    form.evaluate(WATCH_BUTTONS)
    with page.expect_console_message(lambda message: message.text == "[x] Sending…"):
        form.get_by_role("button", name="Send a test to me").dblclick()
    slow_sends.release.set()
    expect(page.get_by_text("A test email was sent to")).to_be_visible()
    assert slow_sends.calls == ["test"]
    assert_clean(page)


def test_a_page_back_from_the_cache_can_send_again(page, live_server, admin, slow_sends):
    page.goto(f"{live_server}/trackers/{admin.id}/mail")
    form = page.locator("#sending .send-row form").first
    form.evaluate(WATCH_BUTTONS)
    # The page cannot be reached while its post waits, so it plays the back-forward cache's pageshow itself.
    page.evaluate("""addEventListener("submit", () => setTimeout(() =>
        dispatchEvent(new PageTransitionEvent("pageshow", {persisted: true}))))""")
    with page.expect_console_message(lambda message: message.text.startswith("[ ] Send a test to me")):
        form.get_by_role("button", name="Send a test to me").click()
    slow_sends.release.set()
    expect(page.get_by_text("A test email was sent to")).to_be_visible()


def test_email_settings_subject_inserts_counts_and_shows_an_example(page, live_server, admin):
    page.goto(f"{live_server}/admin/smtp")
    subject = page.locator("#report_email_subject")
    count = page.locator("#report_email_subject-count")
    expect(subject).to_have_value("{{summary}}")
    expect(page.locator("[data-char-count]")).to_have_text("11 / 300")
    summary = page.locator('[data-insert="summary"]')
    expect(summary).to_have_accessible_name("{{summary}} is in the field. Remove it")
    expect(page.locator("[data-example-text]")).to_contain_text("Network refresh | 06/11/26 : Green")

    summary.click()  # in the subject the button takes the placeholder out again
    expect(subject).to_have_value("")
    expect(count).to_contain_text("Enter a subject")
    expect(summary).to_have_accessible_name("Insert {{summary}}")

    subject.fill("[PMO] ")
    subject.press("End")
    page.locator('[data-insert="tracker_name"]').click()
    expect(subject).to_have_value("[PMO] {{tracker_name}}")
    expect(page.locator("[data-example-text]")).to_have_text("[PMO] Network refresh")
    expect(page.locator("[data-example-length]")).to_have_text("· 21 characters once filled in")

    subject.fill("x" * 280)
    expect(page.locator("[data-char-note]")).to_have_text("20 characters left.")
    expect(page.locator("[data-char-count]")).to_have_text("280 / 300")
    subject.fill("x" * 305 + " {{sumary}}")
    expect(page.locator("[data-char-note]")).to_have_text("16 characters too many: shorten the subject to save.")
    expect(page.locator("[data-char-count]")).to_have_text("316 / 300")
    expect(subject).to_have_attribute("aria-invalid", "true")
    expect(page.locator("[data-unknown]")).to_have_text("Unknown placeholders will be sent as written: sumary.")
    page.get_by_role("button", name="Save", exact=True).click()  # refused in the page, before the server's 400
    expect(page).to_have_url(f"{live_server}/admin/smtp")
    expect(subject).to_be_focused()
    assert_clean(page)
