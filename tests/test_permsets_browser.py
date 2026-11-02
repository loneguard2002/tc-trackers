"""The Permission sets cards in a real browser: live counts, "Changed" marks, the save note, and fit (database)."""

from __future__ import annotations

import re

import pytest
from conftest import browser_sign_in
from playwright.sync_api import expect
from test_report_page_browser import RECORDER

pytestmark = pytest.mark.browser


def test_ticking_updates_the_card_and_the_note(page, live_server, user_factory, give_set):
    give_set(["view_activity"], user=user_factory(), name="PMO")
    page.add_init_script(RECORDER)
    browser_sign_in(page, live_server, user_factory(is_admin=True))
    page.goto(f"{live_server}/admin/permission-sets")
    card = page.locator("article[data-set-card]", has_text="PMO")
    note = page.locator("[data-dirty-note]")
    expect(note).to_have_text("No unsaved changes")

    page.get_by_label("Manage users for PMO").check()
    expect(card.locator("[data-count]")).to_have_text("2/7")
    expect(card).to_have_class(re.compile(r"\bis-changed\b"))
    expect(card.get_by_text("Changed")).to_be_visible()
    expect(note).to_have_text("Unsaved changes in 1 set")

    page.get_by_label("Manage users for PMO").uncheck()
    expect(card.locator("[data-count]")).to_have_text("1/7")
    expect(card.get_by_text("Changed")).to_be_hidden()
    expect(note).to_have_text("No unsaved changes")

    page.get_by_label("Create trackers for PMO").check()
    page.get_by_role("button", name="Save permissions").click()
    expect(page.get_by_text("Saved the permissions.")).to_be_visible()
    expect(page.locator("article[data-set-card]", has_text="PMO").locator("[data-count]")).to_have_text("2/7")
    assert page.evaluate("window.__csp") == []
    assert page.evaluate("window.__errors") == []


@pytest.mark.parametrize("size", [(1440, 900), (390, 844)], ids=["desktop", "phone"])
def test_cards_fit_without_page_scroll(page, live_server, user_factory, give_set, size):
    give_set(
        ["manage_users", "manage_teams"],
        user=user_factory(),
        name=("Programme management office and delivery assurance " * 2)[:100],
    )
    give_set(["view_activity"], user=user_factory(), name="PMO")
    page.set_viewport_size({"width": size[0], "height": size[1]})
    page.add_init_script(RECORDER)
    browser_sign_in(page, live_server, user_factory(is_admin=True))
    page.goto(f"{live_server}/admin/permission-sets")
    expect(page.locator("article[data-set-card]")).to_have_count(2)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert page.evaluate("window.__csp") == []
    assert page.evaluate("window.__errors") == []


def test_cards_scroll_clear_of_the_top_bar(page, live_server, user_factory):
    browser_sign_in(page, live_server, user_factory(is_admin=True))
    page.goto(f"{live_server}/admin/permission-sets")
    margin = page.evaluate("parseFloat(getComputedStyle(document.getElementById('new-set')).scrollMarginTop)")
    bar = page.evaluate("document.querySelector('.topbar').getBoundingClientRect().bottom")
    assert margin > bar


# Before the deferred script runs, tick a box as a browser does when it restores a form after a reload or Back.
RESTORED_TICK = """
document.addEventListener("readystatechange", function () {
  if (document.readyState !== "interactive") return;
  var box = document.querySelector("article[data-set-card] input[value=manage_users]");
  if (box) box.checked = true;
});
"""


def test_ticks_restored_by_the_browser_count_as_unsaved(page, live_server, user_factory, give_set):
    give_set(["view_activity"], user=user_factory(), name="PMO")
    browser_sign_in(page, live_server, user_factory(is_admin=True))
    page.add_init_script(RESTORED_TICK)
    page.goto(f"{live_server}/admin/permission-sets")
    card = page.locator("article[data-set-card]", has_text="PMO")
    expect(page.locator("[data-dirty-note]")).to_have_text("Unsaved changes in 1 set")
    expect(card.get_by_text("Changed")).to_be_visible()
