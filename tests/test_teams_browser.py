"""The team move preview and confirmation in a real browser, under the Content Security Policy (database)."""

from __future__ import annotations

import pytest
from conftest import browser_sign_in
from playwright.sync_api import expect
from test_report_page_browser import RECORDER

pytestmark = pytest.mark.browser


def test_move_preview_then_confirm(page, live_server, team_factory, user_factory, tracker_factory, add_member):
    infra = team_factory(name="Infrastructure")
    apps = team_factory(name="Applications")
    windows = team_factory(name="Windows", parent=infra)
    tracker_factory(name="Laptop refresh", team_id=windows.id)
    add_member(infra, user_factory(full_name="Head of Infrastructure"), "owner")
    admin = user_factory(is_admin=True)
    page.add_init_script(RECORDER)
    browser_sign_in(page, live_server, admin)
    page.goto(f"{live_server}/admin/teams/{windows.id}")

    page.click("#move >> text=Move…")
    page.select_option("#parent_id", str(apps.id))
    page.click("text=Show what changes")
    expect(page.locator("main, body").first).to_contain_text("Head of Infrastructure loses Owner on Laptop refresh.")
    expect(page.locator("body")).to_contain_text("No one gains access.")
    page.get_by_role("button", name="Move Windows").click()
    page.wait_for_load_state("networkidle")

    expect(page.locator(".flash")).to_contain_text("Moved Windows to Applications.")
    expect(page.locator("#move")).to_contain_text("Now below Applications.")
    assert page.evaluate("window.__csp") == []
    assert page.evaluate("window.__errors") == []
