"""The team move confirmation in a real browser, under the Content Security Policy (database)."""

from __future__ import annotations

import pytest
from conftest import browser_sign_in
from playwright.sync_api import expect
from test_report_page_browser import RECORDER

pytestmark = pytest.mark.browser


def test_move_confirmation_names_the_old_and_new_parent(page, live_server, team_factory, user_factory):
    infra = team_factory(name="Infrastructure")
    apps = team_factory(name="Applications")
    windows = team_factory(name="Windows", parent=infra)
    admin = user_factory(is_admin=True)
    page.add_init_script(RECORDER)
    browser_sign_in(page, live_server, admin)
    page.goto(f"{live_server}/admin/teams/{windows.id}")

    page.select_option("#parent_id-move", str(apps.id))
    page.click("#move [data-ask]")
    box = page.locator("#move [data-confirm-box]")
    expect(box).to_be_visible()
    expect(box).to_contain_text("Move Windows from Infrastructure to Applications?")
    box.locator("[data-confirm-yes]").click()
    page.wait_for_load_state("networkidle")

    expect(page.locator(".flash")).to_contain_text("Moved Windows to Applications.")
    expect(page.locator("#move [data-confirm-box]")).to_contain_text("from Applications to")
    assert page.evaluate("window.__csp") == []
    assert page.evaluate("window.__errors") == []
