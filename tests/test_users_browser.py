"""The Users list in a real browser: it fits the screen and its actions menu opens (database)."""

from __future__ import annotations

import pytest
from conftest import browser_sign_in
from playwright.sync_api import expect
from test_report_page_browser import RECORDER

pytestmark = pytest.mark.browser


@pytest.mark.parametrize("size", [(1440, 900), (390, 844)], ids=["desktop", "phone"])
def test_users_fit_without_page_scroll(page, live_server, team_factory, user_factory, add_member, give_set, size):
    infra = team_factory(name="Infrastructure")
    windows = team_factory(name="Windows servers", parent=infra)
    apps = team_factory(name="Applications and platform engineering")
    give_set(["view_activity"], team=apps, name="Activity viewers")
    for n in range(8):
        person = user_factory(
            full_name=f"Alexandria Montgomery-Smith {n}", email=f"alexandria.montgomery-smith{n}@example.com"
        )
        add_member(windows, person, "owner")
        add_member(apps, person, "viewer")
        give_set(["manage_users"], user=person, name=f"Directory managers {n}")
    admin = user_factory(is_admin=True)
    page.set_viewport_size({"width": size[0], "height": size[1]})
    page.add_init_script(RECORDER)
    browser_sign_in(page, live_server, admin)
    page.goto(f"{live_server}/admin/users")

    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    first = page.locator("details.row-menu").first
    first.locator("summary").click()
    expect(first.get_by_text("Reset password")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert page.evaluate("window.__csp") == []
    assert page.evaluate("window.__errors") == []
