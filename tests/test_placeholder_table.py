"""The placeholder table on Email settings (the report subject) and on a tracker's Email tab (the message body), and the
subject's character count and example. The buttons' behaviour is in test_email_settings_browser.py."""

from __future__ import annotations

import re

from conftest import sign_in

from tracker.mail.compose import BLOCK_PLACEHOLDERS, PLACEHOLDERS, SAMPLE_CONTEXT
from tracker.models import AppSetting


def _rows(page: str) -> list[str]:
    return re.findall(r'<tr data-placeholder="(\w+)">', page)


def test_email_settings_lists_the_subject_placeholders_with_examples(client, logged_in_admin):
    page = client.get("/admin/smtp").get_data(as_text=True)
    assert _rows(page) == [name for name in PLACEHOLDERS if name not in BLOCK_PLACEHOLDERS]
    assert "What it gives" in page and SAMPLE_CONTEXT["verdict"] in page
    assert 'data-target="report_email_subject" data-mode="toggle"' in page
    assert 'aria-label="Insert {{status}}" hidden>' in page  # shown by the script only


def test_email_settings_counts_the_subject_and_fills_the_example(client, db, logged_in_admin):
    db.add(AppSetting(key="report_email_subject", value="[PMO] {{tracker_name}} {{status}}"))
    db.commit()
    page = client.get("/admin/smtp").get_data(as_text=True)
    assert "33 / 300" in page  # before the script runs
    assert "[PMO] Network refresh Green" in page
    field = re.search(r'<input id="report_email_subject"[^>]*>', page).group(0)
    assert "maxlength" not in field and 'data-max-length="300"' in field  # a long paste is no longer cut silently


def test_a_tracker_email_tab_lists_every_placeholder_with_this_weeks_values(
    client, db, tracker_factory, user_factory, grant
):
    tracker, owner = tracker_factory(name="Core Rollout"), user_factory()
    grant(owner, tracker, "owner")
    sign_in(client, owner)
    page = client.get(f"/trackers/{tracker.id}/mail").get_data(as_text=True)
    assert _rows(page) == list(PLACEHOLDERS)
    assert 'data-target="body_html" data-mode="repeat"' in page
    row = re.search(r'<tr data-placeholder="tracker_name">.*?</tr>', page, re.S).group(0)
    assert "Core Rollout" in row
    block = re.search(r'<tr data-placeholder="risks">.*?</tr>', page, re.S).group(0)
    assert "A block in the email" in block
