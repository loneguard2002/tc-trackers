"""The Feedback pop-up in a real browser, under the Content Security Policy (database)."""

from __future__ import annotations

import pytest
from conftest import browser_sign_in
from playwright.sync_api import expect
from sqlalchemy import select
from test_feedback_service import _png
from test_report_page_browser import RECORDER

from tracker.feedback import service
from tracker.models import FeedbackFile, FeedbackRequest

pytestmark = pytest.mark.browser

PASTE_A_PICTURE = """
() => {
  const bytes = Uint8Array.from(atob('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC'),
                                c => c.charCodeAt(0));
  const transfer = new DataTransfer();
  transfer.items.add(new File([bytes], 'image.png', { type: 'image/png' }));
  const event = new ClipboardEvent('paste', { clipboardData: transfer, bubbles: true, cancelable: true });
  document.querySelector('#feedback-summary').dispatchEvent(event);
}
"""


def open_pop_up(page, live_server, user):
    page.add_init_script(RECORDER)
    browser_sign_in(page, live_server, user)
    page.goto(f"{live_server}/")
    page.get_by_role("link", name="Feedback on this page").click()
    dialog = page.locator("#feedback-dialog")
    expect(dialog).to_be_visible()
    return dialog


def test_the_link_opens_the_pop_up_and_the_form_works(page, live_server, user_factory, db):
    sam = user_factory(full_name="Sam Taylor")
    dialog = open_pop_up(page, live_server, sam)
    expect(dialog.get_by_text("Tell us more")).to_be_visible()
    expect(dialog.locator("[data-feedback-page-line]")).to_contain_text("Trackers")

    dialog.get_by_text("Something is wrong").click()
    expect(dialog.locator("[data-feedback-details-label]")).to_have_text("What happened?")
    expect(dialog.locator("#feedback-details")).to_have_attribute(
        "placeholder", "What you did, what you expected, and what happened instead."
    )
    expect(dialog.locator("[data-feedback-details-help]")).to_have_text("Steps to see it again help us fix it sooner.")
    dialog.get_by_text("An idea", exact=True).click()
    expect(dialog.locator("[data-feedback-details-label]")).to_have_text("Tell us more")

    page.evaluate(PASTE_A_PICTURE)
    expect(dialog.locator("[data-feedback-list] li")).to_have_count(1)
    expect(dialog.locator("[data-feedback-list]")).to_contain_text("screenshot.png")

    dialog.locator("#feedback-summary").fill("Add a dark chart theme")
    dialog.get_by_role("button", name="Send feedback").click()
    expect(dialog.locator("#feedback-dialog-title")).to_have_text("Thank you, Sam")
    expect(dialog).to_contain_text("Reference FB-0001")
    expect(dialog).to_contain_text("Add a dark chart theme")

    request = db.scalars(select(FeedbackRequest)).one()
    assert request.kind == "idea" and request.page_url == "/" and "window" in request.browser
    assert db.scalars(select(FeedbackFile.filename)).all() == ["screenshot.png"]

    dialog.get_by_role("link", name="Send another").click()
    expect(dialog.locator("#feedback-summary")).to_be_visible()
    dialog.get_by_role("link", name="Cancel").click()
    expect(page.locator("#feedback-dialog")).to_have_count(0)
    assert page.evaluate("window.__csp") == []
    assert page.evaluate("window.__errors") == []


def test_a_refused_form_stays_in_the_pop_up_with_its_files(page, live_server, user_factory, db):
    dialog = open_pop_up(page, live_server, user_factory())
    dialog.get_by_text("Something is wrong").click()
    page.evaluate(PASTE_A_PICTURE)
    dialog.locator("#feedback-summary").fill("It is blank")
    dialog.locator("#feedback-details").evaluate("el => el.removeAttribute('required')")
    dialog.get_by_role("button", name="Send feedback").click()
    expect(dialog.get_by_text("Say what happened.")).to_be_visible()
    expect(dialog.locator("[data-feedback-list]")).to_contain_text("screenshot.png")
    assert db.scalars(select(FeedbackRequest)).all() == []
    assert page.evaluate("window.__csp") == []
    assert page.evaluate("window.__errors") == []


