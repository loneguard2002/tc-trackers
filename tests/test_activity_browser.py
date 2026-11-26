"""The Activity page in a real browser: an email stays whole and the page does not scroll sideways (database)."""

from __future__ import annotations

import pytest
from conftest import browser_sign_in
from playwright.sync_api import expect
from test_report_page_browser import RECORDER

from tracker.models import AuditLog

pytestmark = pytest.mark.browser

# The number of lines a span's text is drawn on: a range yields one client rectangle for each line box.
LINES = """el => {
    const range = document.createRange();
    range.selectNodeContents(el);
    return range.getClientRects().length;
}"""


def deletion_entries(ann, jordan, tracker, mary, alexandria) -> list[AuditLog]:
    """The entries that deleting a person writes, as the Activity page shows them: each removal, then the summary.

    Two more entries name people whose emails hold hyphens, which a line may break at.
    """

    def entry(action, entity, entity_id, detail, tracker_id=None, by=ann, affecting=jordan) -> AuditLog:
        return AuditLog(
            user_id=by.id,
            target_user_id=affecting.id,
            tracker_id=tracker_id,
            action=action,
            entity=entity,
            entity_id=str(entity_id),
            detail=detail,
        )

    return [
        entry("team_member_removed", "team", 1, {"team": "Windows", "role": "editor"}),
        entry("region_access_removed", "region", 1, {"region": "EMEA", "role": "viewer"}),
        entry("role_removed", "user", jordan.id, {"before": "owner", "after": None}, tracker.id),
        entry("settings_updated", "tracker", tracker.id, {"lead": ["Jordan Lee", None]}, tracker.id),
        entry("recipient_removed", "email_settings", jordan.email, {"email": jordan.email}, tracker.id),
        entry(
            "report_send_failed",
            "report_send",
            1,
            {
                "recipient_count": 0,
                "recipients": [],
                "trigger": "manual",
                "status": "failed",
                "week_ending": "2026-09-04",
                "attempts": 1,
                "error": "No recipients left",
            },
            tracker.id,
        ),
        entry(
            "user_deleted",
            "user",
            jordan.id,
            {
                "name": "Jordan Lee",
                "email": jordan.email,
                "administrator": True,
                "teams": 1,
                "region access": 1,
                "tracker roles": 1,
                "permission sets": 1,
                "trackers led": 1,
                "report emails": 2,
            },
        ),
        entry("user_approved", "user", mary.id, None, by=ann, affecting=mary),
        entry("user_enabled", "user", alexandria.id, None, by=mary, affecting=alexandria),
    ]


@pytest.mark.parametrize("width", [1440, 390], ids=["desktop", "phone"])
def test_activity_emails_stay_whole_and_the_page_does_not_scroll_sideways(
    page, live_server, db, user_factory, tracker_factory, width
):
    ann = user_factory(full_name="Ann Admin", email="ann.admin@example.com", is_admin=True)
    jordan = user_factory(full_name="Jordan Lee", email="jordan.lee@example.com", status="deleted")
    mary = user_factory(full_name="Mary-Jane Smith", email="mary-jane.smith@example.com")
    alexandria = user_factory(
        full_name="Alexandria Montgomery-Smith", email="alexandria.montgomery-smith@example-corporation.example.com"
    )
    db.add_all(deletion_entries(ann, jordan, tracker_factory(name="Desktop rollout"), mary, alexandria))
    db.commit()
    page.set_viewport_size({"width": width, "height": 900})
    page.add_init_script("localStorage.setItem('tracker-theme', 'dark')")
    browser_sign_in(page, live_server, ann)
    page.goto(f"{live_server}/admin/activity")
    assert page.evaluate("document.documentElement.getAttribute('data-theme')") == "dark"

    emails = page.locator("table.activity-table .member-email")
    assert emails.count() >= 18  # both people on each of the nine entries (and Ann's own sign-in)
    for index in range(emails.count()):  # Performed by and User affected, on every row
        email = emails.nth(index)
        assert email.evaluate(LINES) == 1, (email.inner_text(), email.bounding_box())
    # The table may scroll inside its own wrapper, but the page itself must not.
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def _open(page, live_server, admin, url="/admin/activity"):
    page.add_init_script(RECORDER)
    browser_sign_in(page, live_server, admin)
    page.goto(f"{live_server}{url}")


def _clean(page):
    assert page.evaluate("window.__csp") == []
    assert page.evaluate("window.__errors") == []


def _entries(db, count: int, user) -> None:
    db.add_all(
        AuditLog(
            user_id=user.id, action="entry_created", entity="entry", entity_id=str(n), detail={"note": f"note-{n}"}
        )
        for n in range(count)
    )
    db.commit()


