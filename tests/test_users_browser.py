"""The Users list in a real browser: it fits the screen and its icon buttons name themselves (database)."""

from __future__ import annotations

import pytest
from conftest import browser_sign_in
from playwright.sync_api import expect
from test_report_page_browser import RECORDER

from tracker.auth.passwords import verify_password

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
    first = page.locator("#people-table tbody tr").first.locator(".button-icon").nth(2)
    first.hover()
    expect(first.locator(".icon-tip")).to_have_css("opacity", "1")  # the word shows above the button
    assert first.locator(".icon-tip").inner_text() in ("Make administrator", "Remove administrator")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert page.evaluate("window.__csp") == []
    assert page.evaluate("window.__errors") == []


@pytest.mark.parametrize("width", [1440, 1280, 1024, 993, 900, 721])
def test_filtered_users_fit_with_clear_in_view(
    page, live_server, team_factory, user_factory, add_member, give_set, width
):
    """After Apply, Clear shows as a button beside Apply, and neither the filters nor the table spill out of the box."""
    apps = team_factory(name="Applications and platform engineering")
    for n in range(3):
        person = user_factory(
            full_name=f"Alexandria Montgomery-Smith {n}", email=f"alexandria.montgomery{n}@example.com"
        )
        add_member(apps, person, "editor")
        give_set(["manage_teams"], user=person, name=f"Team managers {n}")
    admin = user_factory(is_admin=True)
    page.set_viewport_size({"width": width, "height": 900})
    browser_sign_in(page, live_server, admin)
    page.goto(f"{live_server}/admin/users")
    page.select_option("#filter-status", "active")
    page.get_by_role("button", name="Apply").click()
    clear = page.locator(".user-filters").get_by_role("link", name="Clear")
    expect(clear).to_be_visible()
    form = page.locator(".user-filters").bounding_box()
    box, apply = clear.bounding_box(), page.get_by_role("button", name="Apply").bounding_box()
    assert box["x"] + box["width"] <= form["x"] + form["width"], (box, form)  # Clear sits inside the box
    assert abs(box["y"] - apply["y"]) < 4 and box["x"] > apply["x"]  # beside Apply
    for selector in (".user-filters", ".section-table"):
        fit = page.locator(selector).evaluate("el => [el.scrollWidth, el.clientWidth]")
        assert fit[0] <= fit[1], (selector, fit)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


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
    # the four slots are one line high and line up down the table
    slots = [
        [b["x"] for b in row.locator(".user-tools > *").evaluate_all("els => els.map(e => e.getBoundingClientRect())")]
        for row in box.locator("tbody tr").all()
    ]
    assert all(len(row) == 4 for row in slots), slots
    assert all(row == slots[0] for row in slots), slots
    heights = box.locator(".user-tools").evaluate_all("els => els.map(e => e.getBoundingClientRect().height)")
    assert max(heights) < 40, heights


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
    assert sort_by("Admin") == ["Bea Sso", "Cal Local", "Ann Admin"]
    assert sort_by("Status") == ["Ann Admin", "Bea Sso", "Cal Local"]
    assert sort_by("Name") == ["Ann Admin", "Bea Sso", "Cal Local"]
    assert sort_by("Name") == ["Cal Local", "Bea Sso", "Ann Admin"]
    assert page.evaluate("window.__csp") == []
    assert page.evaluate("window.__errors") == []


@pytest.mark.parametrize("width", [1280, 1440, 1920])
def test_users_filters_sit_on_one_row_ending_with_apply(page, live_server, user_factory, width):
    admin = user_factory(is_admin=True)
    page.set_viewport_size({"width": width, "height": 900})
    browser_sign_in(page, live_server, admin)
    page.goto(f"{live_server}/admin/users")
    search = page.locator("#filter-q").bounding_box()
    apply = page.get_by_role("button", name="Apply").bounding_box()
    for select in ("#filter-status", "#filter-admin", "#filter-sign-in", "#filter-team", "#filter-set"):
        box = page.locator(select).bounding_box()
        assert box["y"] > search["y"] + search["height"], select  # the search has the row above to itself
        assert abs((apply["y"] + apply["height"]) - (box["y"] + box["height"])) < 4, (select, box, apply)
        assert box["x"] + box["width"] <= apply["x"], select  # Apply ends the row