def test_a_reviewer_opens_a_request_in_the_panel_and_asks_a_question(page, live_server, user_factory, give_set, db):
    sam = user_factory(full_name="Sam Taylor")
    reviewer = user_factory(full_name="Robin Lee")
    give_set(["manage_feedback"], user=reviewer)
    made = service.create_request(
        db, sam, "problem", "Chart is blank", "Nothing shows.", "Report", "/", "Edge on Windows",
        [service.ValidFile("shot.png", "image/png", _png())],
    )  # fmt: skip
    db.commit()
    page.add_init_script(RECORDER)
    browser_sign_in(page, live_server, reviewer)
    page.goto(f"{live_server}/admin/feedback")
    page.get_by_role("cell", name="Sam Taylor").click()  # anywhere on the row
    panel = page.locator("#feedback-panel")
    expect(panel).to_be_visible()
    expect(panel.locator("[data-panel-feedback]")).to_contain_text("Nothing shows.")
    expect(panel.locator("img.feedback-thumb")).to_have_count(1)
    assert panel.locator("img.feedback-thumb").evaluate("img => img.naturalWidth") == 1
    assert f"request={made.id}" in page.url

    expect(panel.get_by_role("button", name="Send the update")).to_be_visible()
    panel.get_by_text("Question", exact=True).click()
    expect(panel.get_by_role("button", name="Ask the question")).to_be_visible()
    expect(panel.locator("[data-reply-label]")).to_have_text("Your question")
    panel.locator("textarea[name=body]").fill("Which browser do you use?")
    panel.get_by_role("checkbox", name="Email Sam Taylor").uncheck()
    panel.get_by_role("button", name="Ask the question").click()
    expect(panel.locator(".feedback-thread")).to_contain_text("Which browser do you use?")
    expect(panel).to_contain_text("Question sent.")
    expect(panel.locator("select[name=status]")).to_have_value("waiting")

    panel.get_by_role("button", name="Close").click()
    expect(panel).to_be_hidden()
    # the table shows the change once the panel closes
    expect(page.locator(f'tr[data-request="{made.id}"]')).to_contain_text("Waiting for an answer")
    assert "request=" not in page.url
    assert page.evaluate("window.__csp") == []
    assert page.evaluate("window.__errors") == []


def test_the_head_status_goes_with_an_update_and_a_status_save_keeps_the_reply(
    page, live_server, user_factory, give_set, db
):
    sam = user_factory(full_name="Sam Taylor")
    reviewer = user_factory(full_name="Robin Lee")
    give_set(["manage_feedback"], user=reviewer)
    made = service.create_request(db, sam, "idea", "Dark theme", "", "Report", "/", "", [])
    db.commit()
    page.add_init_script(RECORDER)
    browser_sign_in(page, live_server, reviewer)
    page.goto(f"{live_server}/admin/feedback?request={made.id}")
    panel = page.locator("#feedback-panel")
    expect(panel.locator("[data-panel-feedback]")).to_be_visible()

    # a status save keeps what is typed in the reply box
    panel.locator("textarea[name=body]").fill("Half written")
    panel.get_by_text("Question", exact=True).click()
    panel.locator("select[name=status]").select_option("under_review")
    panel.get_by_role("button", name="Save status").click()
    expect(panel.locator("[data-panel-notice]")).to_have_text("Status saved: Under review.")
    expect(panel.locator("textarea[name=body]")).to_have_value("Half written")
    expect(panel.get_by_role("button", name="Ask the question")).to_be_visible()

    # an update carries the status chosen in the head
    panel.get_by_text("Update", exact=True).click()
    panel.locator("select[name=status]").select_option("planned")
    panel.locator("textarea[name=body]").fill("Planned for March.")
    panel.get_by_role("checkbox", name="Email Sam Taylor").uncheck()
    panel.get_by_role("button", name="Send the update").click()
    expect(panel.locator(".feedback-thread")).to_contain_text("Planned for March.")
    expect(panel.locator(".feedback-thread")).to_contain_text("Status: Planned")
    expect(panel.locator("select[name=status]")).to_have_value("planned")
    db.expire_all()
    assert db.get(FeedbackRequest, made.id).status == "planned"
    assert page.evaluate("window.__csp") == []
    assert page.evaluate("window.__errors") == []


def test_on_a_phone_the_link_stays_on_the_title_row_and_no_page_scrolls_sideways(page, live_server, user_factory):
    page.set_viewport_size({"width": 390, "height": 900})
    page.add_init_script(RECORDER)
    browser_sign_in(page, live_server, user_factory(is_admin=True))
    for path in ("/admin/users", "/admin/teams", "/", "/admin/permission-sets"):
        page.goto(f"{live_server}{path}")
        link = page.get_by_role("link", name="Feedback on this page").bounding_box()
        title = page.locator("main h1").first.bounding_box()
        assert link["y"] < title["y"] + title["height"] and link["y"] + link["height"] > title["y"], path
        assert page.evaluate("document.scrollingElement.scrollWidth") <= 390, path
    for path in ("/admin/regions", "/admin/locations", "/admin/business-lines"):
        page.goto(f"{live_server}{path}")
        assert page.evaluate("document.scrollingElement.scrollWidth") <= 390, path
        tabs = page.locator("nav.tabs").bounding_box()
        assert tabs["x"] >= 0 and tabs["x"] + tabs["width"] <= 390, path
    assert page.evaluate("window.__csp") == []
    assert page.evaluate("window.__errors") == []
