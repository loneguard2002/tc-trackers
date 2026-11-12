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


def test_users_table_fits_its_box_at_1440(page, live_server, team_factory, user_factory, add_member, give_set):
    infra = team_factory(name="Infrastructure")
    windows = team_factory(name="Windows servers", parent=infra)
    apps = team_factory(name="Applications and platform engineering")
    give_set(["manage_teams"], team=infra, name="Team managers (through Infrastructure)")
    for n in range(4):
        person = user_factory(
            full_name=f"Alexandria Montgomery-Smith {n}",
            email=f"alexandria.montgomery-smith-with-a-long-address{n}@example-corporation.example.com",
            is_admin=n == 0,
        )
        add_member(windows, person, "owner")
        add_member(apps, person, "viewer")
        give_set(["manage_teams"], user=person, name=f"Team managers (through Infrastructure {n})")
    admin = user_factory(is_admin=True)
    page.set_viewport_size({"width": 1440, "height": 900})
    browser_sign_in(page, live_server, admin)
    page.goto(f"{live_server}/admin/users")
    box = page.locator(".section-table:has(table.user-table)")
    fit = box.evaluate("el => [el.scrollWidth, el.clientWidth]")
    assert fit[0] <= fit[1], fit
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    for text in ("Access", "More"):
        button = box.locator("tbody tr").first.get_by_text(text, exact=False).first
        assert button.bounding_box()["height"] < 40


def test_users_table_sorts_by_each_column(page, live_server, user_factory):
    user_factory(full_name="Bea Sso", auth_source="sso", password_hash=None)
    user_factory(full_name="Cal Local", status="disabled")
    admin = user_factory(full_name="Ann Admin", is_admin=True)
    page.add_init_script(RECORDER)
    browser_sign_in(page, live_server, admin)
    page.goto(f"{live_server}/admin/users")
    names = page.locator("#people-table tbody .member-name")

    def sort_by(label: str) -> list[str]:
        page.get_by_role("button", name=label, exact=True).click()
        return [name.split(" (you)")[0] for name in names.all_inner_texts()]

    assert sort_by("Sign-in") == ["Ann Admin", "Cal Local", "Bea Sso"]
    expect(page.locator("th", has_text="Sign-in")).to_have_attribute("aria-sort", "ascending")
    assert sort_by("Sign-in") == ["Bea Sso", "Ann Admin", "Cal Local"]
    assert sort_by("Administrator") == ["Bea Sso", "Cal Local", "Ann Admin"]
    assert sort_by("Status") == ["Ann Admin", "Bea Sso", "Cal Local"]
    assert sort_by("Name") == ["Ann Admin", "Bea Sso", "Cal Local"]
    assert sort_by("Name") == ["Cal Local", "Bea Sso", "Ann Admin"]
    assert page.evaluate("window.__csp") == []
    assert page.evaluate("window.__errors") == []