def test_typing_a_search_and_pressing_enter_filters_the_log(page, live_server, db, user_factory):
    ann = user_factory(full_name="Ann Admin", email="ann.admin@example.com", is_admin=True)
    _entries(db, 3, ann)
    db.add(AuditLog(action="team_created", entity="team", entity_id="1", detail={"name": "Kestrelwing"}))
    db.commit()
    _open(page, live_server, ann)
    page.fill("#filter-q", "kestrelwing")
    page.press("#filter-q", "Enter")
    page.wait_for_url("**q=kestrelwing**")
    expect(page.locator("tr[data-entry]")).to_have_count(1)
    expect(page.locator(".pager-count")).to_have_text("Showing 1 of 5 entries")
    assert page.locator("a", has_text="Clear filters").count() == 1
    _clean(page)


def test_a_heading_click_sorts_and_page_2_opens(page, live_server, db, user_factory):
    ann = user_factory(full_name="Ann Admin", email="ann.admin@example.com", is_admin=True)
    _entries(db, 40, ann)
    _open(page, live_server, ann)
    expect(page.locator("tr[data-entry]")).to_have_count(25)
    page.click("th a.sort-button:has-text('Time')")
    page.wait_for_url("**sort=time**")
    assert page.locator("th", has_text="Time").get_attribute("aria-sort") == "ascending"
    page.click(".pager-pages a[aria-label='Page 2']")
    page.wait_for_url("**page=2**")
    assert "sort=time" in page.url
    expect(page.locator("tr[data-entry]")).to_have_count(16)  # 41 entries with Ann's sign-in
    expect(page.locator(".pager-count")).to_have_text("Showing 26–41 of 41 entries")
    assert page.locator('.pager-pages a[aria-current="page"]').inner_text() == "2"
    _clean(page)


def test_on_a_phone_the_rows_are_cards_and_nothing_scrolls_sideways(page, live_server, db, user_factory):
    ann = user_factory(full_name="Ann Admin", email="ann.admin@example.com", is_admin=True)
    _entries(db, 5, ann)
    page.set_viewport_size({"width": 390, "height": 900})
    _open(page, live_server, ann)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert page.locator("table.activity-table thead").is_hidden()
    assert page.locator("tr[data-entry]").first.evaluate("el => getComputedStyle(el).display") == "flex"
    label = page.locator("tr[data-entry] td[data-label='Action']").first
    assert label.evaluate("el => getComputedStyle(el, '::before').content") == '"Action "'
    _clean(page)


def test_the_wide_table_stays_reachable_on_a_desktop_window(page, live_server, db, user_factory):
    ann = user_factory(
        full_name="Alexandria Montgomery-Smith",
        email="alexandria.montgomery-smith@example-corporation.example.com",
        is_admin=True,
    )
    other = user_factory(
        full_name="Bartholomew Featherstonehaugh",
        email="bartholomew.featherstonehaugh@another-long-example-company.example.org",
    )
    db.add_all(
        AuditLog(
            user_id=ann.id,
            target_user_id=other.id,
            action="role_removed",
            entity="user",
            entity_id=str(n),
            detail={"before": "owner", "after": None},
        )
        for n in range(4)
    )
    db.commit()
    page.set_viewport_size({"width": 1024, "height": 900})
    _open(page, live_server, ann)
    frame = page.locator(".section-table[data-table-frame]").first
    page.wait_for_function("document.readyState === 'complete'")
    fits = frame.evaluate("el => el.scrollWidth <= el.clientWidth + 1")
    scrolls = frame.evaluate("el => getComputedStyle(el).overflowX") == "auto"
    assert fits or scrolls
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    for width in (900, 1200):  # and again after a resize
        page.set_viewport_size({"width": width, "height": 900})
        page.wait_for_timeout(200)
        assert frame.evaluate("el => el.scrollWidth <= el.clientWidth + 1") or (
            frame.evaluate("el => getComputedStyle(el).overflowX") == "auto"
        )
    _clean(page)


def test_without_javascript_a_wide_activity_table_scrolls_inside_its_wrapper(
    browser, live_server, db, user_factory, tracker_factory
):
    ann = user_factory(full_name="Ann Admin", email="ann.admin@example.com", is_admin=True)
    jordan = user_factory(full_name="Jordan Lee", email="jordan.lee@example.com", status="deleted")
    mary = user_factory(full_name="Mary-Jane Smith", email="mary-jane.smith@example.com")
    alexandria = user_factory(
        full_name="Alexandria Montgomery-Smith", email="alexandria.montgomery-smith@example-corporation.example.com"
    )
    db.add_all(deletion_entries(ann, jordan, tracker_factory(name="Desktop rollout"), mary, alexandria))
    db.commit()
    context = browser.new_context(java_script_enabled=False, viewport={"width": 1024, "height": 900})
    try:
        page = context.new_page()
        browser_sign_in(page, live_server, ann)
        page.goto(f"{live_server}/admin/activity")
        frame = page.locator("[data-table-frame]")
        # Without lists.js nothing marks a wide table, so the wrapper must scroll (or the table fit); it must not clip.
        overflow = frame.evaluate("el => getComputedStyle(el).overflowX")
        assert overflow in ("auto", "scroll") or frame.evaluate("el => el.scrollWidth <= el.clientWidth"), overflow
        assert overflow != "clip"
    finally:
        context.close()
