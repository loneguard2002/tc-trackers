"""Turning an access request down on the Users page, in a real browser under the Content Security Policy (database)."""

from __future__ import annotations

import pytest
from conftest import browser_sign_in
from playwright.sync_api import expect
from test_report_page_browser import RECORDER

pytestmark = pytest.mark.browser


def test_turn_down_asks_in_the_page_then_moves_the_person(page, live_server, user_factory, db):
    admin = user_factory(is_admin=True)
    sam = user_factory(full_name="Sam Taylor", status="pending", auth_source="sso", password_hash=None)
    page.add_init_script(RECORDER)
    browser_sign_in(page, live_server, admin)
    page.goto(f"{live_server}/admin/users")
    expect(page.locator(".nav-count")).to_have_text("1 waiting for approval")
    page.get_by_role("button", name="Turn down…").click()
    question = page.locator("[data-confirm-box]")
    expect(question).to_be_visible()
    expect(question).to_contain_text("Turn down Sam Taylor?")
    page.get_by_role("button", name="Keep waiting").click()
    expect(question).to_be_hidden()
    page.get_by_role("button", name="Turn down…").click()
    with page.expect_navigation():
        page.get_by_role("button", name="Turn down", exact=True).click()
    expect(page.locator("#section-declined")).to_contain_text("Turned down")
    expect(page.locator(".declined-section")).to_contain_text("Sam Taylor")
    expect(page.locator(".nav-count")).to_have_count(0)
    db.refresh(sam)
    assert sam.status == "declined"
    assert page.evaluate("window.__csp") == []
    assert page.evaluate("window.__errors") == []