def test_reset_password_opens_a_dialog_that_asks_twice(page, live_server, user_factory, db):
    target = user_factory(full_name="Reset Target", email="reset.target@example.com")
    admin = user_factory(is_admin=True)
    page.add_init_script(RECORDER)
    browser_sign_in(page, live_server, admin)
    page.goto(f"{live_server}/admin/users")
    dialog = page.locator("#reset-dialog")
    row = page.locator("#people-table tbody tr", has_text="Reset Target")
    row.get_by_role("link", name="Reset password").click()
    expect(dialog).to_be_visible()
    expect(dialog).to_contain_text("Sets a new password for Reset Target (reset.target@example.com).")
    expect(page.locator("#reset-password")).to_be_focused()

    # the eye button shows what was typed in its own field, and hides it again
    eye = dialog.get_by_role("button", name="Show password").first
    page.fill("#reset-password", "Peek-at-this-1")
    expect(eye).to_have_attribute("aria-pressed", "false")
    eye.click()
    expect(page.locator("#reset-password")).to_have_attribute("type", "text")
    expect(page.locator("#reset-confirm")).to_have_attribute("type", "password")
    expect(eye).to_have_attribute("aria-pressed", "true")
    eye.click()
    expect(page.locator("#reset-password")).to_have_attribute("type", "password")
    eye.click()

    new_password = "A-new-password-123"
    page.fill("#reset-password", new_password)
    page.fill("#reset-confirm", new_password + "x")
    dialog.get_by_role("button", name="Set password").click()
    expect(dialog).to_be_visible()  # the browser holds the form back: the two do not match
    assert (
        page.evaluate("document.querySelector('#reset-confirm').validationMessage") == "The two passwords do not match."
    )

    dialog.get_by_role("button", name="Cancel").click()
    expect(dialog).to_be_hidden()
    row.get_by_role("link", name="Reset password").click()
    expect(page.locator("#reset-password")).to_have_value("")  # nothing typed is kept
    expect(page.locator("#reset-password")).to_have_attribute("type", "password")  # and nothing is left shown
    page.fill("#reset-password", new_password)
    page.fill("#reset-confirm", new_password)
    dialog.get_by_role("button", name="Set password").click()
    expect(page.get_by_text("Set a new password for Reset Target.")).to_be_visible()
    db.expire_all()
    assert verify_password(new_password, db.get(type(target), target.id).password_hash)
    assert page.evaluate("window.__csp") == []
    assert page.evaluate("window.__errors") == []


def test_access_page_resets_a_password_in_the_dialog(page, live_server, user_factory, db):
    target = user_factory(full_name="Access Target", email="access.target@example.com")
    admin = user_factory(is_admin=True)
    page.add_init_script(RECORDER)
    browser_sign_in(page, live_server, admin)
    page.goto(f"{live_server}/admin/users/{target.id}/access")
    page.get_by_role("link", name="Reset password").click()
    dialog = page.locator("#reset-dialog")
    expect(dialog).to_contain_text("Sets a new password for Access Target (access.target@example.com).")
    new_password = "Another-password-456"
    page.fill("#reset-password", new_password)
    page.fill("#reset-confirm", new_password)
    dialog.get_by_role("button", name="Set password").click()
    expect(page.get_by_text("Set a new password for Access Target.")).to_be_visible()
    db.expire_all()
    assert verify_password(new_password, db.get(type(target), target.id).password_hash)
    assert page.evaluate("window.__csp") == []
    assert page.evaluate("window.__errors") == []
