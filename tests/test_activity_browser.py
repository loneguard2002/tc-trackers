"""The Activity page in a real browser: an email stays whole and the page does not scroll sideways (database)."""

from __future__ import annotations

import pytest
from conftest import browser_sign_in

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
